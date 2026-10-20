"""Tiny stdlib HTTP client: polite rate limiting, retries, and API-key redaction."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .errors import MemeError

_KEY_RE = re.compile(r"([?&](?:key|api_key|apikey|token)=)[^&#\s]+", re.IGNORECASE)
RETRY_STATUS = {429, 500, 502, 503, 504}


def redact(text: str) -> str:
    """Strip API keys from URLs / messages before they reach logs or agents."""
    return _KEY_RE.sub(r"\1REDACTED", text)


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        *,
        min_interval: float = 0.35,
        timeout: float = 30.0,
        retries: int = 3,
    ) -> None:
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self._last = 0.0
        self._lock = threading.Lock()

    def _throttle(self) -> None:
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _open(self, url: str):
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
        attempt = 0
        while True:
            self._throttle()
            try:
                return urllib.request.urlopen(request, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in RETRY_STATUS and attempt < self.retries:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.8 * 2**attempt
                    time.sleep(min(delay, 10.0))
                    attempt += 1
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.retries:
                    time.sleep(0.8 * 2**attempt)
                    attempt += 1
                    continue
                reason = getattr(exc, "reason", exc)
                raise MemeError(
                    f"Network error: {redact(str(reason))}",
                    code="network_error",
                    hint="Check your internet connection and try again.",
                    details={"url": redact(url)},
                ) from None

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        try:
            with self._open(url) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            raise http_error(exc, url) from None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MemeError(
                "Upstream returned a non-JSON response.",
                code="upstream_error",
                details={"url": redact(url)},
            ) from None

    def download(self, url: str, dest: Path, *, max_bytes: int = 200 * 1024 * 1024) -> int:
        """Stream ``url`` to ``dest`` atomically. Returns the number of bytes written."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".part-", dir=dest.parent)
        written = 0
        try:
            with os.fdopen(fd, "wb") as out:
                try:
                    with self._open(url) as resp:
                        while chunk := resp.read(1024 * 256):
                            written += len(chunk)
                            if written > max_bytes:
                                raise MemeError("Download exceeds size limit.", code="upstream_error")
                            out.write(chunk)
                except urllib.error.HTTPError as exc:
                    raise http_error(exc, url, api=False) from None
            shutil.move(tmp_name, dest)
            os.chmod(dest, 0o644)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return written


def http_error(exc: urllib.error.HTTPError, url: str, *, api: bool = True) -> MemeError:
    details = {"status": exc.code, "url": redact(url)}
    if not api and exc.code in (401, 403):
        return MemeError("Media host denied access to this file.", code="upstream_error", details=details)
    if exc.code in (401, 403):
        return MemeError(
            "Vlipsy rejected the API key.",
            code="auth_failed",
            hint="Check VLIPSY_API_KEY. Keys are issued by Vlipsy (see `agent-memes auth --help`).",
            details=details,
        )
    if exc.code == 404:
        return MemeError("Not found.", code="not_found", details=details)
    if exc.code == 400:
        return MemeError("Bad request.", code="invalid_input", details=details)
    if exc.code == 429:
        return MemeError(
            "Rate limited by upstream.", code="rate_limited", hint="Wait a bit and retry.", details=details
        )
    hint = (
        "If this persists, the API key may be invalid or the Vlipsy API may be down (`agent-memes doctor --online`)."
        if api and exc.code >= 500
        else None
    )
    return MemeError(f"Upstream error (HTTP {exc.code}).", code="upstream_error", hint=hint, details=details)
