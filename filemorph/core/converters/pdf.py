"""Conversions out of PDF."""
from __future__ import annotations

import io
import re
from pathlib import Path

from ..registry import ConversionError, Ctx, Registry


def open_pdf(src: Path):
    import pymupdf
    try:
        doc = pymupdf.open(src)
    except Exception as e:
        raise ConversionError("This PDF couldn't be opened — it may be damaged.") from e
    if doc.needs_pass:
        raise ConversionError("This PDF is password-protected. Remove the password and try again.")
    if doc.page_count == 0:
        raise ConversionError("This PDF has no pages.")
    return doc


def _page_paths(dst: Path, n: int) -> list[Path]:
    if n == 1:
        return [dst]
    width = max(2, len(str(n)))
    return [dst.with_name(f"{dst.stem} - page {i + 1:0{width}d}{dst.suffix}") for i in range(n)]


def pdf_to_images(src: Path, dst: Path, ctx: Ctx):
    from PIL import Image
    doc = open_pdf(src)
    dpi = int(ctx.opt("dpi", 150))
    q = int(ctx.opt("quality", 90))
    target = ctx.dst_fmt
    n = doc.page_count

    if target == "tiff":  # TIFF holds every page in one file
        def render(i):
            ctx.progress(i / n, f"Rendering page {i + 1} of {n}")
            pix = doc[i].get_pixmap(dpi=dpi)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        # pages are rendered one at a time while writing, not all held in memory at once
        render(0).save(dst, "TIFF", save_all=True, append_images=(render(i) for i in range(1, n)),
                       compression="tiff_lzw")
        return [dst]

    outs = _page_paths(dst, n)
    for i, (page, out) in enumerate(zip(doc, outs)):
        ctx.progress(i / n, f"Rendering page {i + 1} of {n}")
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if target == "jpg":
            im.save(out, "JPEG", quality=q, optimize=True, progressive=True)
        elif target == "webp":
            im.save(out, "WEBP", quality=q, method=5)
        else:
            im.save(out, "PNG", optimize=True)
    return outs


def pdf_to_svg(src: Path, dst: Path, ctx: Ctx):
    doc = open_pdf(src)
    outs = _page_paths(dst, doc.page_count)
    for i, (page, out) in enumerate(zip(doc, outs)):
        ctx.progress(i / doc.page_count, f"Page {i + 1} of {doc.page_count}")
        out.write_text(page.get_svg_image(text_as_path=False), encoding="utf-8")
    return outs


def pdf_to_docx(src: Path, dst: Path, ctx: Ctx):
    open_pdf(src).close()  # friendly errors for encrypted/broken files
    from pdf2docx import Converter
    import logging
    # pdf2docx calls logging.basicConfig(level=INFO) on import and logs through the root logger;
    # turn that back down instead of logging.disable(), which is process-wide and racy.
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("pdf2docx").setLevel(logging.ERROR)
    ctx.progress(0.05, "Analyzing layout")
    cv = Converter(str(src))
    try:
        cv.convert(str(dst), multi_processing=False)
    finally:
        cv.close()


def pdf_to_txt(src: Path, dst: Path, ctx: Ctx):
    doc = open_pdf(src)
    parts = []
    for i, page in enumerate(doc):
        ctx.progress(i / doc.page_count, f"Reading page {i + 1}")
        parts.append(page.get_text("text", sort=True).rstrip())
    text = "\n\n".join(parts).strip()
    if not text:
        raise ConversionError("No text found — this PDF looks like a scan. Try converting it to an image instead.")
    dst.write_text(text + "\n", encoding="utf-8")


def pdf_to_html(src: Path, dst: Path, ctx: Ctx):
    doc = open_pdf(src)
    body = []
    for i, page in enumerate(doc):
        ctx.progress(i / doc.page_count, f"Reading page {i + 1}")
        body.append(f'<section class="page">{page.get_text("xhtml")}</section>')
    title = src.stem.replace("<", "")
    dst.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
        "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:820px;margin:40px auto;"
        "padding:0 20px;line-height:1.5;color:#222}section.page{margin-bottom:48px;"
        "border-bottom:1px solid #ddd;padding-bottom:24px}img{max-width:100%}</style></head><body>"
        + "\n".join(body) + "</body></html>", encoding="utf-8")


def _clean_cell(v):
    """Text from a PDF cell -> (value, excel_number_format). Numbers become real numbers."""
    if v is None:
        return None, None
    v = re.sub(r"\s*\n\s*", " ", str(v)).strip()
    if not v:
        return None, None
    num = v.replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("%", "").replace(" ", "")
    if re.fullmatch(r"-?\(?\d+(\.\d+)?\)?", num):
        neg = num.startswith("(") and num.endswith(")")
        try:
            f = float(num.strip("()"))
        except ValueError:
            return v, None
        f = -f if neg else f
        decimals = len(num.strip("()").split(".")[1]) if "." in num else 0
        dec = ("." + "0" * decimals) if decimals else ""
        if v.endswith("%"):
            return f / 100, f"0{dec}%"
        for sym in ("$", "€", "£"):
            if sym in v:
                return f, f'"{sym}"#,##0{dec}'
        if "," in v:
            return f, f"#,##0{dec}"
        return (int(f) if f.is_integer() and not decimals else f), None
    return v, None


def pdf_to_xlsx(src: Path, dst: Path, ctx: Ctx):
    """Extract tables (one sheet per page with tables). Falls back to text columns."""
    import pdfplumber
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    open_pdf(src).close()
    wb = Workbook()
    wb.remove(wb.active)
    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="EEF0F4")
    found_any = False

    with pdfplumber.open(src) as pdf:
        n = len(pdf.pages)
        for pi, page in enumerate(pdf.pages):
            ctx.progress(pi / n, f"Finding tables on page {pi + 1} of {n}")
            tables = page.extract_tables() or []
            if not tables:
                # try text-alignment detection for borderless tables
                tables = page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"}) or []
                tables = [t for t in tables if len(t) >= 2 and max(len(r) for r in t) >= 2]
            if not tables:
                continue
            found_any = True
            ws = wb.create_sheet(f"Page {pi + 1}")
            r = 1
            for t in tables:
                rows = [[_clean_cell(c) for c in row] for row in t]
                rows = [row for row in rows if any(c[0] is not None for c in row)]
                if not rows:
                    continue
                for ri, row in enumerate(rows):
                    for ci, (val, numfmt) in enumerate(row):
                        cell = ws.cell(row=r, column=ci + 1, value=val)
                        if numfmt:
                            cell.number_format = numfmt
                        if ri == 0:
                            cell.font, cell.fill = bold, fill
                    r += 1
                r += 1  # blank row between tables
            for col in ws.columns:
                width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(60, max(9, width + 2))
            ws.freeze_panes = "A2"

    if not found_any:
        # No tables: put the text into rows, splitting on runs of spaces
        doc = open_pdf(src)
        ws = wb.create_sheet("Text")
        r = 1
        for page in doc:
            for line in page.get_text("text", sort=True).splitlines():
                if line.strip():
                    for ci, part in enumerate(re.split(r"\s{2,}", line.strip())):
                        val, numfmt = _clean_cell(part)
                        cell = ws.cell(row=r, column=ci + 1, value=val)
                        if numfmt:
                            cell.number_format = numfmt
                    r += 1
        if r == 1:
            raise ConversionError("No tables or text found — this PDF looks like a scan.")
    wb.save(dst)


def pdf_to_pptx(src: Path, dst: Path, ctx: Ctx):
    """Each page becomes a full-bleed slide image."""
    from pptx import Presentation
    from pptx.util import Emu
    doc = open_pdf(src)
    first = doc[0].rect
    prs = Presentation()
    prs.slide_width = Emu(int(first.width * 12700))
    prs.slide_height = Emu(int(first.height * 12700))
    blank = prs.slide_layouts[6]
    for i, page in enumerate(doc):
        ctx.progress(i / doc.page_count, f"Page {i + 1} of {doc.page_count}")
        png = page.get_pixmap(dpi=170).tobytes("png")
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(io.BytesIO(png), 0, 0, prs.slide_width, prs.slide_height)
    prs.save(dst)


def register(reg: Registry) -> None:
    reg.add("pdf", ["png", "jpg", "webp"], pdf_to_images, multi=True, label="Rendering pages")
    reg.add("pdf", "tiff", pdf_to_images, label="Rendering pages")
    reg.add("pdf", "svg", pdf_to_svg, multi=True, label="Exporting vector pages")
    reg.add("pdf", "docx", pdf_to_docx, cost=1.0, label="Rebuilding as Word")
    reg.add("pdf", "txt", pdf_to_txt, label="Extracting text")
    reg.add("pdf", "html", pdf_to_html, cost=1.3, label="Extracting content")
    reg.add("pdf", "xlsx", pdf_to_xlsx, label="Extracting tables")
    reg.add("pdf", "pptx", pdf_to_pptx, label="Building slides")
