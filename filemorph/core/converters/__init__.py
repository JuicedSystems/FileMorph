from __future__ import annotations

from functools import lru_cache

from ..registry import Registry
from . import documents, images, media, ocr, office, pdf, sheets, shrink, trace_bw


@lru_cache(maxsize=1)
def build_registry() -> Registry:
    reg = Registry()
    for mod in (images, pdf, documents, sheets, media, office, trace_bw, ocr, shrink):
        mod.register(reg)
    return reg
