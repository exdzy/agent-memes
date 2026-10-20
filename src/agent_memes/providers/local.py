"""Local provider: your own clip folders, searchable by filename and optional sidecar tags.

Sidecar format (optional), next to ``clip.mp4`` as ``clip.json`` or ``clip.meme.json``::

    {"title": "Deal with it", "tags": ["cool", "sunglasses"], "from": "My stream", "credit": "..."}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..errors import MemeError
from ..models import Meme
from .base import Page

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".gif"}
MAX_FILES = 20_000


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9']+", text.lower()) if t]


def _sidecar(path: Path) -> dict:
    for candidate in (path.with_suffix(".meme.json"), path.with_suffix(".json")):
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data.get("meme", data) if isinstance(data.get("meme"), dict) else data
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


class LocalProvider:
    name = "local"

    def __init__(self, dirs: list[Path]) -> None:
        self.dirs = [d for d in dirs]

    def _files(self):
        count = 0
        for root in self.dirs:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() in VIDEO_EXTS and path.is_file() and not path.name.startswith("."):
                    yield path
                    count += 1
                    if count >= MAX_FILES:
                        return

    def to_meme(self, path: Path) -> Meme:
        path = path.resolve()
        meta = _sidecar(path)
        title = str(meta.get("title") or path.stem.replace("_", " ").replace("-", " "))
        tags = [str(t) for t in meta.get("tags") or []]
        return Meme(
            ref=f"local:{path}",
            provider="local",
            id=str(path),
            title=title,
            source=meta.get("from") or meta.get("source"),
            tags=tags,
            rating=meta.get("rating"),
            duration=meta.get("duration"),
            local_path=str(path),
            credit=meta.get("credit") or meta.get("attribution"),
            original_source_url=meta.get("original_source_url") or meta.get("page_url"),
        )

    def search(self, query: str, *, limit: int = 10, offset: int = 0, safesearch: str | None = None) -> Page:
        q = _tokens(query)
        scored: list[tuple[float, Meme]] = []
        for path in self._files():
            meme = self.to_meme(path)
            hay_title = set(_tokens(meme.title)) | set(_tokens(path.stem))
            hay_tags = {t for tag in meme.tags for t in _tokens(tag)}
            hay_from = set(_tokens(meme.source or ""))
            if not q:
                score = 1.0
            else:
                score = sum(
                    2.0 if t in hay_tags else 1.5 if t in hay_title else 0.5 if t in hay_from else 0
                    for t in q
                )
                phrase = " ".join(q)
                if phrase in " ".join(_tokens(meme.title)) or any(phrase == tag.lower() for tag in meme.tags):
                    score += 3
            if score > 0:
                scored.append((score, meme))
        scored.sort(key=lambda s: (-s[0], s[1].title))
        window = [m for _, m in scored[offset : offset + max(1, limit)]]
        return Page(items=window, offset=offset, total=len(scored))

    def get(self, item_id: str) -> Meme:
        raw = item_id.split(":", 1)[1] if item_id.startswith("local:") else item_id
        path = Path(raw).expanduser()
        if not path.is_file():
            raise MemeError(f"Local clip not found: {raw}", code="not_found")
        return self.to_meme(path)
