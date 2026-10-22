from __future__ import annotations

from functools import lru_cache

from ..registry import Registry
from . import documents, images, media, office, pdf, sheets


@lru_cache(maxsize=1)
def build_registry() -> Registry:
    reg = Registry()
    for mod in (images, pdf, documents, sheets, media, office):
        mod.register(reg)
    return reg
