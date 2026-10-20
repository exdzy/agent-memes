from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import Meme


@dataclass
class Page:
    items: list[Meme] = field(default_factory=list)
    offset: int = 0
    total: int | None = None

    def to_dict(self, *, compact: bool = True) -> dict:
        return {
            "results": [m.compact() if compact else m.full() for m in self.items],
            "offset": self.offset,
            "count": len(self.items),
            "total": self.total,
            "next_offset": (
                self.offset + len(self.items)
                if self.total is not None and self.offset + len(self.items) < self.total
                else None
            ),
        }


class Provider(Protocol):
    name: str

    def search(self, query: str, *, limit: int, offset: int, safesearch: str) -> Page: ...

    def get(self, item_id: str) -> Meme: ...
