"""Every file format FileMorph knows about, grouped into families."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Fmt:
    key: str               # canonical id, also the default extension
    label: str             # short human name shown under the extension
    category: str          # document | sheet | slides | image | audio | video
    exts: tuple[str, ...]  # extensions recognised on input (first = output ext)
    input_only: bool = False

    @property
    def ext(self) -> str:
        return self.exts[0]


CATEGORIES: list[tuple[str, str]] = [
    ("document", "Documents"),
    ("sheet", "Spreadsheets"),
    ("slides", "Presentations"),
    ("image", "Images"),
    ("audio", "Audio"),
    ("video", "Video"),
]
CATEGORY_LABEL = dict(CATEGORIES)

_ALL = [
    # Documents
    Fmt("pdf", "PDF", "document", ("pdf",)),
    Fmt("docx", "Word", "document", ("docx",)),
    Fmt("doc", "Word 97-2003", "document", ("doc",)),
    Fmt("odt", "OpenDocument", "document", ("odt",)),
    Fmt("rtf", "Rich Text", "document", ("rtf",)),
    Fmt("txt", "Plain text", "document", ("txt", "text", "log")),
    Fmt("md", "Markdown", "document", ("md", "markdown")),
    Fmt("html", "Web page", "document", ("html", "htm")),
    Fmt("epub", "eBook", "document", ("epub",)),
    # Spreadsheets & data
    Fmt("xlsx", "Excel", "sheet", ("xlsx", "xlsm")),
    Fmt("xls", "Excel 97-2003", "sheet", ("xls",)),
    Fmt("ods", "OpenDocument", "sheet", ("ods",)),
    Fmt("csv", "Data table", "sheet", ("csv",)),
    Fmt("tsv", "Tab table", "sheet", ("tsv", "tab")),
    Fmt("json", "JSON data", "sheet", ("json",)),
    # Presentations
    Fmt("pptx", "PowerPoint", "slides", ("pptx",)),
    Fmt("ppt", "PowerPoint 2003", "slides", ("ppt",)),
    Fmt("odp", "OpenDocument", "slides", ("odp",)),
    # Images
    Fmt("png", "PNG image", "image", ("png",)),
    Fmt("jpg", "JPEG image", "image", ("jpg", "jpeg", "jfif", "jpe")),
    Fmt("webp", "WebP image", "image", ("webp",)),
    Fmt("svg", "Vector", "image", ("svg",)),
    Fmt("gif", "GIF", "image", ("gif",)),
    Fmt("heic", "iPhone photo", "image", ("heic", "heif"), input_only=True),
    Fmt("avif", "AVIF image", "image", ("avif",)),
    Fmt("tiff", "TIFF image", "image", ("tiff", "tif")),
    Fmt("bmp", "Bitmap", "image", ("bmp",)),
    Fmt("ico", "Windows icon", "image", ("ico",)),
    # Audio
    Fmt("mp3", "MP3 audio", "audio", ("mp3",)),
    Fmt("wav", "WAV audio", "audio", ("wav",)),
    Fmt("m4a", "AAC audio", "audio", ("m4a", "aac")),
    Fmt("flac", "Lossless", "audio", ("flac",)),
    Fmt("ogg", "Ogg Vorbis", "audio", ("ogg", "oga")),
    Fmt("opus", "Opus audio", "audio", ("opus",)),
    Fmt("wma", "Windows audio", "audio", ("wma",), input_only=True),
    Fmt("aiff", "AIFF audio", "audio", ("aiff", "aif"), input_only=True),
    # Video
    Fmt("mp4", "MP4 video", "video", ("mp4", "m4v")),
    Fmt("mov", "QuickTime", "video", ("mov",)),
    Fmt("mkv", "Matroska", "video", ("mkv",)),
    Fmt("webm", "WebM video", "video", ("webm",)),
    Fmt("avi", "AVI video", "video", ("avi",)),
    Fmt("wmv", "Windows video", "video", ("wmv",), input_only=True),
]

FORMATS: dict[str, Fmt] = {f.key: f for f in _ALL}
_BY_EXT: dict[str, Fmt] = {e: f for f in _ALL for e in f.exts}

# Formats surfaced first for a given source, in order.
SUGGESTED: dict[str, list[str]] = {
    "pdf": ["docx", "xlsx", "jpg", "png", "txt"],
    "docx": ["pdf", "doc", "txt", "html"],
    "doc": ["docx", "pdf", "txt"],
    "odt": ["docx", "pdf"],
    "rtf": ["docx", "pdf"],
    "txt": ["pdf", "docx"],
    "md": ["html", "pdf", "docx"],
    "html": ["pdf", "docx", "md"],
    "epub": ["pdf", "docx", "txt"],
    "xlsx": ["csv", "pdf", "xls", "json"],
    "xls": ["xlsx", "csv", "pdf"],
    "ods": ["xlsx", "csv"],
    "csv": ["xlsx", "json", "pdf"],
    "tsv": ["xlsx", "csv"],
    "json": ["xlsx", "csv"],
    "pptx": ["pdf", "jpg", "png"],
    "ppt": ["pptx", "pdf"],
    "odp": ["pptx", "pdf"],
    "png": ["jpg", "pdf", "svg", "webp", "ico"],
    "jpg": ["png", "pdf", "webp", "svg"],
    "webp": ["png", "jpg", "gif"],
    "svg": ["png", "pdf", "jpg"],
    "gif": ["mp4", "png", "webp"],
    "heic": ["jpg", "png", "pdf"],
    "avif": ["jpg", "png"],
    "tiff": ["jpg", "png", "pdf"],
    "bmp": ["png", "jpg"],
    "ico": ["png"],
    "mp3": ["wav", "m4a"],
    "wav": ["mp3", "flac"],
    "m4a": ["mp3", "wav"],
    "flac": ["mp3", "wav"],
    "ogg": ["mp3", "wav"],
    "opus": ["mp3", "wav"],
    "wma": ["mp3", "wav"],
    "aiff": ["mp3", "wav"],
    "mp4": ["mp3", "gif", "mov", "webm"],
    "mov": ["mp4", "mp3", "gif"],
    "mkv": ["mp4", "mp3"],
    "webm": ["mp4", "mp3", "gif"],
    "avi": ["mp4", "mp3"],
    "wmv": ["mp4", "mp3"],
}


def detect(path: str | Path) -> Fmt | None:
    """Identify a file's format from its extension, falling back to sniffing."""
    p = Path(path)
    f = _BY_EXT.get(p.suffix.lower().lstrip("."))
    if f:
        return f
    return _sniff(p)


_MP4_BRANDS = {b"avc1", b"dash", b"f4v ", b"MSNV", b"mmp4", b"NDAS", b"XAVC", b"MP4 "}


def _sniff(p: Path) -> Fmt | None:
    try:
        head = p.open("rb").read(64)
    except OSError:
        return None
    sigs = [  # noqa: E501
        (b"%PDF", "pdf"), (b"\x89PNG", "png"), (b"\xff\xd8\xff", "jpg"),
        (b"GIF8", "gif"), (b"BM", "bmp"), (b"II*\x00", "tiff"), (b"MM\x00*", "tiff"),
        (b"ID3", "mp3"), (b"fLaC", "flac"), (b"OggS", "ogg"),
        (b"\x1aE\xdf\xa3", "mkv"), (b"\xd0\xcf\x11\xe0", "doc"),
    ]
    for sig, key in sigs:
        if head.startswith(sig):
            return FORMATS[key]
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return FORMATS["webp"]
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return FORMATS["wav"]
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return FORMATS["heic"]
        if brand in (b"avif", b"avis"):
            return FORMATS["avif"]
        if brand.startswith(b"M4A"):
            return FORMATS["m4a"]
        if brand.startswith(b"qt"):
            return FORMATS["mov"]
        if brand in _MP4_BRANDS or brand.startswith((b"3gp", b"3g2", b"iso", b"mp4", b"M4V")):
            return FORMATS["mp4"]
        return None  # other ISO-media files (JPEG 2000, camera RAW, ...) aren't videos
    if head.lstrip().startswith(b"<svg") or b"<svg" in head:
        return FORMATS["svg"]
    return None
