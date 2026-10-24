"""SHRINK: the same file, smaller. Format and extension stay; only weight goes.

One option, shrink_strength: light | balanced | strong. If the result isn't clearly smaller the
original is already compact, and nothing is written (better than handing back a "smaller" file
that isn't).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from ..registry import ConversionError, Ctx, Registry

STRENGTHS = ("light", "balanced", "strong")
MIN_SAVING = 0.03  # under 3% smaller isn't worth a second file

PHOTO = ["jpg", "webp", "avif", "tiff"]
OFFICE = ["docx", "pptx", "xlsx"]
VIDEO = ["mp4", "mov", "mkv", "webm"]
AUDIO = ["mp3", "m4a", "ogg", "opus"]
SOURCES = ["pdf", "png", *PHOTO, *OFFICE, *VIDEO, *AUDIO]

#                   quality, longest side (None = keep)
_PHOTO = {"light": (85, None), "balanced": (75, 2560), "strong": (60, 1600)}
_PNG_SIDE = {"light": None, "balanced": 2560, "strong": 1600}
_OFFICE = {"light": (85, 2560), "balanced": (75, 1920), "strong": (60, 1280)}
_PDF = {"light": (200, 80), "balanced": (150, 70), "strong": (96, 55)}  # target dpi, JPEG quality
_VIDEO = {"light": (24, None), "balanced": (28, 1080), "strong": (32, 720)}  # CRF, max height
_AUDIO = {"light": 160, "balanced": 128, "strong": 80}  # kbps


def strength(ctx: Ctx) -> str:
    s = ctx.opt("shrink_strength", "balanced")
    return s if s in STRENGTHS else "balanced"


def human(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"  # pragma: no cover


def _check_smaller(src: Path, dst: Path) -> None:
    before, after = src.stat().st_size, dst.stat().st_size if dst.exists() else 0
    if after == 0 or after > before * (1 - MIN_SAVING):
        dst.unlink(missing_ok=True)
        raise ConversionError(f"Already as small as it gets: {src.name} can't be shrunk further"
                              + (" at this strength." if after else "."))


# ------------------------------------------------------------------ images
def _fit(im, side):
    from PIL import Image
    if side and max(im.size) > side:
        im = im.copy()
        im.thumbnail((side, side), Image.LANCZOS)
    return im


def _save_photo(im, out, fmt: str, q: int, info: dict) -> None:
    kw: dict = {}
    if info.get("icc_profile") and im.mode in ("RGB", "RGBA", "L", "LA"):
        kw["icc_profile"] = info["icc_profile"]  # colours stay right; EXIF (and its thumbnail) goes
    if fmt == "jpg":
        if im.mode not in ("RGB", "L"):
            from .images import _flatten
            im = _flatten(im)
        im.save(out, "JPEG", quality=q, optimize=True, progressive=True, subsampling=2, **kw)
    elif fmt == "webp":
        im.save(out, "WEBP", quality=q, method=6, **kw)
    elif fmt == "avif":
        im.save(out, "AVIF", quality=q, **kw)
    elif fmt == "tiff":
        if im.mode in ("RGB", "L"):
            im.save(out, "TIFF", compression="jpeg", quality=q, **kw)
        else:
            im.save(out, "TIFF", compression="tiff_adobe_deflate", **kw)
    else:
        raise AssertionError(fmt)


def shrink_photo(src: Path, dst: Path, ctx: Ctx):
    from PIL import ImageOps
    from .images import _normalise_mode, open_image
    im = open_image(src)
    info = dict(im.info)
    if getattr(im, "n_frames", 1) > 1 and ctx.src_fmt == "webp":
        raise ConversionError("Animated images can't be shrunk yet. Try converting it to MP4 instead.")
    q, side = _PHOTO[strength(ctx)]
    ctx.progress(0.2, "Making it smaller")
    im = _fit(_normalise_mode(ImageOps.exif_transpose(im) or im), side)
    _save_photo(im, dst, ctx.src_fmt, q, info)
    _check_smaller(src, dst)


def _png_bytes(im, palette: bool) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    if palette and im.mode not in ("P", "1", "L"):
        im = im.convert("RGBA").quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def shrink_png(src: Path, dst: Path, ctx: Ctx):
    from .images import _normalise_mode, open_image
    im = open_image(src)
    s = strength(ctx)
    ctx.progress(0.2, "Making it smaller")
    im = _fit(_normalise_mode(im), _PNG_SIDE[s])
    data = _png_bytes(im, False)
    if s != "light":  # a 256-colour palette, when it really pays (screenshots, logos, diagrams)
        pal = _png_bytes(im, True)
        if len(pal) < len(data) * 0.7:
            data = pal
    dst.write_bytes(data)
    _check_smaller(src, dst)


# ------------------------------------------------------------------ PDF
def shrink_pdf(src: Path, dst: Path, ctx: Ctx):
    from .pdf import open_pdf
    dpi, q = _PDF[strength(ctx)]
    with open_pdf(src) as doc:
        ctx.progress(0.1, "Re-encoding pictures")
        try:
            doc.rewrite_images(dpi_threshold=dpi + dpi // 3, dpi_target=dpi, quality=q,
                               lossy=True, lossless=True, bitonal=True, color=True, gray=True)
        except Exception:
            pass  # unusual image types: still compact the rest
        ctx.progress(0.7, "Compacting")
        try:
            doc.subset_fonts()
        except Exception:
            pass
        doc.save(dst, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True,
                 use_objstms=1)
    _check_smaller(src, dst)


# ------------------------------------------------------------------ Word / PowerPoint / Excel
def shrink_office(src: Path, dst: Path, ctx: Ctx):
    """Pictures inside the document are resized and re-encoded in place (same name, same format,
    so every reference to them still works); everything else is copied as-is, recompressed."""
    from PIL import Image, ImageOps
    q, side = _OFFICE[strength(ctx)]
    try:
        zin = zipfile.ZipFile(src)
    except zipfile.BadZipFile as e:
        raise ConversionError("This file couldn't be opened — it may be damaged.") from e
    with zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
        items = zin.infolist()
        for n, it in enumerate(items):
            ctx.progress(n / max(1, len(items)), "Shrinking pictures")
            data = zin.read(it.filename)
            ext = it.filename.rsplit(".", 1)[-1].lower()
            if "/media/" in it.filename and ext in ("jpg", "jpeg", "png") and len(data) > 60_000:
                try:
                    im = Image.open(io.BytesIO(data))
                    im.load()
                    small = _fit(ImageOps.exif_transpose(im) or im, side)
                    buf = io.BytesIO()
                    if ext == "png":
                        small.save(buf, "PNG", optimize=True)
                        alt = _png_bytes(small, True)
                        out = alt if len(alt) < buf.tell() * 0.7 else buf.getvalue()
                    else:
                        if small.mode not in ("RGB", "L"):
                            small = small.convert("RGB")
                        small.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
                        out = buf.getvalue()
                    if len(out) < len(data):
                        data = out
                except Exception:
                    pass  # an image Pillow can't read stays exactly as it was
            zi = zipfile.ZipInfo(it.filename, it.date_time)
            zi.compress_type = zipfile.ZIP_STORED if it.filename == "mimetype" else zipfile.ZIP_DEFLATED
            zi.external_attr = it.external_attr
            zout.writestr(zi, data)
    _check_smaller(src, dst)


# ------------------------------------------------------------------ video & audio
def shrink_video(src: Path, dst: Path, ctx: Ctx):
    from .media import _run_ffmpeg, probe
    info = probe(src, ctx)
    if not info["video"]:
        raise ConversionError("This file has no video track.")
    crf, height = _VIDEO[strength(ctx)]
    scale = (f"scale=-2:'min({height},ih)':flags=lanczos," if height else "") + "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    if ctx.src_fmt == "webm":
        v = ["-c:v", "libvpx-vp9", "-crf", str(crf + 8), "-b:v", "0", "-row-mt", "1", "-deadline", "good",
             "-cpu-used", "4"]
        a = ["-c:a", "libopus", "-b:a", "96k"]
    else:
        v = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
        a = ["-c:a", "aac", "-b:a", "128k"]
    maps = ["-map", "0:v:0"] + (["-map", "0:a:0?", *a] if info["audio"] else ["-an"])
    extra = ["-movflags", "+faststart"] if ctx.src_fmt in ("mp4", "mov") else []
    _run_ffmpeg([*maps, "-vf", scale, "-pix_fmt", "yuv420p", *v, *extra, "-map_metadata", "0", str(dst)],
                src, ctx, info["duration"], "Shrinking video")
    _check_smaller(src, dst)


_AUDIO_CODEC = {"mp3": ["-c:a", "libmp3lame"], "m4a": ["-c:a", "aac"], "ogg": ["-c:a", "libvorbis"],
                "opus": ["-c:a", "libopus"]}


def shrink_audio(src: Path, dst: Path, ctx: Ctx):
    from .media import _run_ffmpeg, probe
    info = probe(src, ctx)
    if not info["audio"]:
        raise ConversionError("This file has no audio track.")
    kbps = _AUDIO[strength(ctx)]
    _run_ffmpeg(["-vn", "-map", "0:a:0", *_AUDIO_CODEC[ctx.src_fmt], "-b:a", f"{kbps}k", "-map_metadata", "0",
                 str(dst)], src, ctx, info["duration"], "Shrinking audio")
    _check_smaller(src, dst)


def register(reg: Registry) -> None:
    reg.add("pdf", "shrink", shrink_pdf, label="Shrinking PDF")
    reg.add("png", "shrink", shrink_png, label="Shrinking image")
    reg.add(PHOTO, "shrink", shrink_photo, label="Shrinking image")
    reg.add(OFFICE, "shrink", shrink_office, label="Shrinking pictures")
    reg.add(VIDEO, "shrink", shrink_video, label="Shrinking video", engine="ffmpeg")
    reg.add(AUDIO, "shrink", shrink_audio, label="Shrinking audio", engine="ffmpeg")

