"""Bitmap -> vector SVG tracing, crash-proofed.

Primary tracer: vtracer (Rust, best quality), run in a *separate process* so a native crash
in the library can never take FileMorph down with it. If that process fails for any reason,
we fall back to an OpenCV tracer (OpenCV ships with the app already, via pdf2docx).
Both produce real vector shapes, never a bitmap wrapped in an SVG.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .. import proc
from ..registry import ConversionError, Ctx

PRESETS = {
    "simple": dict(filter_speckle=10, color_precision=5, layer_difference=32, corner_threshold=60),
    "balanced": dict(filter_speckle=4, color_precision=6, layer_difference=16, corner_threshold=60),
    "detailed": dict(filter_speckle=2, color_precision=8, layer_difference=8, corner_threshold=45),
}
# Black & white line tracing (TRACE): shapes only, no colour layers
BW_PRESETS = {
    "bw-bold": dict(filter_speckle=12, corner_threshold=75, length_threshold=6.0, splice_threshold=45, path_precision=2),
    "bw-balanced": dict(filter_speckle=6, corner_threshold=60, length_threshold=4.0, splice_threshold=45, path_precision=2),
    "bw-fine": dict(filter_speckle=2, corner_threshold=45, length_threshold=3.0, splice_threshold=45, path_precision=3),
}
LAST_TRACER = {"name": ""}  # which engine traced the last image (reported by --selftest)


# ------------------------------------------------------------------ child-process entry
def trace_child_main(src: str, dst: str, detail: str) -> int:
    """Runs inside `FileMorph.exe --trace src dst detail`. Exit 0 only if dst was written."""
    if sys.platform == "win32":  # a native crash here must not pop a Windows Error Reporting dialog
        try:
            import ctypes
            ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)  # FAILCRITICAL|NOGPFAULT|NOOPENFILE
        except Exception:
            pass
    if os.environ.get("FILEMORPH_TRACE_CRASH"):  # test hook: simulate a native crash
        os.abort()
    import vtracer
    if detail in BW_PRESETS:
        vtracer.convert_image_to_svg_py(src, dst, colormode="binary", mode="spline", **BW_PRESETS[detail])
    else:
        vtracer.convert_image_to_svg_py(src, dst, colormode="color", hierarchical="stacked", mode="spline",
                                        **PRESETS.get(detail, PRESETS["balanced"]))
    return 0 if Path(dst).exists() and Path(dst).stat().st_size > 0 else 1


def _trace_vtracer_isolated(png: Path, dst: Path, detail: str, ctx: Ctx) -> bool:
    base, env = proc.child_cmd(), proc.child_env()
    try:
        p = proc.popen(base + ["--trace", str(png), str(dst), detail], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=env, cwd=str(png.parent))
    except OSError:
        return False
    start = time.monotonic()
    try:
        while True:
            try:
                code = p.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if (ctx.cancel_event is not None and ctx.cancel_event.is_set()) or time.monotonic() - start > 180:
                    proc.kill_tree(p)
                    ctx.check_cancel()
                    return False
    finally:
        proc._forget(p)
    return code == 0 and dst.exists() and dst.stat().st_size > 0


# ------------------------------------------------------------------ OpenCV fallback
def trace_opencv(png: Path, dst: Path, detail: str) -> None:
    """Colour-quantise, then trace each colour's regions (with holes) into SVG paths."""
    import numpy as np
    import cv2
    from PIL import Image

    im = Image.open(png).convert("RGBA")
    w, h = im.size
    colors = {"simple": 8, "balanced": 16, "detailed": 32}.get(detail, 16)
    eps = {"simple": 1.6, "balanced": 1.0, "detailed": 0.6}.get(detail, 1.0)
    min_area = {"simple": 24, "balanced": 8, "detailed": 3}.get(detail, 8)

    alpha = np.array(im.getchannel("A"))
    rgb = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im).convert("RGB")
    q = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    idx = np.array(q)
    pal = q.getpalette()[: colors * 3]
    opaque = alpha > 16

    # paint larger areas first so small details stay on top
    order = sorted(np.unique(idx[opaque]), key=lambda c: -int((idx[opaque] == c).sum()))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    for c in order:
        mask = ((idx == c) & opaque).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) if detail == "simple" else mask
        contours, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        d = []
        for cnt in contours:
            if abs(cv2.contourArea(cnt)) < min_area:
                continue
            ap = cv2.approxPolyDP(cnt, eps, True).reshape(-1, 2)
            if len(ap) < 3:
                continue
            d.append("M" + "L".join(f"{x},{y}" for x, y in ap) + "Z")
        if d:
            r, g, b = pal[c * 3: c * 3 + 3]
            parts.append(f'<path fill="#{r:02x}{g:02x}{b:02x}" fill-rule="evenodd" d="{"".join(d)}"/>')
    parts.append("</svg>")
    dst.write_text("\n".join(parts), encoding="utf-8")


# ------------------------------------------------------------------ quality guard
def render_error(svg: Path, png: Path, size: int = 160) -> float:
    """Mean per-channel difference (0-255) between the rendered SVG and the source, over visible pixels."""
    import numpy as np
    import pymupdf
    from PIL import Image
    src = Image.open(png).convert("RGBA")
    src.thumbnail((size, size))
    w, h = src.size
    with pymupdf.open(svg) as doc:  # closed promptly: the temp folder is deleted right after
        page = doc[0]
        zoom = min(w / max(page.rect.width, 1), h / max(page.rect.height, 1))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    out = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).resize((w, h))
    white = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    ref = Image.alpha_composite(white, src).convert("RGB")
    a = np.asarray(ref, dtype=np.int16)
    b = np.asarray(out, dtype=np.int16)
    vis = np.asarray(src.getchannel("A")) > 16
    if not vis.any():
        return 0.0
    return float(np.abs(a - b)[vis].mean())


GOOD_ENOUGH = 18.0  # mean error below this: vtracer's smooth curves win, no need to compare


# ------------------------------------------------------------------ public
def trace(png: Path, dst: Path, detail: str, ctx: Ctx) -> None:
    """vtracer (isolated) first; if it crashed or is visibly off (e.g. it flattens photographic
    gradients), trace with OpenCV too and keep whichever looks closer to the original."""
    ctx.progress(0.2, "Tracing shapes")
    vt_err = None
    if not os.environ.get("FILEMORPH_NO_VTRACER") and _trace_vtracer_isolated(png, dst, detail, ctx):
        try:
            vt_err = render_error(dst, png)
        except Exception:
            vt_err = 0.0  # can't measure: trust vtracer
        if vt_err <= GOOD_ENOUGH:
            LAST_TRACER["name"] = "vtracer"
            return
    ctx.progress(0.55, "Tracing shapes")
    alt = dst.with_name(dst.stem + ".cv.svg")
    try:
        trace_opencv(png, alt, detail)
        cv_err = render_error(alt, png)
    except Exception as e:
        alt.unlink(missing_ok=True)
        if vt_err is not None:  # vtracer output exists; keep it
            LAST_TRACER["name"] = "vtracer"
            return
        raise ConversionError("This image couldn't be traced into a vector SVG.") from e
    if vt_err is None or cv_err < vt_err:
        alt.replace(dst)
        # "opencv (fallback)" = vtracer failed; plain "opencv" = it simply matched this image better
        LAST_TRACER["name"] = "opencv" if vt_err is not None else "opencv (fallback)"
    else:
        alt.unlink(missing_ok=True)
        LAST_TRACER["name"] = "vtracer"
