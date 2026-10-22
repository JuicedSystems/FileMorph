"""Image conversions: raster <-> raster, SVG in/out, image -> PDF."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, features

from ..registry import ConversionError, Ctx, Registry

try:  # HEIC/HEIF (iPhone photos)
    import pillow_heif
    pillow_heif.register_heif_opener()
    if not features.check("avif") and hasattr(pillow_heif, "register_avif_opener"):
        pillow_heif.register_avif_opener()
except Exception:  # pragma: no cover
    pillow_heif = None

Image.MAX_IMAGE_PIXELS = 300_000_000  # allow big scans, still guards against bombs

RASTER_OUT = ["png", "jpg", "webp", "gif", "tiff", "bmp", "ico", "avif"]
RASTER_IN = RASTER_OUT + ["heic"]
_NO_ALPHA = {"jpg", "bmp"}
_PIL_NAME = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF", "tiff": "TIFF",
             "bmp": "BMP", "ico": "ICO", "avif": "AVIF"}


def open_image(src: Path) -> Image.Image:
    try:
        im = Image.open(src)
        im.load()
    except Exception as e:
        raise ConversionError("This image couldn't be read — it may be damaged or in an unusual variant.") from e
    return im


def _normalise_mode(im: Image.Image) -> Image.Image:
    """Bring unusual pixel formats to 8-bit RGB/RGBA/L without wrecking the colours.
    - 16/32-bit greyscale ('I;16', 'I', 'F'): scaled down, not clipped (clipping turns it white)
    - CMYK: converted through its embedded ICC profile to sRGB when it has one"""
    mode = im.mode
    if mode.startswith("I;16") or mode in ("I", "F"):
        import numpy as np
        a = np.asarray(im, dtype=np.float64)
        top = a.max() if a.size else 0
        if top > 255:
            a = a * (255.0 / (65535.0 if top <= 65535 else top))
        return Image.fromarray(np.clip(a, 0, 255).astype("uint8"), "L")
    if mode == "CMYK":
        icc = im.info.get("icc_profile")
        if icc:
            try:
                from PIL import ImageCms
                src_prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                return ImageCms.profileToProfile(im, src_prof, ImageCms.createProfile("sRGB"), outputMode="RGB")
            except Exception:
                pass
        return im.convert("RGB")
    if mode in ("YCbCr", "LAB", "HSV"):
        return im.convert("RGB")
    return im


def _flatten(im: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    """Drop transparency onto a white background."""
    im = _normalise_mode(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.getchannel("A"))
        return base
    return im.convert("RGB")


def _prep(im: Image.Image, dst: str) -> Image.Image:
    im = ImageOps.exif_transpose(im) or im
    if dst in _NO_ALPHA:
        return _flatten(im)
    im = _normalise_mode(im)
    if im.mode == "P" and dst not in ("gif", "png", "bmp"):
        return im.convert("RGBA")
    return im


def raster_to_raster(src: Path, dst: Path, ctx: Ctx):
    target = ctx.dst_fmt
    im = open_image(src)
    q = int(ctx.opt("quality", 90))
    animated = getattr(im, "n_frames", 1) > 1 and target in ("gif", "webp")

    kw: dict = {}
    if target == "jpg":
        kw = dict(quality=q, optimize=True, progressive=True, subsampling=0 if q >= 90 else 2)
        # keep an RGB/greyscale profile; a CMYK profile must never be attached to the converted RGB pixels
        if im.info.get("icc_profile") and im.mode in ("RGB", "RGBA", "L", "LA", "P"):
            kw["icc_profile"] = im.info["icc_profile"]
    elif target == "webp":
        kw = dict(quality=q, method=5)
    elif target == "avif":
        kw = dict(quality=q)
    elif target == "png":
        kw = dict(optimize=True)
    elif target == "tiff":
        kw = dict(compression="tiff_lzw")
    elif target == "ico":
        im = _prep(im, target).convert("RGBA")
        side = max(im.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(side, 16)]
        square.resize((256, 256), Image.LANCZOS).save(dst, "ICO", sizes=sizes)
        return
    elif target == "gif" and not animated:
        im = _prep(im, target)
        if im.mode not in ("P", "L"):
            im = im.convert("RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)

    if animated:
        frames, durations = [], []
        for i in range(im.n_frames):
            im.seek(i)
            frames.append(im.convert("RGBA"))
            durations.append(im.info.get("duration", 100))
        frames[0].save(dst, _PIL_NAME[target], save_all=True, append_images=frames[1:],
                       duration=durations, loop=im.info.get("loop", 0), disposal=2, **kw)
        return
    out = _prep(im, target)
    if "icc_profile" in kw and not _icc_matches(kw["icc_profile"], out.mode):
        del kw["icc_profile"]  # e.g. a greyscale profile on pixels that became RGB
    out.save(dst, _PIL_NAME[target], **kw)


def _icc_matches(profile: bytes, mode: str) -> bool:
    space = bytes(profile[16:20]) if profile and len(profile) >= 20 else b""
    if space == b"GRAY":
        return mode in ("L", "LA")
    if space == b"RGB ":
        return mode in ("RGB", "RGBA", "P")
    return False


def raster_to_svg(src: Path, dst: Path, ctx: Ctx):
    """True vector tracing (shapes + colours), not a bitmap wrapped in SVG. Crash-isolated: see tracing.py."""
    from .tracing import trace
    im = _prep(open_image(src), "png").convert("RGBA")
    if max(im.size) > 1600:  # tracing time & SVG size grow fast with resolution
        im.thumbnail((1600, 1600), Image.LANCZOS)
    tmp = ctx.tmpdir / "trace_in.png"
    im.save(tmp)
    trace(tmp, dst, ctx.opt("svg_detail", "balanced"), ctx)


def svg_to_png(src: Path, dst: Path, ctx: Ctx):
    import pymupdf
    try:
        doc = pymupdf.open(src)
    except Exception as e:
        raise ConversionError("This SVG couldn't be read — it may use features that aren't supported.") from e
    with doc:
        page = doc[0]
        w, h = page.rect.width or 512, page.rect.height or 512
        # Icons are scaled up to a useful size; huge drawings are scaled down so the bitmap stays
        # sane (a 20000 px SVG would need gigabytes).
        target_px = int(ctx.opt("svg_px", 2048))
        side = max(w, h)
        zoom = target_px / side if side < target_px else (8192 / side if side > 8192 else 1.0)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
        pix.save(dst)


def svg_to_pdf(src: Path, dst: Path, ctx: Ctx):
    import pymupdf
    try:
        doc = pymupdf.open(src)
    except Exception as e:
        raise ConversionError("This SVG couldn't be read — it may use features that aren't supported.") from e
    with doc, pymupdf.open("pdf", doc.convert_to_pdf()) as pdf:
        pdf.save(dst, garbage=3, deflate=True)


def image_to_pdf(src: Path, dst: Path, ctx: Ctx):
    images_to_pdf([src], dst)


def images_to_pdf(srcs: list[Path], dst: Path):
    """One page per image, page sized to the image (at its DPI, default 150)."""
    import pymupdf
    out = pymupdf.open()
    for s in srcs:
        im = open_image(s)
        n = getattr(im, "n_frames", 1) if s.suffix.lower() in (".tif", ".tiff") else 1
        for i in range(n):
            if n > 1:
                im.seek(i)
            frame = _normalise_mode(ImageOps.exif_transpose(im) or im)
            dpi = frame.info.get("dpi", (150, 150))[0] or 150
            dpi = 150 if dpi < 30 else dpi
            has_alpha = frame.mode in ("RGBA", "LA") or (frame.mode == "P" and "transparency" in frame.info)
            buf = io.BytesIO()
            if has_alpha:
                frame.convert("RGBA").save(buf, "PNG")
            else:
                frame.convert("RGB").save(buf, "JPEG", quality=95)
            w, h = frame.width * 72 / dpi, frame.height * 72 / dpi
            page = out.new_page(width=w, height=h)
            page.insert_image(page.rect, stream=buf.getvalue())
    out.save(dst, garbage=3, deflate=True)


def register(reg: Registry) -> None:
    for s in RASTER_IN:
        for d in RASTER_OUT:
            if s != d:
                # going through a lossy format costs a bit more so PNG is preferred as a hub
                reg.add(s, d, raster_to_raster, cost=1.0 if d != "jpg" else 1.1, label="Converting image")
    reg.add([f for f in RASTER_IN if f != "gif"], "svg", raster_to_svg, cost=1.5, label="Tracing to vector")
    reg.add("gif", "svg", raster_to_svg, cost=1.5, label="Tracing to vector")
    reg.add("svg", "png", svg_to_png, cost=0.5, label="Rendering SVG")
    reg.add("svg", "pdf", svg_to_pdf, label="Converting SVG")
    reg.add(RASTER_IN, "pdf", image_to_pdf, cost=1.0, label="Building PDF")
