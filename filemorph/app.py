"""Entry point. `FileMorph.exe [files...]`

Only one window runs at a time: launching again (e.g. Explorer's right-click menu
on several files, which starts one process per file) hands the files to the
running window. `--selftest <report.json>` checks the bundled engines and exits.
"""
from __future__ import annotations

import getpass
import json
import sys
import tempfile
import time
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

    def after_install(version):
        shell.install()

    def after_update(version):
        shell.install()  # refresh paths/icons in case they changed

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
    if "--selftest" in argv:
        i = argv.index("--selftest")
        return selftest(Path(argv[i + 1]) if len(argv) > i + 1 else Path("selftest.json"))
    run_velopack_hooks()
    files = [str(Path(a).resolve()) for a in argv[1:] if not a.startswith("--")]

    if sys.platform == "win32":
        try:  # own taskbar icon/grouping instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FileMorph.App")
        except Exception:
            pass

    from PySide6.QtCore import QLockFile, QTimer, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("FileMorph")
    app.setOrganizationName("FileMorph")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")

    # --- single instance election ------------------------------------------
    name = _ident()
    lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{name}.lock"))
    lock.setStaleLockTime(0)
    primary = "--new-window" in argv or lock.tryLock(0)
    if not primary:
        # Another FileMorph owns the lock (possibly still starting up): hand our files over.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            sock = QLocalSocket()
            sock.connectToServer(name)
            if sock.waitForConnected(200):
                if sys.platform == "win32":  # let the running FileMorph bring itself to the front
                    try:
                        import ctypes
                        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
                    except Exception:
                        pass
                sock.write(json.dumps(files).encode())
                sock.flush()
                sock.waitForBytesWritten(1000)
                sock.disconnectFromServer()
                return 0
            time.sleep(0.1)
        primary = True  # owner is unresponsive: run on our own

    # tidy up work folders a crash or forced exit left in %TEMP% (in the background)
    import threading
    from .core.engine import cleanup_stale_temp
    threading.Thread(target=cleanup_stale_temp, daemon=True).start()

    pending: list[str] = list(files)
    win = None
    classic = "--classic" in argv
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)
    QLocalServer.removeServer(name)
    server.listen(name)

    def deliver(paths: list[str]):
        if win is None:
            pending.extend(paths)
            return
        if classic:
            if paths:
                win.add_files([Path(p) for p in paths], replace=False)
            win.showNormal()
            win.raise_()
            win.activateWindow()
        elif paths:
            win.receive_paths([Path(p) for p in paths])
        else:
            win.expand()

    def on_conn():
        conn = server.nextPendingConnection()
        buf = bytearray()

        def read():
            buf.extend(bytes(conn.readAll()))

        def done():
            buf.extend(bytes(conn.readAll()))  # data that arrived together with the disconnect
            try:
                paths = json.loads(buf.decode("utf-8") or "[]")
                paths = [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else []
            except ValueError:
                paths = []
            # several Explorer launches arrive back to back: the controller merges them into one batch
            deliver(paths)
            conn.deleteLater()
        conn.readyRead.connect(read)
        conn.disconnected.connect(done)
    server.newConnection.connect(on_conn)

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
            QTimer.singleShot(0, lambda: win.add_files([Path(p) for p in pending], replace=True))
    else:  # the floating Morph node
        from .ui.node.controller import MorphController
        app.setQuitOnLastWindowClosed(False)  # lives in the tray
        win = MorphController(app)
        if JUST_UPDATED:
            QTimer.singleShot(900, lambda: win.show_updated(JUST_UPDATED[0]))
        if pending:
            win.receive_paths([Path(p) for p in pending])
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
