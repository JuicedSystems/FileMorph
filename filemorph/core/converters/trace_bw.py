"""TRACE: any image or PDF -> clean black & white vector SVG.

White (the paper) is dropped, so the SVG is just the black shapes on a transparent background:
ready for vinyl cutters, laser engraving, stencils, logos and print.

Pipeline:
  1. flatten transparency onto white, greyscale, bring to a working size (small images are
     upscaled so curves come out smooth; huge ones are capped)
  2. decide what kind of picture it is:
       line art / logos / scans -> one global cut-off (Otsu), light-on-dark designs are flipped
       photos                   -> a local cut-off that keeps edges and shading as clean lines
  3. remove specks, then trace the black areas into smooth curves (vtracer "binary" mode, in a
     separate process; OpenCV contours if that fails)
  4. size the SVG to the original image and keep only black paths
"""
from __future__ import annotations

import re
from pathlib import Path

from ..registry import ConversionError, Ctx, Registry
from .images import RASTER_IN, open_image

DETAILS = ("bold", "balanced", "fine")
_MIN_BLOB = {"bold": 90, "balanced": 24, "fine": 6}   # specks removed, in px at ~1600 px working size
_EPS = {"bold": 1.8, "balanced": 1.1, "fine": 0.6}     # OpenCV fallback smoothing


def _working(gray, ctx: Ctx):
    """Scale to a size where tracing gives smooth curves without taking long."""
    from PIL import Image
    w, h = gray.size
    side = max(w, h)
    target = side
    if side < 1200:
        target = 1200 if side >= 300 else side * 4
    elif side > 2600:
        target = 2600
    if target != side:
        k = target / side
        gray = gray.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    return gray


def to_black_white(im, detail: str = "balanced", darkness: int = 0):
    """PIL image -> numpy uint8 array, 0 = ink, 255 = paper (plus the kind of picture it was)."""
    import cv2
    import numpy as np
    from PIL import Image

    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    g = np.asarray(im.convert("L"), dtype=np.uint8)
    side = max(g.shape)

    small = cv2.GaussianBlur(g, (5, 5), 0)
    mid = float(np.mean((small > 60) & (small < 195)))  # share of grey tones
    photo = mid > 0.22

    if not photo:
        # line art, logos, text, scans: one clean cut-off
        blur = 3 if detail != "bold" else 5
        b = cv2.GaussianBlur(g, (blur, blur), 0)
        t, _ = cv2.threshold(b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        t = max(1, min(254, t + darkness))
        bw = np.where(b > t, 255, 0).astype(np.uint8)
        if np.mean(bw == 0) > 0.55:  # mostly "ink": a light design on a dark background
            bw = 255 - bw
    else:
        # photos: local cut-off -> drawn-looking lines that follow edges and shading
        d = {"bold": 13, "balanced": 9, "fine": 7}[detail]
        b = cv2.bilateralFilter(g, d, 60, 60)
        block = max(11, (side // 60) | 1)
        c = {"bold": 9, "balanced": 7, "fine": 5}[detail] - darkness / 5
        bw = cv2.adaptiveThreshold(b, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, c)
        bw[b < 45 + darkness] = 0  # keep big dark areas solid instead of hollow outlines

    # tidy: close pinholes in strokes, then drop specks
    if detail != "fine":
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))  # 0 = ink: open fills tiny gaps in ink
    min_blob = max(2, int(_MIN_BLOB[detail] * (side / 1600) ** 2))
    ink = (bw == 0).astype(np.uint8)
    n, labels, stats, _c = cv2.connectedComponentsWithStats(ink, 8)
    small_ids = np.where(stats[1:, cv2.CC_STAT_AREA] < min_blob)[0] + 1
    if len(small_ids):
        bw[np.isin(labels, small_ids)] = 255
    # same for small paper holes inside ink (stops "salt" in solid areas)
    paper = (bw == 255).astype(np.uint8)
    n, labels, stats, _c = cv2.connectedComponentsWithStats(paper, 4)
    holes = np.where(stats[1:, cv2.CC_STAT_AREA] < max(2, min_blob // 2))[0] + 1
    if len(holes):
        bw[np.isin(labels, holes)] = 0
    return bw, ("photo" if photo else "line art")


def _opencv_bw(bw, dst: Path, detail: str) -> None:
    """Fallback tracer: ink outlines with holes, as straight-segment paths."""
    import cv2
    import numpy as np
    ink = (bw == 0).astype(np.uint8) * 255
    contours, hier = cv2.findContours(ink, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    parts = []
    for cnt in contours:
        if cv2.contourArea(cnt) < 2:
            continue
        a = cv2.approxPolyDP(cnt, _EPS[detail], True).reshape(-1, 2)
        if len(a) < 3:
            continue
        parts.append("M" + " L".join(f"{x} {y}" for x, y in a) + " Z")
    h, w = bw.shape
    dst.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
                   f'<path fill="#000000" fill-rule="evenodd" d="{" ".join(parts)}"/></svg>', encoding="utf-8")


def _finish_svg(svg: Path, work_size: tuple[int, int], out_size: tuple[int, int]) -> None:
    """Size the drawing like the original picture and keep only the black (ink) paths."""
    text = svg.read_text(encoding="utf-8")
    ww, wh = work_size
    ow, oh = out_size
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{ow}" height="{oh}" '
            f'viewBox="0 0 {ww} {wh}">')
    text = re.sub(r"<\?xml[^>]*>\s*", "", text)
    text = re.sub(r"<!--.*?-->\s*", "", text, flags=re.S)
    text = re.sub(r"<svg\b[^>]*>", head, text, count=1)
    # vtracer's binary mode can emit a paper-coloured background shape: drop anything not black
    text = re.sub(r'<path\b[^>]*fill="(?!#000000|#000"|black)[^"]*"[^>]*/>\s*', "", text)
    if "<path" not in text:
        raise ConversionError("Nothing to trace: the picture came out completely white. "
                              "Try Darkness: Darker.")
    svg.write_text(text, encoding="utf-8")


def trace_image(im, dst: Path, ctx: Ctx, out_size: tuple[int, int] | None = None) -> None:
    from PIL import Image
    from .tracing import LAST_TRACER, _trace_vtracer_isolated
    import os
    detail = ctx.opt("trace_detail", "balanced")
    detail = detail if detail in DETAILS else "balanced"
    try:
        darkness = int(ctx.opt("trace_darkness", 0))
    except (TypeError, ValueError):
        darkness = 0
    out_size = out_size or im.size
    ctx.progress(0.15, "Cleaning up the picture")
    work = _working(im if im.mode != "P" else im.convert("RGBA"), ctx)
    bw, _kind = to_black_white(work, detail, darkness)
    ctx.check_cancel()
    bw_png = ctx.tmpdir / f"trace_bw_{dst.stem[:40]}.png"
    Image.fromarray(bw).save(bw_png)
    ctx.progress(0.5, "Tracing clean lines")
    raw = dst.with_suffix(".raw.svg")
    ok = (not os.environ.get("FILEMORPH_NO_VTRACER")
          and _trace_vtracer_isolated(bw_png, raw, f"bw-{detail}", ctx))
    if ok:
        LAST_TRACER["name"] = "vtracer"
    else:
        ctx.check_cancel()
        _opencv_bw(bw, raw, detail)
        LAST_TRACER["name"] = "opencv (fallback)"
    _finish_svg(raw, (bw.shape[1], bw.shape[0]), out_size)
    raw.replace(dst)


def raster_to_trace(src: Path, dst: Path, ctx: Ctx):
    im = open_image(src)
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)  # animated: trace the first frame
    trace_image(im.copy(), dst, ctx)


def pdf_to_trace(src: Path, dst: Path, ctx: Ctx):
    """Each page traced on its own: 'Report - trace - page 01.svg'."""
    from PIL import Image
    from .pdf import _page_paths, open_pdf
    outs = []
    with open_pdf(src) as doc:
        n = doc.page_count
        paths = _page_paths(dst, n)
        for i, page in enumerate(doc):
            r = page.rect
            dpi = max(72, min(300, int(2000 / max(r.width, r.height) * 72)))  # ~2000 px long side
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            sub = Ctx(ctx.src_fmt, ctx.dst_fmt, ctx.tmpdir, ctx.options,
                      lambda f, m, _i=i: ctx.progress((_i + f) / n, f"Page {_i + 1} of {n}: {m}"),
                      ctx.cancel_event)
            pt_size = (round(r.width), round(r.height))  # keep the page's real size (points)
            trace_image(im, paths[i], sub, out_size=pt_size)
            outs.append(paths[i])
    return outs


def register(reg: Registry) -> None:
    reg.add(RASTER_IN, "trace", raster_to_trace, cost=1.0, label="Tracing clean lines")
    reg.add("pdf", "trace", pdf_to_trace, multi=True, cost=1.0, label="Tracing clean lines")
