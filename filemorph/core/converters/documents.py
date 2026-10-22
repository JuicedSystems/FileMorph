"""Text-document conversions via bundled Pandoc, plus HTML -> PDF rendering."""
from __future__ import annotations

import html as htmllib
import re
import sys
from functools import lru_cache
from pathlib import Path

from .. import proc
from ..registry import ConversionError, Ctx, Registry

PANDOC_IN = {"docx": "docx", "odt": "odt", "rtf": "rtf", "md": "markdown", "html": "html", "epub": "epub"}
PANDOC_OUT = {"docx": "docx", "odt": "odt", "rtf": "rtf", "md": "gfm", "html": "html5", "epub": "epub3", "txt": "plain"}

HTML_CSS = """
body{font-family:"Segoe UI",system-ui,-apple-system,sans-serif;max-width:780px;margin:48px auto;
padding:0 24px;line-height:1.6;color:#1f2328;font-size:16px}
h1,h2,h3{line-height:1.25;margin-top:1.6em}img{max-width:100%}
table{border-collapse:collapse;margin:1em 0}th,td{border:1px solid #d0d7de;padding:6px 10px}
th{background:#f6f8fa}pre,code{font-family:Consolas,monospace;font-size:.9em;background:#f6f8fa}
pre{padding:12px;overflow:auto}blockquote{border-left:4px solid #d0d7de;margin:0;padding-left:16px;color:#57606a}
"""


@lru_cache(maxsize=1)
def pandoc_exe() -> str:
    name = "pandoc.exe" if sys.platform == "win32" else "pandoc"
    try:
        import pypandoc
        cand = Path(pypandoc.__file__).parent / "files" / name
        if cand.exists():
            return str(cand)
        return pypandoc.get_pandoc_path()
    except Exception:
        pass
    raise ConversionError("The document engine (Pandoc) is missing from this installation.")


# Keeps conversions offline and contained: a document can't make FileMorph download remote
# images or pull arbitrary local files (C:\\..., /etc/..., ../../) into the output.
SAFE_RESOURCES_LUA = r"""
local function unsafe(src)
  if src == nil or src == "" then return false end
  local s = src:lower()
  if s:match("^data:") then return false end
  if s:match("^%a[%w+.-]*:") then return true end          -- http:, https:, file:, C: ...
  if s:match("^[/\\]") then return true end                -- /etc/passwd, \\server\share
  if s:match("%.%.[/\\]") or s:match("[/\\]%.%.$") or s == ".." then return true end
  return false
end

function Image(el)
  if unsafe(el.src) then
    return el.caption and #el.caption > 0 and el.caption or pandoc.Str("")
  end
end

-- Raw HTML can't be checked reliably (unquoted, entity-encoded, iframe/object/style/url()...),
-- so it is dropped. The text around it is kept; tags like <b> just lose their effect.
local function drop_raw(el)
  if el.format:match("html") or el.format:match("epub") or el.format:match("xml") then
    return {}
  end
end
RawInline = drop_raw
RawBlock = drop_raw

-- Inline styles can point at files too (background:url(...)).
local function clean_attrs(el)
  local st = el.attributes and el.attributes["style"]
  if st and st:lower():match("url%s*%(") then
    el.attributes["style"] = nil
    return el
  end
end
Div = clean_attrs
Span = clean_attrs
Table = clean_attrs
Header = clean_attrs

-- Metadata in a document's front matter can tell pandoc to read files (cover image, CSS,
-- header includes...). Our own settings come from the command line, not from these.
local RISKY_META = {"cover-image", "epub-cover-image", "css", "stylesheet", "header-includes",
                    "include-before", "include-after", "epub-embedded-fonts", "bibliography",
                    "csl", "reference-doc", "template", "logo", "favicon"}
function Meta(m)
  for _, k in ipairs(RISKY_META) do m[k] = nil end
  return m
end
"""


def _safe_filter(ctx: Ctx) -> Path:
    f = ctx.tmpdir / "safe-resources.lua"
    if not f.exists():
        f.write_text(SAFE_RESOURCES_LUA, encoding="utf-8")
    return f


def pandoc(src: Path, dst: Path, ctx: Ctx, src_fmt: str, dst_fmt: str, extra: list[str] | None = None, cwd=None):
    args = [pandoc_exe(), str(src), "-f", src_fmt, "-t", dst_fmt, "-o", str(dst),
            f"--lua-filter={_safe_filter(ctx)}",
            f"--resource-path={src.parent}"] + (extra or [])  # relative images resolve next to the source
    proc.run(args, ctx, cwd=cwd, env=proc.offline_env(), err_msg="The document couldn't be converted.")


def doc_to_doc(src: Path, dst: Path, ctx: Ctx):
    s, d = ctx.src_fmt, ctx.dst_fmt
    extra: list[str] = ["--wrap=none" if d in ("md", "txt") else "--wrap=auto"]
    title = src.stem
    if d in ("html", "rtf", "epub", "odt", "docx"):
        extra.append("--standalone")
    if d == "html":
        css = ctx.tmpdir / "style.css"
        css.write_text(HTML_CSS, encoding="utf-8")
        extra += ["--embed-resources", f"--css={css}", "-M", f"pagetitle={title}"]
    if d == "epub":
        extra += ["-M", f"title={title}"]
    media = None
    cwd = None
    if d == "md" and s in ("docx", "odt", "epub"):
        # link-safe folder name: pandoc writes it into the Markdown as-is (spaces, &, # would break links)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", dst.stem).strip("._") or "document"
        media = dst.parent / f"{safe}_media"
        extra.append(f"--extract-media={media.name}")  # relative, so links survive moving
        cwd = dst.parent
    if s == "html":
        cwd = cwd or src.parent
    ctx.progress(0.1, "Converting document")
    pandoc(src.resolve(), dst.resolve(), ctx, PANDOC_IN[s], PANDOC_OUT[d], extra, cwd=cwd)
    if media is not None and media.exists():
        return [dst, media]


def txt_to_html(src: Path, dst: Path, ctx: Ctx):
    text = read_text(src)
    blocks = re.split(r"\n\s*\n", text.strip("\n"))
    body = "\n".join("<p>" + "<br>\n".join(htmllib.escape(l) for l in b.splitlines()) + "</p>" for b in blocks)
    dst.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{htmllib.escape(src.stem)}</title>"
                   f"<style>{HTML_CSS}</style></head><body>{body}</body></html>", encoding="utf-8")


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    # Mostly UTF-8 with a few stray bytes? Then keep UTF-8 (reading it as cp1252 would garble every
    # accent). Decide by counting valid multi-byte UTF-8 sequences against invalid bytes.
    valid = len(re.findall(rb"[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3}", raw))
    text = raw.decode("utf-8", errors="replace")
    if valid and valid >= 4 * text.count("\ufffd"):
        return text
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# ---------------------------------------------------------------- HTML -> PDF

PDF_CSS = """
body{font-family:%(font)s;font-size:10.5pt;line-height:1.45;color:#111}
h1{font-size:20pt;margin:0 0 8pt 0}h2{font-size:15pt;margin:14pt 0 6pt 0}h3{font-size:12.5pt;margin:12pt 0 4pt 0}
p{margin:0 0 7pt 0}li{margin-bottom:2pt}
table{border-collapse:collapse;margin:6pt 0}th,td{border:0.6pt solid #888;padding:3pt 5pt;font-size:9.5pt}
th{background-color:#eeeeee;font-weight:bold}
pre,code{font-family:monospace;font-size:8.5pt}blockquote{margin-left:14pt;color:#444}
"""
_FONT_CANDIDATES = [
    # (dir, regular, bold, italic, bolditalic)
    (Path("C:/Windows/Fonts"), "segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    (Path("C:/Windows/Fonts"), "arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    (Path("/usr/share/fonts/truetype/dejavu"), "DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
     "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
    (Path("/usr/share/fonts/truetype/liberation"), "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf",
     "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
]


def _font_setup():
    """Embed a real Unicode font when one is available (accents, symbols, etc.)."""
    for d, *files in _FONT_CANDIDATES:
        if all((d / f).exists() for f in files):
            faces = [("normal", "normal"), ("bold", "normal"), ("normal", "italic"), ("bold", "italic")]
            css = "".join(f"@font-face{{font-family:docfont;src:url({f});font-weight:{w};font-style:{s}}}"
                          for f, (w, s) in zip(files, faces))
            return d, css, "docfont"
    return None, "", "sans-serif"


def html_to_pdf(src: Path, dst: Path, ctx: Ctx):
    html = read_text(src)
    render_html_pdf(html, dst, ctx, base_dir=src.parent)


def render_html_pdf(html: str, dst: Path, ctx: Ctx, base_dir: Path | None = None):
    import pymupdf
    # Strip things the layout engine can't use and that confuse it.
    html = re.sub(r"(?is)<(script|style|noscript|iframe)[^>]*>.*?</\1>", "", html)
    html = re.sub(r"(?is)<link[^>]*>", "", html)
    # Percentage column widths collapse tables in the layout engine; let it size columns itself.
    html = re.sub(r"(?is)<colgroup>.*?</colgroup>", "", html)
    def _strip_widths(m: re.Match) -> str:
        attrs = re.sub(r'(?i)\s(?:width\s*=\s*"?[^\s>"]*"?|style\s*=\s*"[^"]*width[^"]*")', "", m.group(2))
        return f"<{m.group(1)}{attrs}>"
    html = re.sub(r"(?is)<(table|td|th|tr)(\s[^>]*)?>", lambda m: _strip_widths(m) if m.group(2) else m.group(0), html)
    font_dir, font_css, family = _font_setup()
    arch = pymupdf.Archive()
    if base_dir and base_dir.exists():
        arch.add(str(base_dir))
    if font_dir:
        arch.add(str(font_dir))
    css = font_css + PDF_CSS % {"font": family}
    size = ctx.opt("page_size", "letter")
    page = pymupdf.paper_rect(size)
    margin = 54  # 0.75in
    where = page + (margin, margin, -margin, -margin)
    story = pymupdf.Story(html=html, user_css=css, archive=arch)
    writer = pymupdf.DocumentWriter(str(dst))
    try:
        more, n = 1, 0
        while more:
            n += 1
            ctx.progress(min(0.95, 0.1 + n * 0.05), f"Laying out page {n}")  # raises on cancel
            dev = writer.begin_page(page)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            if n > 20000:
                raise ConversionError("This document is too long to lay out as a PDF (over 20,000 pages).")
    finally:
        writer.close()  # release the file handle even when cancelled


def doc_to_pdf(src: Path, dst: Path, ctx: Ctx):
    """Word/ODT/RTF/Markdown/EPUB -> PDF without needing Office (pandoc -> HTML -> layout)."""
    work = ctx.tmpdir / "pdfwork"
    work.mkdir(exist_ok=True)
    frag = work / "doc.html"
    ctx.progress(0.05, "Reading document")
    # --standalone keeps the document title (Word's "Title" style becomes metadata otherwise)
    pandoc(src.resolve(), frag, ctx, PANDOC_IN[ctx.src_fmt], "html5",
           ["--standalone", "--extract-media=media", "--wrap=none", "-M", f"pagetitle={src.stem}"], cwd=work)
    # pandoc writes absolute or work-relative media paths; normalise to relative
    html = frag.read_text(encoding="utf-8").replace(str(work).replace("\\", "/") + "/", "")
    render_html_pdf(html, dst, ctx, base_dir=work)


def register(reg: Registry) -> None:
    ins, outs = list(PANDOC_IN), list(PANDOC_OUT)
    reg.add(ins, outs, doc_to_doc, label="Converting document", engine="pandoc")
    reg.add("txt", "html", txt_to_html, cost=0.5, label="Reading text")
    reg.add("html", "pdf", html_to_pdf, cost=1.0, label="Laying out PDF")
    reg.add(["docx", "odt", "rtf", "md", "epub"], "pdf", doc_to_pdf, cost=1.4, label="Laying out PDF")
