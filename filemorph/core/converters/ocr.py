"""Offline OCR: reading scanned PDFs and photos of documents.

RapidOCR (PP-OCRv6 ONNX models shipped inside its wheel) runs on onnxruntime, entirely on this PC.
Two ways the text is used:
  - prepare():         scanned pages are rebuilt as real, visible text at the same positions, so
                       every existing PDF converter (Word, Excel tables, text, HTML) just works
  - make_searchable(): the scan stays exactly as it looks, with an invisible text layer on top
                       ("Searchable PDF"), sized to each line so selection lines up with the picture
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..registry import ConversionError, Ctx, Registry

MIN_SCORE = 0.5          # lines the recogniser is less sure about are dropped
_TEXT_CHARS = 12         # a page with fewer characters than this has no real text layer
_IMAGE_COVER = 0.3       # ...and counts as scanned when a picture covers this much of it
_WORK_SIDE = 2400        # OCR pages are rendered at about this many pixels on the long side
_lock = threading.Lock()  # one OCR run at a time: onnxruntime already uses every core


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float


@lru_cache(maxsize=1)
def engine():
    import logging
    try:
        from rapidocr import RapidOCR
    except Exception as e:  # pragma: no cover - packaging slip
        raise ConversionError("The text recognition engine is missing from this installation.") from e
    eng = RapidOCR(params={"Global.log_level": "error", "Global.max_side_len": _WORK_SIDE + 100,
                           "Global.text_score": MIN_SCORE})
    for name in ("RapidOCR", "rapidocr"):
        logging.getLogger(name).setLevel(logging.ERROR)
    return eng


def read_image(im) -> list[Line]:
    """Text lines in a PIL image, top to bottom, in pixel coordinates."""
    import numpy as np
    arr = np.asarray(im.convert("RGB"))[:, :, ::-1].copy()  # RapidOCR expects BGR like OpenCV
    with _lock:
        res = engine()(arr)
    lines = []
    for box, text, score in zip(res.boxes if res.boxes is not None else [], res.txts or (), res.scores or ()):
        text = (text or "").strip()
        if not text or score < MIN_SCORE or (len(text) <= 2 and score < 0.85):
            continue  # unsure, or a speck on a photo read as a letter
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        lines.append(Line(text, float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)), float(score)))
    if sum(len(ln.text) for ln in lines) < 3:
        return []  # a stray digit read off a logo or a photo isn't a document
    lines.sort(key=lambda ln: (round(ln.y0 / 8), ln.x0))
    return lines


# ------------------------------------------------------------------ detection
def page_needs_ocr(page) -> bool:
    if len(page.get_text("text").strip()) >= _TEXT_CHARS:
        return False
    area = abs(page.rect) or 1
    covered = 0.0
    for info in page.get_image_info():
        r = page.rect & info["bbox"]
        covered += abs(r) if r.is_valid else 0
    return covered / area >= _IMAGE_COVER


def looks_scanned(path: str | Path, pages: int = 3) -> bool:
    """Quick check for the UI: do the first pages of this PDF lack a text layer?"""
    try:
        import pymupdf
        with pymupdf.open(path) as doc:
            if doc.needs_pass or doc.page_count == 0:
                return False
            return any(page_needs_ocr(doc[i]) for i in range(min(pages, doc.page_count)))
    except Exception:
        return False


# ------------------------------------------------------------------ page reading
def _render(page):
    from PIL import Image
    r = page.rect
    dpi = max(100, min(300, int(_WORK_SIDE / max(r.width, r.height, 1) * 72)))
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), pix.width / max(r.width, 1)


def ocr_page(page) -> list[Line]:
    """OCR one page; returns lines in the page's (displayed) point coordinates."""
    im, k = _render(page)
    out = []
    for ln in read_image(im):
        out.append(Line(ln.text, ln.x0 / k, ln.y0 / k, ln.x1 / k, ln.y1 / k, ln.score))
    return out


def rows(lines: list[Line]) -> list[list[Line]]:
    """Group lines that sit side by side (table cells, columns) into rows, left to right. A scan
    that is a little crooked puts cells of one row at slightly different heights."""
    out: list[list[Line]] = []
    for ln in sorted(lines, key=lambda ln: (ln.y0 + ln.y1) / 2):
        mid, h = (ln.y0 + ln.y1) / 2, ln.y1 - ln.y0
        if out:
            row = out[-1]
            r_mid = sum((x.y0 + x.y1) / 2 for x in row) / len(row)
            r_h = sum(x.y1 - x.y0 for x in row) / len(row)
            if abs(mid - r_mid) < 0.5 * min(h, r_h):
                row.append(ln)
                continue
        out.append([ln])
    return [sorted(r, key=lambda ln: ln.x0) for r in out]


def _levelled(lines: list[Line]) -> list[Line]:
    """Each row on one shared baseline and height, so text extraction reads it as one row."""
    out = []
    for row in rows(lines):
        y0 = sorted(x.y0 for x in row)[len(row) // 2]
        y1 = sorted(x.y1 for x in row)[len(row) // 2]
        out += [Line(x.text, x.x0, y0, x.x1, y1, x.score) for x in row]
    return out


def _columns(table: list[list[Line]]) -> list[tuple[float, float]]:
    """Column spans of a table: overlapping cell spans across its rows merge into one column, so
    left-aligned labels and right-aligned numbers each land in their own column."""
    spans = sorted((c.x0, c.x1) for row in table for c in row)
    cols: list[list[float]] = []
    for a, b in spans:
        if cols and a <= cols[-1][1] + 4:
            cols[-1][1] = max(cols[-1][1], b)
        else:
            cols.append([a, b])
    return [(a, b) for a, b in cols]


def blocks(lines: list[Line]) -> list[tuple]:
    """Reading-order layout of one page: ("para", text, height, bottom, right) and
    ("table", [[cell, ...], ...]).
    Runs of rows with two or more separate pieces become a table."""
    out: list[tuple] = []
    rs = rows(lines)
    right = max((c.x1 for c in lines), default=0)  # the text column's right edge
    left = min((c.x0 for c in lines), default=0)
    i = 0
    while i < len(rs):
        if len(rs[i]) >= 2:
            j = i
            while j < len(rs) and len(rs[j]) >= 2:
                j += 1
            if j - i >= 2:  # a single two-piece line is just text with a big gap
                table = rs[i:j]
                cols = _columns(table)
                grid = []
                for row in table:
                    cells = [""] * len(cols)
                    for c in row:
                        mid = (c.x0 + c.x1) / 2
                        k = next((n for n, (a, b) in enumerate(cols) if a - 4 <= mid <= b + 4), len(cols) - 1)
                        cells[k] = (cells[k] + " " + c.text).strip()
                    grid.append(cells)
                out.append(("table", grid))
                i = j
                continue
        row = rs[i]
        h = sum(c.y1 - c.y0 for c in row) / len(row)
        text = "   ".join(c.text for c in row)
        prev = out[-1] if out and out[-1][0] == "para" else None
        # a line that ran to the right edge and is followed closely by one of the same size wrapped
        wrapped = prev and prev[4] >= left + 0.85 * (right - left) and row[0].y0 - prev[3] < 0.6 * h \
            and abs(prev[2] - h) < 0.25 * h
        if wrapped:
            out[-1] = ("para", prev[1] + " " + text, prev[2], row[-1].y1, row[-1].x1)
        else:
            out.append(("para", text, h, max(c.y1 for c in row), row[-1].x1))
        i += 1
    return out


def _font_for(text: str) -> tuple[str, str | None]:
    """Base-14 Helvetica covers Western text; anything else uses a Windows Unicode font."""
    try:
        text.encode("cp1252")
        return "helv", None
    except UnicodeEncodeError:
        pass
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in ("arialuni.ttf", "segoeui.ttf", "arial.ttf", "msyh.ttc"):
        f = Path(windir) / "Fonts" / name
        if f.exists():
            return "F" + Path(name).stem[:6], str(f)
    return "helv", None


def _put_line(page, ln: Line, invisible: bool) -> None:
    import pymupdf
    h = ln.y1 - ln.y0
    w = ln.x1 - ln.x0
    if h <= 1 or w <= 1:
        return
    fontname, fontfile = _font_for(ln.text)
    fs = h * 0.78
    try:
        width = pymupdf.Font(fontname if not fontfile else None, fontfile=fontfile).text_length(ln.text, fs)
    except Exception:
        width = pymupdf.get_text_length(ln.text, "helv", fs)
    base = pymupdf.Point(ln.x0, ln.y1 - h * 0.2)
    kw = dict(fontname=fontname, fontfile=fontfile)
    if invisible:
        # stretch/squeeze each line to its box, so selecting text highlights the right words
        sx = w / width if width > 0 else 1
        pt = base * page.derotation_matrix
        page.insert_text(pt, ln.text, fontsize=fs, render_mode=3, rotate=page.rotation,
                         morph=(pt, pymupdf.Matrix(sx, 1)), **kw)
    else:
        if width > w * 1.02:  # never run into the next column: shrink the font instead
            fs *= w / width
        page.insert_text(base, ln.text, fontsize=fs, color=(0, 0, 0), **kw)


def _progress(ctx: Ctx, i: int, n: int, span: float = 1.0):
    ctx.progress(span * i / n, f"Reading scanned page {i + 1} of {n}" if n > 1 else "Reading the scan")


def prepare(src: Path, ctx: Ctx) -> Path:
    """The PDF to extract from: `src` itself when every page has text, otherwise a copy whose
    scanned pages are rebuilt as real text. Digital pages are copied untouched."""
    import pymupdf
    from .pdf import open_pdf
    if ctx.opt("ocr", "auto") == "off":
        return src
    with open_pdf(src) as doc:
        todo = [i for i, page in enumerate(doc) if page_needs_ocr(page)]
        if not todo:
            return src
        out = pymupdf.open()
        found = False
        for i, page in enumerate(doc):
            if i not in todo:
                out.insert_pdf(doc, from_page=i, to_page=i)
                continue
            _progress(ctx, todo.index(i), len(todo), 0.6)
            lines = ocr_page(page)
            ctx.scratch.setdefault("ocr_lines", {})[i] = lines
            found = found or bool(lines)
            r = page.rect
            new = out.new_page(width=r.width, height=r.height)
            for ln in _levelled(lines):
                _put_line(new, ln, invisible=False)
        if not found and len(todo) == doc.page_count:
            raise ConversionError("No text found, even after reading the scan. "
                                  "Is the picture sharp and the right way up?")
        ctx.scratch["ocr_all"] = len(todo) == doc.page_count
        dst = ctx.tmpdir / f"ocr-{src.stem[:40]}.pdf"
        out.subset_fonts()
        out.save(dst, garbage=3, deflate=True)
        out.close()
    return dst


def scan_to_docx(dst: Path, ctx: Ctx) -> None:
    """A fully scanned PDF -> a clean, flowing Word document: paragraphs and real tables."""
    import docx
    from docx.shared import Pt
    d = docx.Document()
    pages = ctx.scratch["ocr_lines"]
    for n, i in enumerate(sorted(pages)):
        if n:
            d.add_page_break()
        for b in blocks(pages[i]):
            if b[0] == "para":
                par = d.add_paragraph()
                run = par.add_run(b[1])
                run.font.size = Pt(max(8, min(28, round(b[2] * 0.72))))
            else:
                grid = b[1]
                tbl = d.add_table(rows=len(grid), cols=len(grid[0]))
                tbl.style = "Table Grid"
                for r, cells in enumerate(grid):
                    for c, text in enumerate(cells):
                        tbl.cell(r, c).text = text
                d.add_paragraph()
    d.save(dst)


def scan_tables(ctx: Ctx) -> dict[int, list[list[str]]]:
    """Rows of every OCR'd page, cells split into columns, for Excel."""
    out = {}
    for i, lines in sorted(ctx.scratch.get("ocr_lines", {}).items()):
        grid: list[list[str]] = []
        for b in blocks(lines):
            if b[0] == "para":
                grid.append([b[1]])
            else:
                grid += b[1]
            grid.append([])
        out[i] = grid[:-1]
    return out


def make_searchable(src: Path, dst: Path, ctx: Ctx):
    """PDF -> the same PDF with an invisible, selectable text layer on every scanned page."""
    from .pdf import open_pdf
    with open_pdf(src) as doc:
        todo = [i for i, page in enumerate(doc) if page_needs_ocr(page)]
        if not todo:
            raise ConversionError("This PDF already has selectable text, so there's nothing to read.")
        found = False
        for n, i in enumerate(todo):
            _progress(ctx, n, len(todo))
            page = doc[i]
            page.clean_contents()
            lines = ocr_page(page)
            found = found or bool(lines)
            for ln in lines:
                _put_line(page, ln, invisible=True)
        if not found:
            raise ConversionError("No text found, even after reading the scan. "
                                  "Is the picture sharp and the right way up?")
        doc.subset_fonts()
        doc.save(dst, garbage=3, deflate=True)


def register(reg: Registry) -> None:
    reg.add("pdf", "ocrpdf", make_searchable, cost=1.0, label="Reading the scan")
