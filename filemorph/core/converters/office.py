"""High-fidelity Office conversions.

Uses Microsoft Office through COM when installed (Windows), otherwise LibreOffice
if found. These unlock legacy formats (.doc, .xls, .ppt) and pixel-perfect
Office -> PDF. Without either, FileMorph falls back to its built-in engines.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

from .. import proc
from ..registry import Cancelled, ConversionError, Ctx, Registry

WORD_IN, WORD_OUT = ["doc", "docx", "rtf", "odt"], ["doc", "docx", "rtf", "odt", "pdf"]
# CSV deliberately not routed through Office: Excel/LibreOffice split it by the system locale and
# strip leading zeros. The built-in reader handles delimiters and number formats safely.
CALC_IN, CALC_OUT = ["xls", "xlsx", "ods"], ["xls", "xlsx", "ods", "pdf"]
SLIDE_IN, SLIDE_OUT = ["ppt", "pptx", "odp"], ["ppt", "pptx", "odp", "pdf"]
NEEDS_OFFICE = {"doc", "xls", "ppt", "pptx", "odp"}  # formats that are much better with a backend

# ------------------------------------------------------------------ detection


@lru_cache(maxsize=1)
def ms_office_apps() -> frozenset[str]:
    if sys.platform != "win32" or os.environ.get("FILEMORPH_NO_MSOFFICE"):
        return frozenset()
    try:
        import winreg
        import win32com.client  # noqa: F401  (pywin32 must be bundled)
    except ImportError:
        return frozenset()
    found = set()
    for app in ("Word", "Excel", "PowerPoint"):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{app}.Application\\CLSID"))
            found.add(app)
        except OSError:
            pass
    return frozenset(found)


@lru_cache(maxsize=1)
def soffice_exe() -> str | None:
    if os.environ.get("FILEMORPH_NO_LIBREOFFICE"):
        return None
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cand = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if cand.exists():
                return str(cand)
    elif sys.platform == "darwin":
        cand = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if cand.exists():
            return str(cand)
    return None


def backend_name() -> str | None:
    apps = ms_office_apps()
    if apps:
        return "Microsoft Office"
    if soffice_exe():
        return "LibreOffice"
    return None


# ------------------------------------------------------------- MS Office COM

_WORD_CODES = {"doc": 0, "docx": 16, "rtf": 6, "odt": 23}
_EXCEL_CODES = {"xls": 56, "xlsx": 51, "ods": 60}
_PPT_CODES = {"ppt": 1, "pptx": 24, "odp": 35, "pdf": 32}


# A wrong dummy password makes Office fail fast on protected files instead of showing an invisible
# password prompt that would hang the hidden Office process forever.
_NO_PASSWORD = "\u2063filemorph-no-password\u2063"
_OFFICE_EXE = {"Word": "WINWORD.EXE", "Excel": "EXCEL.EXE", "PowerPoint": "POWERPNT.EXE"}
_COM_TIMEOUT = 600


def _office_pids(exe: str) -> set[int]:
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"],
                                  capture_output=True, text=True, creationflags=proc.NO_WINDOW, timeout=15).stdout
    except Exception:
        return set()
    pids = set()
    for line in out.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def _com(fam: str, fn, ctx: Ctx):
    """Run fn(app) against a private, hidden Office instance with a cancel/timeout watchdog.
    Office can't be interrupted politely mid-call, so the watchdog kills *our* instance's process
    (identified by the PIDs that appeared when we started it — never the user's own Office windows)."""
    # One conversion per Office app at a time: the "new process" detection below must not mix up
    # two of our own instances (a cancel would then kill the wrong one).
    with _COM_LOCKS[fam]:
        return _com_locked(fam, fn, ctx)


_COM_LOCKS = {fam: threading.Lock() for fam in ("Word", "Excel", "PowerPoint")}


def _com_locked(fam: str, fn, ctx: Ctx):
    ctx.check_cancel()
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    exe = _OFFICE_EXE[fam]
    before = _office_pids(exe)
    app = None
    ours: set[int] = set()
    stop = threading.Event()
    killed = {"why": None}

    def watchdog():
        start = time.monotonic()
        while not stop.wait(0.2):
            cancelled = ctx.cancel_event is not None and ctx.cancel_event.is_set()
            if cancelled or time.monotonic() - start > _COM_TIMEOUT:
                killed["why"] = "cancel" if cancelled else "timeout"
                for pid in ours:
                    proc.kill_tree(pid)
                return

    try:
        app = win32com.client.DispatchEx(f"{fam}.Application")
        ours.update(_office_pids(exe) - before)
        for pid in ours:
            proc.register_pid(pid)
        threading.Thread(target=watchdog, daemon=True).start()
        try:
            return fn(app)
        finally:
            try:
                # PowerPoint is single-instance: DispatchEx may hand us the user's own open
                # PowerPoint. Never quit that one while it has their presentations open.
                # PowerPoint is single-instance: DispatchEx may hand us (or later share with) the
                # user's own PowerPoint. Never quit it while any presentation is still open.
                users_app = fam == "PowerPoint" and app.Presentations.Count > 0
                if not users_app:
                    app.Quit()
            except Exception:
                pass
    except ConversionError:
        raise
    except Exception as e:
        if killed["why"] == "cancel":
            raise Cancelled() from e
        if killed["why"] == "timeout":
            raise ConversionError("Microsoft Office took too long with this file and was stopped.") from e
        raise ConversionError("Microsoft Office couldn't convert this file. It may be damaged or "
                              "password-protected.") from e
    finally:
        stop.set()
        app = None
        for pid in ours:
            proc.unregister_pid(pid)
        pythoncom.CoUninitialize()


def _word(src: Path, dst: Path, fmt: str, ctx: Ctx):
    def go(app):
        app.Visible = False
        app.DisplayAlerts = 0
        try:
            app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable: never run macros
        except Exception:
            pass
        try:  # don't refresh links/linked pictures a document points at (web, network shares)
            app.Options.UpdateLinksAtOpen = False
            app.Options.UpdateLinksAtPrint = False
        except Exception:
            pass
        doc = app.Documents.Open(str(src.resolve()), ConfirmConversions=False, ReadOnly=True,
                                 AddToRecentFiles=False, PasswordDocument=_NO_PASSWORD,
                                 Revert=False, Visible=False,
                                 OpenAndRepair=False, NoEncodingDialog=True)
        try:
            if fmt == "pdf":
                doc.ExportAsFixedFormat(str(dst.resolve()), 17)
            else:
                doc.SaveAs2(str(dst.resolve()), FileFormat=_WORD_CODES[fmt])
        finally:
            doc.Close(False)
    _com("Word", go, ctx)


def _excel(src: Path, dst: Path, fmt: str, ctx: Ctx):
    def go(app):
        app.Visible = False
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False
        try:
            app.AutomationSecurity = 3
        except Exception:
            pass
        # (no WriteResPassword: ReadOnly=True already skips the write-reservation prompt)
        wb = app.Workbooks.Open(str(src.resolve()), UpdateLinks=0, ReadOnly=True, Password=_NO_PASSWORD,
                                IgnoreReadOnlyRecommended=True,
                                Notify=False, AddToMru=False, CorruptLoad=0)
        try:
            if fmt == "pdf":
                wb.ExportAsFixedFormat(0, str(dst.resolve()))
            else:
                wb.SaveAs(str(dst.resolve()), FileFormat=_EXCEL_CODES[fmt])
        finally:
            wb.Close(False)
    _com("Excel", go, ctx)


def _powerpoint(src: Path, dst: Path, fmt: str, ctx: Ctx):
    def go(app):
        for attr, val in (("AutomationSecurity", 3), ("DisplayAlerts", 1)):  # 1 = ppAlertsNone
            try:
                setattr(app, attr, val)
            except Exception:
                pass
        # "file::password" makes PowerPoint fail instead of prompting for a password
        pres = app.Presentations.Open(f"{src.resolve()}::{_NO_PASSWORD}", ReadOnly=True, Untitled=False,
                                      WithWindow=False)
        try:
            pres.SaveAs(str(dst.resolve()), _PPT_CODES[fmt])
        finally:
            pres.Close()
    _com("PowerPoint", go, ctx)


# ------------------------------------------------------------ LibreOffice

_LO_FILTERS = {
    "doc": "doc:MS Word 97", "docx": "docx:MS Word 2007 XML", "rtf": "rtf:Rich Text Format",
    "odt": "odt", "xls": "xls:MS Excel 97", "xlsx": "xlsx:Calc MS Excel 2007 XML", "ods": "ods",
    "ppt": "ppt:MS PowerPoint 97", "pptx": "pptx:Impress MS PowerPoint 2007 XML", "odp": "odp",
    "pdf": "pdf",
}


_LO_LOCK = threading.Lock()


class _ProfileLock:
    """Cross-process lock on the LibreOffice profile. Two soffice processes sharing a profile
    don't run side by side: the second hands its job to the first and can hang. Threads in this
    process are serialised by _LO_LOCK; this also covers other FileMorph processes."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self, ctx: Ctx, timeout: float = 900):
        self.fh = open(self.path, "a+b")
        start = time.monotonic()
        while True:
            try:
                self.fh.seek(0)
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.monotonic() - start > timeout:
                    self.release()
                    raise ConversionError("LibreOffice is busy with another conversion. Try again in a moment.")
                try:
                    ctx.check_cancel()
                except BaseException:
                    self.release()
                    raise
                time.sleep(0.2)

    def release(self):
        if self.fh is None:
            return
        try:
            self.fh.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.fh.close()
        self.fh = None


# LibreOffice settings FileMorph needs in its private profile:
#  - never fetch images/links a document points at (web trackers, \\server\share NTLM leaks,
#    or a private file:///C:/... picture copied into the output)
#  - never run macros
_LO_SETTINGS = [
    ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks", "true"),
    ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "3"),
    ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "true"),
    ("/org.openoffice.Office.Common/Misc", "UseOpenCL", "false"),
    ("/org.openoffice.Office.Writer/Content/Update", "Link", "1"),  # 1 = never update links
    ("/org.openoffice.Office.Calc/Content/Update", "Link", "1"),
]


def _lo_profile() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "FileMorph" / "lo-profile"
    base.mkdir(parents=True, exist_ok=True)
    _lo_harden(base)
    return base


def _lo_harden(profile: Path) -> None:
    """Make sure the profile's registrymodifications.xcu carries _LO_SETTINGS (added or replaced)."""
    import re as _re
    xcu = profile / "user" / "registrymodifications.xcu"
    try:
        text = xcu.read_text(encoding="utf-8") if xcu.exists() else ""
    except OSError:
        return
    if "<oor:items" not in text:
        text = ('<?xml version="1.0" encoding="UTF-8"?>\n<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
                'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
                '</oor:items>\n')
    changed = False
    for path, name, value in _LO_SETTINGS:
        item = (f'<item oor:path="{path}"><prop oor:name="{name}" oor:op="fuse"><value>{value}</value>'
                f'</prop></item>')
        pat = _re.compile(r'<item oor:path="' + _re.escape(path) + r'"><prop oor:name="' + _re.escape(name)
                          + r'"[^>]*>.*?</item>', _re.S)
        if item in text:
            continue
        text, n = pat.subn(lambda _m: item, text)
        if not n:
            text = text.replace("</oor:items>", item + "\n</oor:items>")
        changed = True
    if changed:
        try:
            xcu.parent.mkdir(parents=True, exist_ok=True)
            xcu.write_text(text, encoding="utf-8")
        except OSError:
            pass


def _libreoffice(src: Path, dst: Path, fmt: str, ctx: Ctx):
    outdir = ctx.tmpdir / f"lo-{fmt}"
    outdir.mkdir(exist_ok=True)
    # copy to a plain name: soffice dislikes some characters and names output after input
    work_src = ctx.tmpdir / f"input{src.suffix.lower()}"
    if work_src.resolve() != src.resolve():
        shutil.copyfile(src, work_src)
    args = [soffice_exe(), f"-env:UserInstallation={_lo_profile().as_uri()}", "--headless", "--norestore",
            "--nolockcheck", "--convert-to", _LO_FILTERS[fmt], "--outdir", str(outdir), str(work_src)]
    # LibreOffice can't share a profile between simultaneous runs: serialise, and retry once
    # because the very first launch (profile creation) occasionally fails.
    with _LO_LOCK:
        lock = _ProfileLock(_lo_profile().parent / "lo-profile.lock")
        lock.acquire(ctx)
        try:
            for attempt in range(2):
                try:
                    proc.run(args, ctx, timeout=600, err_msg="LibreOffice couldn't convert this file.")
                except ConversionError as e:
                    if attempt or "too long" in str(e):  # a timeout won't go better the second time
                        raise
                if list(outdir.glob(f"input.{fmt}")):
                    break
        finally:
            lock.release()
    produced = list(outdir.glob(f"input.{fmt}"))
    if not produced:
        raise ConversionError("LibreOffice couldn't convert this file. It may be damaged or password-protected.")
    shutil.move(str(produced[0]), dst)


# ------------------------------------------------------------- dispatch

def _family(src_fmt: str) -> str:
    if src_fmt in WORD_IN:
        return "Word"
    if src_fmt in CALC_IN:
        return "Excel"
    return "PowerPoint"


def office_convert(src: Path, dst: Path, ctx: Ctx):
    fam = _family(ctx.src_fmt)
    label = {"Word": "Opening in Word", "Excel": "Opening in Excel", "PowerPoint": "Opening in PowerPoint"}
    if fam in ms_office_apps():
        ctx.progress(0.1, label[fam])
        {"Word": _word, "Excel": _excel, "PowerPoint": _powerpoint}[fam](src, dst, ctx.dst_fmt, ctx)
    elif soffice_exe():
        ctx.progress(0.1, "Converting with LibreOffice")
        _libreoffice(src, dst, ctx.dst_fmt, ctx)
    else:  # pragma: no cover - edge only registered when a backend exists
        raise ConversionError("This conversion needs Microsoft Office or LibreOffice.")
    if not dst.exists() or dst.stat().st_size == 0:
        raise ConversionError("The Office conversion produced no output.")


def _all_shapes(shapes):
    """Shapes in reading order, including the ones inside groups."""
    for sh in shapes:
        if getattr(sh, "shape_type", None) == 6 and hasattr(sh, "shapes"):  # MSO_SHAPE_TYPE.GROUP
            yield from _all_shapes(sh.shapes)
        else:
            yield sh


def pptx_to_txt(src: Path, dst: Path, ctx: Ctx):
    from pptx import Presentation
    try:
        prs = Presentation(src)
    except Exception as e:
        raise ConversionError("This presentation couldn't be read.") from e
    out = []
    for i, slide in enumerate(prs.slides, 1):
        lines = [f"--- Slide {i} ---"]
        for shape in _all_shapes(slide.shapes):
            if shape.has_text_frame:
                lines += [p.text for p in shape.text_frame.paragraphs if p.text.strip()]
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    lines.append("\t".join(c.text for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            lines.append("Notes: " + slide.notes_slide.notes_text_frame.text.strip())
        out.append("\n".join(lines))
    dst.write_text("\n\n".join(out) + "\n", encoding="utf-8")


def register(reg: Registry) -> None:
    # final-only (multi=True): never chain slide *text* into a fake "PDF of the slides"
    reg.add("pptx", "txt", pptx_to_txt, multi=True, label="Extracting slide text")
    apps = ms_office_apps()
    lo = soffice_exe() is not None
    engine = "msoffice" if apps else "libreoffice"
    if "Word" in apps or lo:
        reg.add(WORD_IN, WORD_OUT, office_convert, cost=0.7, label="Converting with Office", engine=engine)
    if "Excel" in apps or lo:
        reg.add(CALC_IN, CALC_OUT, office_convert, cost=0.7, label="Converting with Office", engine=engine)
    if "PowerPoint" in apps or lo:
        reg.add(SLIDE_IN, SLIDE_OUT, office_convert, cost=0.7, label="Converting with Office", engine=engine)
