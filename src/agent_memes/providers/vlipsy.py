"""Vlipsy provider: the official REST API only (https://docs.vlipsy.com).

This module never scrapes vlipsy.com. It needs an API key issued by Vlipsy,
passed via ``VLIPSY_API_KEY`` (or the user config file). Downloads default to
the watermarked rendition, and every result carries attribution back to Vlipsy.
"""

from __future__ import annotations

import re
import urllib.parse

from ..config import Config
from ..errors import MemeError, invalid
from ..http import HttpClient
from ..models import Meme, Variant
from .base import Page

_ID = r"[A-Za-z0-9]{8}"
_ID_RE = re.compile(rf"^{_ID}$")
_PAGE_RE = re.compile(rf"vlipsy\.com/vlip/(?:[^/?#]*-)?({_ID})(?:[/?#]|$)")
_SHORT_RE = re.compile(rf"vlp\.to/({_ID})(?:[/?#]|$)")
_MEDIA_RE = re.compile(rf"media\.vlipsy\.com/vlips/({_ID})/")

MAX_LIMIT = 100
KEY_HELP = (
    "Set VLIPSY_API_KEY (env var, a git-ignored .env file, or `agent-memes auth set`). "
    "Vlipsy issues API keys on request; see https://docs.vlipsy.com and the API section of "
    "https://vlipsy.com/terms. Without a key, use the local provider (AGENT_MEMES_LOCAL_DIRS)."
)


def parse_vlipsy_id(text: str) -> str | None:
    """Accept ``vlipsy:ID``, a bare 8-char id, a vlipsy.com/vlip/... URL or a vlp.to short link."""
    text = text.strip()
    if text.lower().startswith("vlipsy:"):
        candidate = text.split(":", 1)[1]
        return candidate if _ID_RE.match(candidate) else None
    if _ID_RE.match(text):
        return text
    for regex in (_PAGE_RE, _SHORT_RE, _MEDIA_RE):
        if m := regex.search(text):
            return m.group(1)
    return None


def normalize_query(query: str) -> str:
    # Vlipsy docs: lowercase, strip special characters.
    cleaned = re.sub(r"[^\w\s']", " ", query.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


class VlipsyProvider:
    name = "vlipsy"

    def __init__(self, config: Config, http: HttpClient) -> None:
        self.config = config
        self.http = http

    # -- plumbing -----------------------------------------------------------------
    def _key(self) -> str:
        if not self.config.vlipsy_api_key:
            raise MemeError("No Vlipsy API key configured.", code="missing_api_key", hint=KEY_HELP)
        return self.config.vlipsy_api_key

    def _get(self, path: str, **params):
        params["key"] = self._key()
        return self.http.get_json(f"{self.config.api_base}{path}", params)

    @staticmethod
    def _limit(limit: int) -> int:
        return max(1, min(int(limit), MAX_LIMIT))

    @staticmethod
    def _safesearch(level: str | None) -> str | None:
        return None if level in (None, "", "off") else level

    def _page(self, payload: dict, offset: int) -> Page:
        items = [self.to_meme(raw) for raw in payload.get("data") or [] if isinstance(raw, dict)]
        pagination = payload.get("pagination") or {}
        return Page(
            items=items,
            offset=int(pagination.get("offset", offset) or 0),
            total=pagination.get("total_count"),
        )

    # -- API ----------------------------------------------------------------------
    def search(self, query: str, *, limit: int = 10, offset: int = 0, safesearch: str | None = None) -> Page:
        q = normalize_query(query)
        if not q:
            raise invalid(
                "Search query is empty after normalization.", "Use plain words, e.g. 'this is fine'."
            )
        payload = self._get(
            "/v1/vlips/search",
            q=q,
            limit=self._limit(limit),
            pos=max(0, offset),
            safesearch=self._safesearch(safesearch),
        )
        return self._page(payload, offset)

    def trending(self, *, limit: int = 10, offset: int = 0, safesearch: str | None = None) -> Page:
        payload = self._get(
            "/v1/vlips/trending",
            limit=self._limit(limit),
            pos=max(0, offset),
            safesearch=self._safesearch(safesearch),
        )
        return self._page(payload, offset)

    def get(self, item_id: str) -> Meme:
        vid = parse_vlipsy_id(item_id)
        if not vid:
            raise invalid(
                f"Not a Vlipsy id or URL: {item_id!r}", "Ids look like 'V1iupR0X' or 'vlipsy:V1iupR0X'."
            )
        payload = self._get(f"/v1/vlips/{urllib.parse.quote(vid)}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise MemeError(f"Vlip {vid} not found.", code="not_found")
        return self.to_meme(data)

    def playlists(self, *, limit: int = 25, offset: int = 0) -> dict:
        payload = self._get("/v1/playlists", limit=self._limit(limit), pos=max(0, offset))
        pagination = payload.get("pagination") or {}
        return {
            "results": [
                {
                    "id": p.get("id"),
                    "title": p.get("title"),
                    "count": p.get("vlip_count"),
                    "image": p.get("image"),
                }
                for p in payload.get("data") or []
                if isinstance(p, dict)
            ],
            "offset": pagination.get("offset", offset),
            "total": pagination.get("total_count"),
        }

    def playlist(
        self, playlist_id: str, *, limit: int = 25, offset: int = 0, safesearch: str | None = None
    ) -> Page:
        if not re.match(r"^[A-Za-z0-9_-]{4,32}$", playlist_id):
            raise invalid(f"Not a playlist id: {playlist_id!r}")
        payload = self._get(
            f"/v1/playlists/{playlist_id}/vlips",
            limit=self._limit(limit),
            pos=max(0, offset),
            safesearch=self._safesearch(safesearch),
        )
        return self._page(payload, offset)

    # -- mapping ------------------------------------------------------------------
    @staticmethod
    def to_meme(raw: dict) -> Meme:
        media = raw.get("media") or {}

        def variant(name: str) -> Variant | None:
            m = media.get(name)
            if not isinstance(m, dict) or not (m.get("url") or m.get("watermark")):
                return None
            return Variant(
                url=m.get("url"),
                watermark_url=m.get("watermark"),
                width=m.get("width"),
                height=m.get("height"),
            )

        variants = {k: v for k, v in (("hd", variant("mp4")), ("sd", variant("mp4_small"))) if v}
        preview = media.get("preview") or media.get("preview_small") or {}
        small = media.get("preview_small") or {}
        slug = raw.get("slug")
        vid = str(raw.get("id") or raw.get("objectID") or "")
        creator = raw.get("creator") if isinstance(raw.get("creator"), dict) else {}
        best = variants.get("hd") or variants.get("sd")
        return Meme(
            ref=f"vlipsy:{vid}",
            provider="vlipsy",
            id=vid,
            title=str(raw.get("title") or vid),
            source=raw.get("from") or None,
            tags=[str(t) for t in raw.get("tags") or []],
            rating=raw.get("rating"),
            duration=float(raw["duration"]) if raw.get("duration") else None,
            width=best.width if best else None,
            height=best.height if best else None,
            slug=slug,
            page_url=raw.get("url") or (f"https://vlipsy.com/vlip/{slug}" if slug else None),
            preview_url=preview.get("url"),
            preview_gif_url=small.get("gif"),
            variants=variants,
            created=raw.get("created"),
            creator=creator.get("display_name") or creator.get("username"),
            original_source_url=raw.get("source") if isinstance(raw.get("source"), str) else None,
        )
