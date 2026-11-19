"""TRACE: any image or PDF -> clean black & white vector SVG.

White (the paper) is dropped, so the SVG is just the black shapes on a transparent background:
ready for vinyl cutters, laser engraving, stencils, logos and print.

Pipeline:
  1. flatten transparency onto white, greyscale, decide what kind of picture it is
  2. bring it to a working size (small pictures are enlarged so there are enough points along
     every curve; huge ones are capped)
  3. build the "ink field": a soft grey map that is negative where there is ink, positive on paper
       line art / logos / scans -> distance from one global cut-off, light-on-dark designs flipped
       photos                   -> distance from a local cut-off that keeps edges and shading
  4. remove specks, then trace every ink outline at sub-pixel precision and fit it with straight
     lines and smooth curves (trace_fit.py)
  5. write the SVG in the original picture's own units
"""
from __future__ import annotations

from pathlib import Path

from ..registry import Cancelled, ConversionError, Ctx, Registry
from .images import RASTER_IN, open_image

DETAILS = ("bold", "balanced", "fine")
_MIN_BLOB = {"bold": 90, "balanced": 24, "fine": 6}   # specks removed, in px at ~1600 px working size
_SOFTEN = {"bold": 0.9, "balanced": 0.55, "fine": 0.35}  # grain removed before the cut-off (source px)
_EPS = {"bold": 1.8, "balanced": 1.1, "fine": 0.6}     # polygon fallback smoothing
# how the last picture was traced ("subpixel" or "polygon (fallback)"), and why it fell back
LAST_ENGINE = {"name": "", "error": ""}


def _gray(im):
    """PIL image (any mode) -> uint8 greyscale array, transparency flattened onto white."""
    import numpy as np
    from PIL import Image
    if im.mode == "P":
        im = im.convert("RGBA")
    if im.mode in ("RGBA", "LA", "PA"):
        rgba = im.convert("RGBA")
        im = Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba)
    return np.asarray(im.convert("L"), dtype=np.uint8)


def _is_photo(g) -> bool:
    """Lots of mid-greys = a photo; line art, logos and scans are nearly all ink or paper."""
    import cv2
    import numpy as np
    side = max(g.shape)
    if side > 1600:  # judged at a modest size: enough to tell, and independent of megapixels
        k = 1600 / side
        g = cv2.resize(g, (max(1, round(g.shape[1] * k)), max(1, round(g.shape[0] * k))),
                       interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(g, (5, 5), 0)
    return float(np.mean((small > 60) & (small < 195))) > 0.22


def _working(g, photo: bool):
    """Scale to a size where tracing gives smooth curves without taking long. -> (array, factor)"""
    import cv2
    h, w = g.shape
    side = max(w, h)
    if photo:   # photos are drawn from local contrast; their look depends on this size, so it stays put
        target = side
        if side < 1200:
            target = 1200 if side >= 300 else side * 4
        elif side > 2600:
            target = 2600
    else:       # line art: several working pixels per source pixel until the picture is big anyway
        target = min(max(side, min(side * 4, 2400)), 3600)
    if target == side:
        return g, 1.0
    k = target / side
    size = (max(1, round(w * k)), max(1, round(h * k)))
    return cv2.resize(g, size, interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA), k


def ink_field(g, photo: bool, detail: str = "balanced", darkness: int = 0, factor: float = 1.0):
    """Working greyscale -> (float32 field, ink-to-paper contrast or None).

    The field is negative on ink, positive on paper and 0 exactly on the edge.
    """
    import cv2
    import numpy as np
    side = max(g.shape)
    if not photo:
        # line art, logos, text, scans: one clean cut-off, half-way between the ink and the paper
        sigma = max(0.6, _SOFTEN[detail] * max(factor, 1.0))
        b = cv2.GaussianBlur(g.astype(np.float32), (0, 0), sigma)
        b8 = np.clip(b + 0.5, 0, 255).astype(np.uint8)
        t, _ = cv2.threshold(b8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        dark, light = b8[b8 <= t], b8[b8 > t]
        contrast = None
        if len(dark) and len(light):
            # Otsu only splits the two groups; the true edge is midway between solid ink and bare
            # paper.  The quartiles (not the middles) stand for those: in a drawing made of thin
            # lines most "ink" pixels are half-covered edge pixels, and treating them as the ink
            # level would move the cut-off towards the paper and fatten every stroke.
            lo, hi = float(np.percentile(dark, 25)), float(np.percentile(light, 75))
            t, contrast = 0.5 * (lo + hi), hi - lo
        t = max(1.0, min(254.0, float(t) + darkness))
        field = b - t
        if np.mean(field < 0) > 0.55:  # mostly "ink": a light design on a dark background
            field = -field
        return field, contrast
    # photos: local cut-off -> drawn-looking lines that follow edges and shading
    d = {"bold": 13, "balanced": 9, "fine": 7}[detail]
    b = cv2.bilateralFilter(g, d, 60, 60).astype(np.float32)
    block = max(11, (side // 60) | 1)
    c = {"bold": 9, "balanced": 7, "fine": 5}[detail] - darkness / 5
    local = cv2.blur(b, (block, block), borderType=cv2.BORDER_REPLICATE)
    field = b - (local - c)
    # keep big dark areas solid instead of hollow outlines
    field = np.minimum(field, b - (45.0 + darkness))
    # Where shading is flat this field hovers around zero and its edge meanders with the grain;
    # a light blur settles it, so the lines come out drawn rather than ragged.
    return cv2.GaussianBlur(field, (0, 0), 0.9), None


def clean_mask(field, detail: str = "balanced", contrast: float | None = None):
    """Ink mask (uint8, 255 = ink) from the field, without specks or pinholes.

    Small is not the same as unwanted: the dot on an "i", a full stop and the hole in a small "e"
    are tiny but as black (or as white) as everything else, while dust and grain are tiny *and*
    faint.  So when the ink-to-paper contrast is known, a small blob that reaches nearly full
    ink is kept unless it is really minute, and likewise for small holes that reach bare paper.
    """
    import cv2
    import numpy as np
    side = max(field.shape)
    ink = (field < 0).astype(np.uint8)
    min_blob = max(2, int(_MIN_BLOB[detail] * (side / 1600) ** 2))

    def unwanted(labels, stats, limit, solid):
        area = stats[:, cv2.CC_STAT_AREA]
        drop = area < limit
        if solid is not None:
            keep = np.zeros(len(area), bool)
            keep[np.unique(labels[solid])] = True
            drop &= ~(keep & (area >= max(2, limit // 4)))
        drop[0] = False                      # label 0 is "everything else", never a blob
        return np.nonzero(drop)[0]

    solid_ink = solid_paper = None
    if contrast:
        solid_ink, solid_paper = field < -0.25 * contrast, field > 0.25 * contrast
    _n, labels, stats, _c = cv2.connectedComponentsWithStats(ink, 8)
    ids = unwanted(labels, stats, min_blob, solid_ink)
    if len(ids):
        ink[np.isin(labels, ids)] = 0
    # same for small paper holes inside ink (stops "salt" in solid areas)
    _n, labels, stats, _c = cv2.connectedComponentsWithStats(1 - ink, 4)
    ids = unwanted(labels, stats, max(2, min_blob // 2), solid_paper)
    if len(ids):
        ink[np.isin(labels, ids)] = 1
    return ink * 255


def to_black_white(im, detail: str = "balanced", darkness: int = 0):
    """PIL image -> numpy uint8 array, 0 = ink, 255 = paper (plus the kind of picture it was)."""
    g = _gray(im)
    photo = _is_photo(g)
    field, contrast = ink_field(g, photo, detail, darkness)
    mask = clean_mask(field, detail, contrast)
    return 255 - mask, ("photo" if photo else "line art")


def _polygon_paths(mask, detail: str, scale: tuple[float, float]) -> list[str]:
    """Fallback tracer: ink outlines with holes, as straight-segment paths."""
    import cv2
    sx, sy = scale
    contours, _hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    parts = []
    for cnt in contours:
        if cv2.contourArea(cnt) < 2:
            continue
        a = cv2.approxPolyDP(cnt, _EPS[detail], True).reshape(-1, 2)
        if len(a) < 3:
            continue
        parts.append("M" + "L".join(f"{(x + 0.5) * sx:.2f} {(y + 0.5) * sy:.2f}" for x, y in a) + "Z")
    return ["".join(parts)] if parts else []


def trace_image(im, dst: Path, ctx: Ctx, out_size: tuple[int, int] | None = None) -> None:
    from . import trace_fit
    detail = ctx.opt("trace_detail", "balanced")
    detail = detail if detail in DETAILS else "balanced"
    try:
        darkness = int(ctx.opt("trace_darkness", 0))
    except (TypeError, ValueError):
        darkness = 0
    ow, oh = out_size or im.size
    ctx.progress(0.15, "Cleaning up the picture")
    g = _gray(im)
    photo = _is_photo(g)
    work, factor = _working(g, photo)
    field, contrast = ink_field(work, photo, detail, darkness, factor)
    mask = clean_mask(field, detail, contrast)
    ctx.check_cancel()
    ctx.progress(0.4, "Tracing clean lines")
    wh, ww = work.shape
    scale = (ow / ww, oh / wh)   # the SVG is written in the original picture's units
    try:
        paths = trace_fit.trace_paths(field, mask, detail, scale, unit=factor, contrast=contrast, loose=photo,
                                      tick=lambda f: ctx.progress(0.4 + 0.55 * f, "Tracing clean lines"))
        LAST_ENGINE.update(name="subpixel", error="")
    except Cancelled:
        raise
    except Exception:  # never fail a conversion over a fitting bug: plain outlines still work
        import traceback
        LAST_ENGINE.update(name="polygon (fallback)", error=traceback.format_exc(limit=8))
        paths = _polygon_paths(mask, detail, scale)
    if not paths:
        raise ConversionError("Nothing to trace: the picture came out completely white. "
                              "Try Darkness: Darker.")
    body = "\n".join(f'<path fill="#000000" fill-rule="evenodd" d="{d}"/>' for d in paths)
    dst.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{ow}" height="{oh}" '
                   f'viewBox="0 0 {ow} {oh}">\n{body}\n</svg>\n', encoding="utf-8")


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
