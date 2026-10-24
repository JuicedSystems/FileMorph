"""Conversion graph.

Each converter is an edge between two formats. To convert A -> C we search for
the cheapest chain of edges (max 3 hops), so adding one converter automatically
unlocks every format reachable through it.
"""
from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .formats import FORMATS


class ConversionError(Exception):
    """An error whose message is safe to show to the user as-is."""


class Cancelled(Exception):
    pass


@dataclass
class Ctx:
    """Per-conversion context passed to every converter."""
    src_fmt: str
    dst_fmt: str
    tmpdir: Path
    options: dict = field(default_factory=dict)
    progress_cb: Callable[[float, str], None] | None = None
    cancel_event: threading.Event | None = None
    scratch: dict = field(default_factory=dict)  # facts one step shares with itself (e.g. OCR results)

    def progress(self, frac: float, msg: str = "") -> None:
        self.check_cancel()
        if self.progress_cb:
            self.progress_cb(max(0.0, min(1.0, frac)), msg)

    def check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise Cancelled()

    def opt(self, key, default=None):
        return self.options.get(key, default)


# A converter writes `dst` (or several files next to it) and may return the list
# of files it produced. Returning None means "just dst".
ConverterFn = Callable[[Path, Path, Ctx], "list[Path] | None"]


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    fn: ConverterFn
    cost: float = 1.0
    multi: bool = False        # may produce several files -> only valid as the final hop
    label: str = ""            # short description of what this step does
    engine: str = "builtin"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.src}->{self.dst} {self.engine} {self.cost}>"


# Which target families make sense for a given source family. Keeps the graph
# from offering technically-reachable-but-useless conversions (e.g. PNG -> XLSX).
_ALLOWED_CATS = {
    "document": {"document", "image"},
    "sheet": {"sheet", "document"},
    "slides": {"slides", "document", "image"},
    "image": {"image"},
    "audio": {"audio"},
    "video": {"video", "audio"},
}
_EXTRA_TARGETS = {
    "image": {"pdf", "pptx"},
    "gif": {"mp4", "webm", "mov"},
    "mp4": {"gif"}, "mov": {"gif"}, "mkv": {"gif"}, "webm": {"gif"}, "avi": {"gif"}, "wmv": {"gif"},
    "pdf": {"xlsx", "csv", "pptx"},
}
# Targets we never offer for a source family even if reachable.
_BLOCKED = {
    "sheet": {"epub", "md", "rtf", "odt", "doc", "docx", "txt", "svg"},
    "document": {"gif", "ico", "bmp", "svg", "avif", "trace"},
    "slides": {"html", "md", "epub", "rtf", "odt", "doc", "docx", "gif", "ico", "bmp", "svg", "avif", "trace"},
}
_OCR_TARGETS = {"txt", "docx", "xlsx"}
_NO_OCR_IMAGES = {"svg", "ico", "gif"}
_PDF_OK_IMAGE_TARGETS = {"png", "jpg", "webp", "tiff", "svg", "trace"}


def target_allowed(src: str, dst: str, direct: bool = True) -> bool:
    if src == dst or FORMATS[dst].input_only or FORMATS[src].output_only:
        return False
    s_cat = FORMATS[src].category
    if dst in _OCR_TARGETS and s_cat == "image":
        return src not in _NO_OCR_IMAGES  # photos of documents -> text, through OCR
    if FORMATS[dst].category == "tools":
        # SHRINK only where it is one direct step; OCR from PDFs and photos of pages
        return direct if dst != "ocrpdf" else src == "pdf" or (s_cat == "image" and src not in _NO_OCR_IMAGES)
    d_cat = FORMATS[dst].category
    if dst in _BLOCKED.get(s_cat, ()):
        # PDF is the exception: it renders cleanly to SVG
        if not (src == "pdf" and dst in _PDF_OK_IMAGE_TARGETS):
            return False
    if dst in _EXTRA_TARGETS.get(src, ()) or dst in _EXTRA_TARGETS.get(s_cat, ()):
        return True
    return d_cat in _ALLOWED_CATS.get(s_cat, ())


class Registry:
    MAX_HOPS = 3

    def __init__(self) -> None:
        self._edges: dict[str, list[Edge]] = {}

    def add(self, srcs: Iterable[str] | str, dsts: Iterable[str] | str, fn: ConverterFn, *,
            cost: float = 1.0, multi: bool = False, label: str = "", engine: str = "builtin") -> None:
        srcs = [srcs] if isinstance(srcs, str) else list(srcs)
        dsts = [dsts] if isinstance(dsts, str) else list(dsts)
        for s, d in itertools.product(srcs, dsts):
            if s == d:
                continue
            assert s in FORMATS and d in FORMATS, (s, d)
            self._edges.setdefault(s, []).append(
                Edge(s, d, fn, cost, multi, label, engine))

    def edges(self) -> list[Edge]:
        return [e for es in self._edges.values() for e in es]

    def _search(self, src: str) -> dict[str, tuple[float, list[Edge]]]:
        """Cheapest path from src to every reachable format (Dijkstra, hop-limited)."""
        best: dict[tuple[str, int], float] = {}
        result: dict[str, tuple[float, list[Edge]]] = {}
        counter = itertools.count()
        heap: list = [(0.0, next(counter), src, [])]
        while heap:
            cost, _, node, path = heapq.heappop(heap)
            if node != src and (node not in result or cost < result[node][0]):
                result[node] = (cost, path)
            if len(path) >= self.MAX_HOPS or (path and path[-1].multi):
                continue
            for e in self._edges.get(node, []):
                if any(p.src == e.dst for p in path) or e.dst == src:
                    continue  # no cycles
                nc = cost + e.cost + 0.15  # small per-hop penalty
                key = (e.dst, len(path) + 1)
                if best.get(key, float("inf")) <= nc:
                    continue
                best[key] = nc
                heapq.heappush(heap, (nc, next(counter), e.dst, path + [e]))
        return result

    def plan(self, src: str, dst: str) -> list[Edge] | None:
        hit = self._search(src).get(dst)
        return hit[1] if hit else None

    def targets(self, src: str) -> dict[str, list[Edge]]:
        """All formats `src` can sensibly be converted to, with the plan for each."""
        return {d: path for d, (_, path) in self._search(src).items()
                if target_allowed(src, d, direct=len(path) == 1)}


def unique_path(path: Path) -> Path:
    """`report.docx` -> `report (1).docx` if the name is taken."""
    if not path.exists():
        return path
    for i in itertools.count(1):
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
    raise AssertionError  # unreachable
