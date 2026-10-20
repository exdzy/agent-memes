"""Clip sources. Each provider turns a query or id into :class:`~agent_memes.models.Meme` objects."""

from .base import Page, Provider
from .local import LocalProvider
from .vlipsy import VlipsyProvider, parse_vlipsy_id

__all__ = ["LocalProvider", "Page", "Provider", "VlipsyProvider", "parse_vlipsy_id"]
