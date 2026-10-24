# PyInstaller spec — build with:  pyinstaller packaging/filemorph.spec --noconfirm
# Produces dist/FileMorph/FileMorph.exe (one-folder build: fast startup, installer packs it).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is injected by PyInstaller)

datas, binaries, hiddenimports = [], [], []


def _unused(path: str) -> bool:
    """pymupdf.layout is an optional AI layout module (~50 MB of models) and mupdf-devel holds
    C headers/libs for building extensions; FileMorph uses neither. (onnxruntime itself is
    needed: it runs the OCR models.)"""
    p = path.replace("\\", "/")
    return "pymupdf/layout" in p or "pymupdf/mupdf-devel" in p


# Packages that ship native binaries or data files (pandoc.exe, ffmpeg.exe, MuPDF, libheif, ...)
for pkg in ("pypandoc", "imageio_ffmpeg", "pymupdf", "pillow_heif", "vtracer", "pdf2docx",
            "pdfplumber", "pdfminer", "docx", "pptx", "openpyxl", "odf", "xlrd", "velopack",
            "rapidocr", "onnxruntime", "pyclipper", "shapely", "omegaconf"):  # OCR engine + its models
    d, b, h = collect_all(pkg, filter_submodules=lambda name: not name.startswith("pymupdf.layout"))
    datas += [x for x in d if not _unused(x[0])]
    binaries += [x for x in b if not _unused(x[0])]
    hiddenimports += h

datas += [(str(ROOT / "assets" / "icon.ico"), "assets"), (str(ROOT / "assets" / "icon.png"), "assets"),
          (str(ROOT / "assets" / "fonts"), "assets/fonts")]   # Geist + Geist Mono (OFL) for the Morph UI
hiddenimports += ["PySide6.QtNetwork", "PySide6.QtSvg"]
if sys.platform == "win32":
    hiddenimports += ["win32com", "win32com.client", "pythoncom", "pywintypes", "winreg"]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pymupdf.layout", "onnxruntime.training", "onnxruntime.transformers", "onnxruntime.quantization", "tkinter", "matplotlib", "IPython", "notebook", "pytest", "scipy",
              "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FileMorph",
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,          # windowed app: no console flash
    upx=False,              # UPX triggers antivirus false positives
    disable_windowed_traceback=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FileMorph",
)
