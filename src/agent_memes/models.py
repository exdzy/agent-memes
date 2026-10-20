"""Provider-neutral meme model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Variant:
    """One downloadable video rendition."""

    url: str | None
    watermark_url: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class Meme:
    ref: str  # globally unique, e.g. "vlipsy:V1iupR0X" or "local:/abs/clip.mp4"
    provider: str
    id: str
    title: str
    source: str | None = None  # the show / movie / property ("from" on Vlipsy)
    tags: list[str] = field(default_factory=list)
    rating: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    slug: str | None = None
    page_url: str | None = None
    preview_url: str | None = None
    preview_gif_url: str | None = None
    variants: dict[str, Variant] = field(default_factory=dict)  # "hd", "sd"
    created: str | None = None
    creator: str | None = None
    original_source_url: str | None = None
    local_path: str | None = None
    credit: str | None = None

    @property
    def attribution(self) -> str:
        if self.credit:
            return self.credit
        parts = [f'"{self.title}"']
        if self.source:
            parts.append(f"from {self.source}")
        if self.provider == "vlipsy":
            parts.append(f"via Vlipsy ({self.page_url or 'https://vlipsy.com'})")
        return " ".join(parts)

    @property
    def safe_name(self) -> str:
        import re

        if self.local_path:
            from pathlib import Path

            base = Path(self.local_path).stem
        else:
            base = self.slug or f"{self.source or ''}-{self.title}-{self.id}"
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._")
        return base[:96] or self.id

    def compact(self) -> dict[str, Any]:
        """Small, token-cheap summary for search results."""
        out: dict[str, Any] = {
            "ref": self.ref,
            "title": self.title,
            "from": self.source,
            "duration": round(self.duration, 2) if self.duration else None,
            "rating": self.rating,
            "tags": self.tags[:8],
            "preview": self.preview_url,
            "page_url": self.page_url,
        }
        if self.local_path:
            out["path"] = self.local_path
        return {k: v for k, v in out.items() if v not in (None, [], "")}

    def full(self) -> dict[str, Any]:
        data = asdict(self)
        data["from"] = data.pop("source")
        data["attribution"] = self.attribution
        data["safe_name"] = self.safe_name
        return data

    @classmethod
    def from_full(cls, data: dict[str, Any]) -> Meme:
        data = dict(data)
        data["source"] = data.pop("from", None)
        data.pop("attribution", None)
        data.pop("safe_name", None)
        variants = {k: Variant(**v) for k, v in (data.pop("variants", None) or {}).items()}
        known = set(cls.__dataclass_fields__)
        meme = cls(**{k: v for k, v in data.items() if k in known})
        meme.variants = variants
        return meme
