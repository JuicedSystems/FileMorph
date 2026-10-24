"""Entry point. `FileMorph.exe [files...]`

Only one window runs at a time: launching again (e.g. Explorer's right-click menu
on several files, which starts one process per file) hands the files to the
running window through an inbox folder (see instance.py). `--selftest <report.json>` checks the bundled engines and exits.
"""
from __future__ import annotations

import getpass
import json
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from . import __version__  # single source of truth: filemorph/__init__.py


def _ident() -> str:
    return "FileMorph-" + "".join(c for c in getpass.getuser() if c.isalnum())


def selftest(report: Path) -> int:
    """Convert a few generated files through every engine; used by CI and build.ps1 on the frozen build.
    The report is rewritten after every step, so a crash part-way still shows how far it got."""
    import traceback
    report = Path(report).resolve()
    data = {"version": __version__, "python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False)),
            "results": {}}

    def save():
        report.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def step(name, fn):
        data["current_step"] = name
        save()
        try:
            fn()
            data["results"][name] = "ok"
        except Exception:
            data["results"][name] = "FAIL " + traceback.format_exc(limit=6)
        save()

    save()
    try:
        from PIL import Image, ImageDraw
        from .core.engine import convert_file
        tmp = Path(tempfile.mkdtemp(prefix="filemorph-selftest-"))
        out = tmp / "out"
        png = tmp / "t.png"
        im = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle((10, 10, 190, 110), 20, fill=(40, 120, 240, 255))
        im.save(png)
        md = tmp / "t.md"
        md.write_text("# Hello\n\nA *test* with a table:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
        csv = tmp / "t.csv"
        csv.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
        produced: dict[str, Path] = {}

        def conv(src, dst, sub="."):
            def run():
                produced[dst] = convert_file(src, dst, out / sub)[0]
            return run

        for src, dst in [(png, "jpg"), (png, "pdf"), (png, "svg"), (png, "webp"), (md, "docx"), (md, "pdf"),
                         (csv, "xlsx"), (csv, "pdf")]:
            step(f"{src.suffix[1:]}->{dst}", conv(src, dst))
        for src_key, dst in (("pdf", "png"), ("pdf", "docx"), ("docx", "pdf"), ("xlsx", "csv")):
            if src_key in produced:
                step(f"{src_key}->{dst}", conv(produced[src_key], dst, "2"))

        def media():
            import subprocess
            from .core import proc
            from .core.converters.media import ffmpeg_exe
            wav = tmp / "t.wav"
            subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1",
                            str(wav)], check=True, creationflags=proc.NO_WINDOW)
            convert_file(wav, "mp3", out)
        def bw_trace():
            res = convert_file(png, "trace", out / "trace", {"trace_detail": "balanced"})[0]
            text = res.read_text(encoding="utf-8")
            if "<path" not in text or 'fill="#ffffff"' in text.lower():
                raise RuntimeError("B&W trace produced no black paths")
        step("png->trace", bw_trace)

        def scan_pdf():
            """A picture of a page: OCR (bundled models + onnxruntime) must read it."""
            import io
            import pymupdf
            from PIL import ImageFont
            page = Image.new("RGB", (1200, 500), "white")
            try:
                f = ImageFont.truetype("arial.ttf", 48)
            except OSError:
                f = ImageFont.load_default(48)
            ImageDraw.Draw(page).text((60, 80), "Invoice 4417 for Northwind", fill="black", font=f)
            ImageDraw.Draw(page).text((60, 220), "Total due 1,250.00", fill="black", font=f)
            buf = io.BytesIO()
            page.save(buf, "JPEG", quality=85)
            doc = pymupdf.open()
            doc.new_page(width=600, height=250).insert_image(pymupdf.Rect(0, 0, 600, 250), stream=buf.getvalue())
            doc.save(tmp / "scan.pdf")
            return tmp / "scan.pdf"

        def ocr_txt():
            text = convert_file(scan_pdf(), "txt", out / "ocr")[0].read_text(encoding="utf-8")
            if "Northwind" not in text or "1,250.00" not in text:
                raise RuntimeError(f"OCR read: {text!r}")

        def ocr_searchable():
            import pymupdf
            res = convert_file(tmp / "scan.pdf", "ocrpdf", out / "ocr")[0]
            with pymupdf.open(res) as d:
                if "Northwind" not in d[0].get_text():
                    raise RuntimeError("searchable PDF has no text layer")
        step("scan->txt", ocr_txt)
        step("scan->ocrpdf", ocr_searchable)

        def shrink():
            big = tmp / "big.png"
            grain = Image.effect_noise((1400, 900), 48).convert("RGB")  # photo-like detail
            Image.blend(Image.radial_gradient("L").resize((1400, 900)).convert("RGB"), grain, 0.5).save(big)
            res = convert_file(big, "jpg", out / "shrink", {"quality": 98})[0]
            small = convert_file(res, "shrink", out / "shrink")[0]
            if small.suffix != ".jpg" or small.stat().st_size >= res.stat().st_size:
                raise RuntimeError("SHRINK didn't make the JPG smaller")
        step("jpg->shrink", shrink)

        step("wav->mp3", media)

        def updater():
            from .core.updater import Updater
            u = Updater()  # "not installed" is expected for a build that hasn't been through Setup.exe
            data["updater"] = "ready" if u.available else (u.why_unavailable or "unavailable")
        step("updater", updater)

        def ui_imports():
            from .ui.node import controller  # noqa: F401  (catches missing UI modules / fonts)
            from .ui.node import style
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets" / "fonts"
            if not list(base.glob("*.ttf")):
                raise RuntimeError(f"fonts missing in {base}")
        step("ui", ui_imports)

        if sys.platform == "win32":
            def windows_com():
                # pywin32 drives Office and creates the "Send to" shortcut; a packaging slip here
                # would otherwise only show up on users' PCs.
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                try:
                    win32com.client.Dispatch("WScript.Shell")
                finally:
                    pythoncom.CoUninitialize()
            step("windows-com", windows_com)

        from .core.converters.office import backend_name
        from .core.converters.tracing import LAST_TRACER
        data["office_backend"] = backend_name()
        data["svg_tracer"] = LAST_TRACER["name"]
    except Exception:
        data["crash"] = traceback.format_exc()
    data.pop("current_step", None)
    save()
    ok = "crash" not in data and all(v == "ok" for v in data["results"].values())
    return 0 if ok else 1


JUST_UPDATED: list[str] = []  # set by Velopack's on_restarted hook -> "Updated to vX" on the node


def run_velopack_hooks() -> None:
    """Must run first: Velopack launches the app with special args during install/update/uninstall,
    handles them here (registering or removing the Explorer integration) and exits."""
    try:
        import velopack
    except ImportError:
        return
    from .core import shell

    def refresh_recipes():
        try:  # saved recipes keep their right-click entries across reinstalls and updates
            from .core import recipes
            shell.install_recipes(recipes.load())
        except Exception:
            pass

    def after_install(version):
        shell.install()
        refresh_recipes()

    def after_update(version):
        try:  # the portable zip shouldn't add itself to Explorer's menus
            if velopack.UpdateManager().get_is_portable():
                return
        except Exception:
            pass
        shell.install()  # refresh paths/icons in case they changed
        refresh_recipes()

    def before_uninstall(version):
        shell.uninstall()

    def restarted(version):
        JUST_UPDATED.append(str(version))

    try:
        # A downloaded-but-not-applied update waits for the user's "Restart to update" click; it is
        # never applied silently at launch (which would also drop files passed from Explorer).
        (velopack.App()
         .set_auto_apply_on_startup(False)
         .on_after_install_fast_callback(after_install)
         .on_after_update_fast_callback(after_update)
         .on_before_uninstall_fast_callback(before_uninstall)
         .on_restarted(restarted)
         .run())
    except Exception:
        pass  # never block startup over the updater


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if len(argv) >= 5 and argv[1] == "--trace":  # isolated vector-tracing helper (see core/converters/tracing.py)
        from .core.converters.tracing import trace_child_main
        return trace_child_main(argv[2], argv[3], argv[4])
    if len(argv) >= 4 and argv[1] == "--pdf2docx":  # isolated PDF -> Word helper (see converters/pdf.py)
        from .core.converters.pdf import pdf2docx_child_main
        return pdf2docx_child_main(argv[2], argv[3])
    if "--selftest" in argv:
        i = argv.index("--selftest")
        return selftest(Path(argv[i + 1]) if len(argv) > i + 1 else Path("selftest.json"))
    run_velopack_hooks()
    recipe = None
    if "--recipe" in argv:  # Explorer: right-click -> FileMorph recipes -> <name>
        i = argv.index("--recipe")
        recipe = argv[i + 1] if len(argv) > i + 1 else None
        argv = argv[:i] + argv[i + 2:]
    files = [str(Path(a).resolve()) for a in argv[1:] if not a.startswith("--")]

    if sys.platform == "win32":
        try:  # own taskbar icon/grouping instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FileMorph.App")
        except Exception:
            pass

    # --- single instance election (before any window code, so extra copies exit fast) ----------
    from PySide6.QtCore import QLockFile
    from . import instance
    lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{_ident()}.lock"))
    lock.setStaleLockTime(0)  # only a dead owner process makes the lock stale
    owns_lock = "--new-window" not in argv and lock.tryLock(0)
    if "--new-window" not in argv and not owns_lock:
        # A FileMorph is already running (or starting): leave our files in its inbox and exit.
        if sys.platform == "win32":  # let it bring itself to the front
            try:
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
            except Exception:
                pass
        try:
            if instance.wait_taken(instance.post(files, recipe)):
                return 0
        except OSError:
            pass  # inbox not writable
        # Nobody picked the files up (the running copy is hung or just quitting): open our own
        # window rather than losing them. Take over the lock if its owner has gone meanwhile.
        owns_lock = lock.tryLock(0)

    from PySide6.QtCore import QFileSystemWatcher, QTimer, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("FileMorph")
    app.setOrganizationName("FileMorph")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")

    # tidy up work folders a crash or forced exit left in %TEMP% (in the background)
    import threading
    from .core.engine import cleanup_stale_temp
    threading.Thread(target=cleanup_stale_temp, daemon=True).start()

    pending: list[tuple[list[str], str | None]] = [(list(files), recipe)] if files else []
    win = None
    classic = "--classic" in argv

    def deliver(paths: list[str], rid: str | None = None):
        if win is None:
            pending.append((paths, rid))
            return
        if rid and not classic:
            win.receive_paths([Path(p) for p in paths], rid)
            return
        if classic:
            if paths:
                win.receive_paths([Path(p) for p in paths])
            win.showNormal()
            win.raise_()
            win.activateWindow()
        elif paths:
            win.receive_paths([Path(p) for p in paths])
        else:
            win.expand()

    def check_inbox(*_):
        try:
            batches, seen = instance.drain()
        except OSError:
            return
        if seen and not batches:
            deliver([])
        for paths, rid in batches:
            deliver(paths, rid)

    # Only the copy holding the lock reads the inbox (a --new-window/--classic extra window doesn't).
    watcher = None
    poll = QTimer(interval=1500, timeout=check_inbox)  # backstop if a change notification is missed
    if owns_lock:
        try:
            watcher = QFileSystemWatcher([str(instance.inbox_dir())])
            watcher.directoryChanged.connect(check_inbox)
        except OSError:
            watcher = None
        poll.start()
        check_inbox()  # notes left by copies started while we were starting up

    from .ui import theme as th
    from .ui.widgets import app_icon_pixmap

    ico = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets" / "icon.ico"
    app.setWindowIcon(QIcon(str(ico)) if ico.exists() else QIcon(app_icon_pixmap(256)))

    if classic:  # the original single-window UI, kept as a fallback
        from .ui.main_window import MainWindow
        app.setFont(th.ui_font(10))
        win = MainWindow()
        win.show()
        if pending:
            QTimer.singleShot(0, lambda: win.add_files([Path(p) for b in pending for p in b[0]], replace=True))
    else:  # the floating Morph node
        from .ui.node.controller import MorphController
        app.setQuitOnLastWindowClosed(False)  # lives in the tray
        win = MorphController(app)
        if JUST_UPDATED:
            QTimer.singleShot(900, lambda: win.show_updated(JUST_UPDATED[0]))
        for paths, rid in pending:
            win.receive_paths([Path(p) for p in paths], rid)
    code = app.exec()
    poll.stop()
    if owns_lock:
        lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
