"""Render film.html frame-by-frame with headless Chromium.

usage:
  python render.py stills <out_dir> t1 t2 ...          # PNG stills at given seconds
  python render.py frames <out.mp4> <start> <end> [fps]  # encode a time range (no audio)
"""
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = (HERE / "film.html").as_uri()


def open_page(p):
    b = p.chromium.launch(args=["--disable-gpu-vsync", "--force-color-profile=srgb", "--font-render-hinting=none"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL)
    pg.evaluate("window.ready")
    if errs:
        print("PAGE ERRORS:", *errs, sep="\n  ")
    return b, pg, errs


def stills(out, times):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b, pg, errs = open_page(p)
        for t in times:
            pg.evaluate(f"window.seek({t})")
            pg.screenshot(path=str(out / f"t{float(t):07.2f}.png"))
        if errs:
            print("ERRORS:", errs[:10])
        b.close()


def frames(out, start, end, fps=60):
    n0, n1 = round(start * fps), round(end * fps)
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(fps), out],
                          stdin=subprocess.PIPE)
    with sync_playwright() as p:
        b, pg, errs = open_page(p)
        for n in range(n0, n1):
            pg.evaluate(f"window.seek({n / fps})")
            ff.stdin.write(pg.screenshot(type="jpeg", quality=96))
            if n % 300 == 0:
                print(f"{out}: {n / fps:.1f}s", flush=True)
        b.close()
    ff.stdin.close()
    ff.wait()


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "stills":
        stills(sys.argv[2], [float(x) for x in sys.argv[3:]])
    else:
        frames(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]) if len(sys.argv) > 5 else 60)
