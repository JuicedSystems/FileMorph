"""Frozen-app entry point. A windowed .exe has no console, so any startup crash is written to
%LOCALAPPDATA%\\FileMorph\\logs\\crash.log (and into the --selftest report) instead of vanishing."""
import multiprocessing
import os
import sys
import time
import traceback
from pathlib import Path


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "FileMorph" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _report_crash(tb: str) -> None:
    try:
        (_log_dir() / "crash.log").write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}  argv={sys.argv}\n\n{tb}", encoding="utf-8")
    except OSError:
        pass
    if "--selftest" in sys.argv:  # make the build script show the reason
        i = sys.argv.index("--selftest")
        if len(sys.argv) > i + 1:
            try:
                import json
                Path(sys.argv[i + 1]).write_text(json.dumps({"crash": tb}, indent=2), encoding="utf-8")
            except OSError:
                pass


def _install_crash_logging() -> None:
    """Errors inside Qt callbacks and worker threads never reach main()'s try/except, and a
    windowed .exe has no stderr; log them (and native crashes) to crash.log instead."""
    def log_exc(kind, exc_type, exc, tb):
        try:
            with open(_log_dir() / "crash.log", "a", encoding="utf-8") as f:
                f.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')}  {kind}\n"
                        + "".join(traceback.format_exception(exc_type, exc, tb)))
        except OSError:
            pass

    sys.excepthook = lambda t, e, tb: log_exc("unhandled error", t, e, tb)

    import threading
    threading.excepthook = lambda a: log_exc(f"error in thread {a.thread.name if a.thread else '?'}",
                                             a.exc_type, a.exc_value, a.exc_traceback)
    try:
        import faulthandler
        global _FAULT_LOG
        path = _log_dir() / "native-crash.log"
        if path.exists() and path.stat().st_size > 1_000_000:  # keep it from growing forever
            path.unlink()
        _FAULT_LOG = open(path, "a", encoding="utf-8")  # kept open
        faulthandler.enable(_FAULT_LOG)
    except (OSError, RuntimeError):
        pass


if __name__ == "__main__":
    multiprocessing.freeze_support()  # pdf2docx / pandas may spawn helpers
    if len(sys.argv) < 2 or sys.argv[1] != "--trace":  # the tracer child crashing is expected/handled
        _install_crash_logging()
    try:
        from filemorph.app import main
        code = main()
    except SystemExit:
        raise
    except BaseException:
        _report_crash(traceback.format_exc())
        code = 1
    sys.exit(code)
