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


if __name__ == "__main__":
    multiprocessing.freeze_support()  # pdf2docx / pandas may spawn helpers
    try:
        from filemorph.app import main
        code = main()
    except SystemExit:
        raise
    except BaseException:
        _report_crash(traceback.format_exc())
        code = 1
    sys.exit(code)
