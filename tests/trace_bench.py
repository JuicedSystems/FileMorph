"""TRACE quality benchmark: how close, how smooth and how sharp are the traced lines?

Draws scenes whose exact geometry is known, turns them into the kind of picture a user drops
on FileMorph (small web logo, large export, JPEG, scan), runs TRACE and compares the SVG with
the true shapes.  All distances are in pixels of the picture that was traced.

    edge   mean distance between the traced outline and the true outline   (lower = more faithful)
    p95    95th percentile of that distance                                 (worst spots)
    wobble ripple along the outline that the true shape doesn't have        (lower = smoother)
    corner how far sharp corners were rounded off                           (lower = crisper)
    nodes  curve/line segments in the SVG                                   (lower = cleaner to edit/cut)

Usage:
    python tests/trace_bench.py                 # all scenes, all details
    python tests/trace_bench.py --detail balanced --sheet tests/_out_trace
    python tests/trace_bench.py --json before.json     # save numbers, compare later with --against
"""
from __future__ import annotations

import argparse
import json
import os
import math
import re
import sys
import tempfile
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# FILEMORPH_ROOT=<another checkout> measures that checkout's tracer with this benchmark
sys.path.insert(0, os.environ.get("FILEMORPH_ROOT") or str(ROOT))
warnings.filterwarnings("ignore")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

W, H = 480, 320          # scene size in scene units
TRUTH = 12               # truth pixels per scene unit at variant scale 1 (kept >= 6 per traced px)
FONT = ROOT / "assets" / "fonts" / "Geist-Bold.ttf"


# ------------------------------------------------------------------ scenes (exact geometry)
def _star(cx, cy, r1, r2, n=5, rot=-90.0):
    pts = []
    for i in range(n * 2):
        r = r1 if i % 2 == 0 else r2
        a = math.radians(rot + i * 180.0 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _rot_rect(cx, cy, w, h, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in
            ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]


def scene_rings(page):
    """Circles: the classic 'is it actually round and smooth' test."""
    sh = page.new_shape()
    sh.draw_circle((90, 100), 62); sh.finish(color=(0, 0, 0), width=9, fill=None)
    sh.draw_circle((240, 100), 62); sh.finish(color=(0, 0, 0), width=2.2, fill=None)
    sh.draw_circle((390, 100), 62); sh.finish(color=None, fill=(0, 0, 0))
    sh.draw_oval(pymupdf.Rect(30, 190, 230, 300)); sh.finish(color=(0, 0, 0), width=5, fill=None)
    sh.draw_circle((300, 245), 22); sh.finish(color=(0, 0, 0), width=3, fill=None)
    sh.draw_circle((370, 245), 11); sh.finish(color=None, fill=(0, 0, 0))
    sh.draw_circle((420, 245), 5); sh.finish(color=None, fill=(0, 0, 0))
    sh.commit()
    return []


def scene_corners(page):
    """Sharp corners must stay sharp, straight edges straight."""
    sh = page.new_shape()
    corners = []
    r = pymupdf.Rect(30, 30, 170, 130)
    sh.draw_rect(r); sh.finish(color=None, fill=(0, 0, 0))
    corners += [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
    q = _rot_rect(260, 85, 110, 80, 17)
    sh.draw_polyline(q + [q[0]]); sh.finish(color=None, fill=(0, 0, 0), closePath=True)
    corners += q
    st = _star(400, 85, 62, 25)
    sh.draw_polyline(st + [st[0]]); sh.finish(color=None, fill=(0, 0, 0), closePath=True)
    corners += st
    tri = [(40, 290), (150, 290), (70, 175)]
    sh.draw_polyline(tri + [tri[0]]); sh.finish(color=None, fill=(0, 0, 0), closePath=True)
    corners += tri
    # outlined box (stroke with mitred corners): outer and inner corners
    sh.draw_rect(pymupdf.Rect(200, 190, 330, 290)); sh.finish(color=(0, 0, 0), width=8, fill=None, lineJoin=0)
    corners += [(196, 186), (334, 186), (334, 294), (196, 294), (204, 194), (326, 194), (326, 286), (204, 286)]
    # rounded rectangle: corners here are true curves and must NOT become sharp
    rr = pymupdf.Rect(360, 190, 455, 290)
    sh.draw_rect(rr, radius=0.22); sh.finish(color=None, fill=(0, 0, 0))
    sh.commit()
    return corners


def scene_lines(page):
    """Straight strokes at awkward angles: shallow slopes are where pixel stair-steps show."""
    sh = page.new_shape()
    y = 30
    for deg, wd in ((1.5, 1.2), (3, 2), (7, 3), (13, 5), (-4, 1.6), (-9, 2.5)):
        a = math.radians(deg)
        x0, x1 = 30, 300
        sh.draw_line((x0, y), (x1, y + (x1 - x0) * math.tan(a)))
        sh.finish(color=(0, 0, 0), width=wd, lineCap=0)
        y += 46 if deg > 0 else 30
    for i, (deg, wd) in enumerate(((45, 2), (60, 3), (83, 1.5), (88, 4), (97, 2.5))):
        a = math.radians(deg)
        x = 330 + i * 30
        sh.draw_line((x, 290), (x + 250 * math.cos(a), 290 - 250 * math.sin(a)))
        sh.finish(color=(0, 0, 0), width=wd, lineCap=0)
    sh.commit()
    return []


def scene_curves(page):
    """Flowing strokes: signatures, hand lettering, swooshes."""
    sh = page.new_shape()
    sh.draw_bezier((20, 90), (110, -40), (150, 220), (250, 70))
    sh.draw_bezier((250, 70), (320, -30), (360, 170), (460, 40))
    sh.finish(color=(0, 0, 0), width=4, closePath=False, lineCap=1, lineJoin=1)
    sh.draw_bezier((20, 190), (140, 110), (200, 300), (300, 180))
    sh.draw_bezier((300, 180), (350, 120), (420, 140), (460, 210))
    sh.finish(color=(0, 0, 0), width=1.8, closePath=False, lineCap=1, lineJoin=1)
    # a swoosh that tapers to points (filled, not stroked)
    sh.draw_bezier((30, 300), (150, 215), (310, 215), (450, 262))
    sh.draw_bezier((450, 262), (310, 240), (150, 250), (30, 300))
    sh.finish(color=None, fill=(0, 0, 0), closePath=True)
    sh.draw_sector((400, 120), (440, 120), 250, fullSector=False)
    sh.finish(color=(0, 0, 0), width=2.5, closePath=False, lineCap=1)
    sh.commit()
    return []


def scene_text(page):
    """Lettering, big to small: stems, bowls, counters and thin joins."""
    y = 78
    for size in (72, 40, 24, 14, 9):
        page.insert_text((22, y), "FileMorph & Rg8a" if size < 60 else "Morph", fontsize=size,
                         fontname="gb", fontfile=str(FONT), color=(0, 0, 0))
        y += size * 0.62 + 30
    page.insert_text((250, 78), "Sag", fontsize=72, fontname="gb", fontfile=str(FONT), color=(0, 0, 0))
    return []


SCENES = {"rings": scene_rings, "corners": scene_corners, "lines": scene_lines,
          "curves": scene_curves, "text": scene_text}

# name: (traced-picture pixels per scene unit, degrade)
VARIANTS = {
    "small": (1.0, None),      # 480 px logo off a website
    "large": (3.5, None),      # 1680 px clean export
    "jpeg": (1.5, "jpeg"),     # 720 px, saved as a low-quality JPEG
    "scan": (2.5, "scan"),     # 1200 px scan: soft, grey paper, grain
}


def build(scene: str, variant: str, seed: int = 7):
    """-> (input picture as PIL L, truth mask uint8 1=ink at TRUTH px/unit, corners in truth px, px/unit)."""
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    corners = SCENES[scene](page)
    k, degrade = VARIANTS[variant]
    s = max(TRUTH, int(math.ceil(k * 6)))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(s, s), colorspace=pymupdf.csGRAY, alpha=False)
    hi = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    doc.close()
    truth = (hi < 128).astype(np.uint8)
    iw, ih = round(W * k), round(H * k)
    img = cv2.resize(hi, (iw, ih), interpolation=cv2.INTER_AREA)
    rng = np.random.default_rng(seed)
    if degrade == "jpeg":
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 45])
        img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    elif degrade == "scan":
        f = img.astype(np.float32) / 255.0
        f = 45 + f * (232 - 45)                           # ink isn't black, paper isn't white
        f = cv2.GaussianBlur(f, (0, 0), 0.9)              # scanner softness
        yy = np.linspace(-6, 5, ih, dtype=np.float32)[:, None]
        f = f + yy                                         # uneven lighting
        f = f + rng.normal(0, 5.0, f.shape).astype(np.float32)
        img = np.clip(f, 0, 255).astype(np.uint8)
    return Image.fromarray(img), truth, [(x * s, y * s) for x, y in corners], k, s


# ------------------------------------------------------------------ measuring
def render_svg(svg: Path, size: tuple[int, int]):
    """Rendered SVG as an ink mask (1 = ink) of exactly `size` (w, h)."""
    w, h = size
    with pymupdf.open(svg) as doc:
        page = doc[0]
        zx, zy = w / page.rect.width, h / page.rect.height
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zx, zy), colorspace=pymupdf.csGRAY, alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    if a.shape != (h, w):
        a = cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR)
    return (a < 128).astype(np.uint8)


def _edge(mask):
    """Boundary pixels of a mask (ink pixels touching paper)."""
    er = cv2.erode(mask, np.ones((3, 3), np.uint8))
    return (mask == 1) & (er == 0)


def _signed_distance(mask):
    """Signed distance to the mask's outline, in px: negative inside ink, positive outside.

    Reads 0 on the mask's own edge pixels (see _edge), so a tracing identical to the truth scores
    exactly 0.
    """
    outside = cv2.distanceTransform((1 - mask).astype(np.uint8), cv2.DIST_L2, 5)
    inside = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    return np.where(mask == 1, 1.0 - inside, outside)


def measure(svg: Path, truth, corners, px_per_truth: float) -> dict:
    """Compare a traced SVG with the truth mask. `px_per_truth` = traced-picture px per truth px."""
    got = render_svg(svg, (truth.shape[1], truth.shape[0]))
    te, ge = _edge(truth), _edge(got)
    sd_t = _signed_distance(truth)
    d_tg = np.abs(sd_t[ge])                                   # traced outline -> truth
    sd_g = _signed_distance(got)
    d_gt = np.abs(sd_g[te])                                   # truth outline -> traced (catches lost shapes)
    both = np.concatenate([d_tg, d_gt]) if len(d_tg) else d_gt
    inter = int((truth & got).sum())
    union = int((truth | got).sum())

    # wobble: follow each traced outline, read its signed offset from the true outline, and keep
    # only the fast ripple (offset minus its own running average over ~14 traced px)
    contours, _ = cv2.findContours(got, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    win = max(5, int(round(14 / px_per_truth)) | 1)
    rip = []
    for c in contours:
        if len(c) < win * 3:
            continue
        p = c.reshape(-1, 2)
        d = sd_t[p[:, 1], p[:, 0]]
        ok = np.abs(d) < 3 / px_per_truth                     # ignore spots that are simply wrong
        d = np.clip(d, -3 / px_per_truth, 3 / px_per_truth)
        ext = np.concatenate([d[-win:], d, d[:win]])
        avg = np.convolve(ext, np.ones(win) / win, mode="same")[win:-win]
        r = (d - avg)[ok]
        if len(r):
            rip.append(r)
    wobble = float(np.sqrt(np.mean(np.concatenate(rip) ** 2))) * px_per_truth if rip else float("nan")

    corner = float("nan")
    if corners:
        gy, gx = np.nonzero(ge)
        pts = np.stack([gx, gy], 1).astype(np.float32)
        ds = []
        for cx, cy in corners:
            ds.append(float(np.sqrt(((pts - (cx, cy)) ** 2).sum(1)).min()) if len(pts) else 99.0)
        corner = float(np.mean(ds)) * px_per_truth

    text = svg.read_text(encoding="utf-8")
    nodes = sum(len(re.findall(r"[CLQSTHVAclqsthva]", d)) for d in re.findall(r'\bd="([^"]+)"', text))
    return {
        "bias": float(sd_t[ge].mean()) * px_per_truth if ge.any() else 0.0,   # + = strokes came out fatter
        "edge": float(both.mean()) * px_per_truth,
        "p95": float(np.percentile(both, 95)) * px_per_truth,
        "max": float(both.max()) * px_per_truth,
        "wobble": wobble,
        "corner": corner,
        "iou": inter / union if union else 1.0,
        "nodes": nodes,
        "bytes": len(text.encode("utf-8")),
    }


# ------------------------------------------------------------------ running TRACE
def run_trace(im, dst: Path, detail: str, tmp: Path, options: dict | None = None) -> None:
    from filemorph.core.converters.trace_bw import trace_image
    from filemorph.core.registry import Ctx
    opts = {"trace_detail": detail}
    opts.update(options or {})
    ctx = Ctx("png", "trace", tmp, opts)
    trace_image(im, dst, ctx)


def engine() -> str:
    """Which tracer drew the last picture (older checkouts report it in a different place)."""
    from filemorph.core.converters import trace_bw, tracing
    return getattr(trace_bw, "LAST_ENGINE", tracing.LAST_TRACER)["name"]


def sheet(im, svg: Path, truth, out: Path, title: str) -> None:
    """Side-by-side crops (source | traced, magnified, with the true outline in red) for eyeballing."""
    th, tw = truth.shape
    got = render_svg(svg, (tw, th))
    src = np.asarray(im.convert("L").resize((tw, th), Image.NEAREST))
    te = cv2.dilate(_edge(truth).astype(np.uint8), np.ones((2, 2), np.uint8)) > 0
    left = cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
    right = cv2.cvtColor(((1 - got) * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    right[te] = (0, 0, 255)
    both = np.hstack([left, np.full((th, 12, 3), 255, np.uint8), right])
    scale = min(1.0, 3600 / both.shape[1])
    if scale < 1:
        both = cv2.resize(both, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.putText(both, title, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 80, 0), 2)
    cv2.imwrite(str(out), both)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", default="bold,balanced,fine")
    ap.add_argument("--scene", default=",".join(SCENES))
    ap.add_argument("--variant", default=",".join(VARIANTS))
    ap.add_argument("--sheet", help="folder for magnified source-vs-traced pictures and the SVGs")
    ap.add_argument("--json", help="write all numbers here")
    ap.add_argument("--against", help="earlier --json file to compare with")
    ap.add_argument("--opt", action="append", default=[], help="extra conversion option, key=value")
    a = ap.parse_args()
    options = dict(o.split("=", 1) for o in a.opt)
    out_dir = Path(a.sheet).resolve() if a.sheet else None  # absolute: the tracer child runs elsewhere
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    prev = json.loads(Path(a.against).read_text()) if a.against else {}
    rows = {}
    engines: set[str] = set()
    keys =("edge", "p95", "wobble", "corner", "nodes")
    print(f"{'detail':9}{'scene':9}{'variant':7}" + "".join(f"{k:>9}" for k in keys) + f"{'sec':>7}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for detail in a.detail.split(","):
            for scene in a.scene.split(","):
                for variant in a.variant.split(","):
                    im, truth, corners, k, s = build(scene, variant)
                    dst = (out_dir or tmp) / f"{scene}-{variant}-{detail}.svg"
                    t0 = time.perf_counter()
                    try:
                        run_trace(im, dst, detail, tmp, options)
                    except Exception as e:  # a scene that fails to trace is a result too
                        print(f"{detail:9}{scene:9}{variant:7}  FAILED: {e}")
                        continue
                    sec = time.perf_counter() - t0
                    m = measure(dst, truth, corners, k / s)
                    m["sec"] = sec
                    m["tracer"] = engine()
                    engines.add(m["tracer"])
                    name = f"{detail}/{scene}/{variant}"
                    rows[name] = m
                    line = f"{detail:9}{scene:9}{variant:7}"
                    for key in keys:
                        v = m[key]
                        line += f"{v:9.0f}" if key == "nodes" else (f"{'-':>9}" if v != v else f"{v:9.3f}")
                    print(line + f"{sec:7.2f}", flush=True)
                    if out_dir:
                        sheet(im, dst, truth, out_dir / f"{scene}-{variant}-{detail}.png",
                              f"{scene} / {variant} / {detail}")

    def avg(sel, key, table):
        v = [r[key] for n, r in table.items() if sel(n) and r[key] == r[key]]
        return sum(v) / len(v) if v else float("nan")

    print(f"\nTraced by: {', '.join(sorted(engines)) or '-'}")
    print("Averages" + (" (earlier run in brackets)" if prev else ""))
    for detail in a.detail.split(","):
        sel = lambda n, d=detail: n.startswith(d + "/")  # noqa: E731
        line = f"  {detail:9}"
        for key in keys + ("bias", "sec"):
            v = avg(sel, key, rows)
            line += f" {key} {v:.3f}" if key != "nodes" else f" {key} {v:.0f}"
            if prev:
                p = avg(lambda n: sel(n) and n in rows, key, prev)
                line += f" [{p:.3f}]" if key != "nodes" else f" [{p:.0f}]"
        print(line)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
