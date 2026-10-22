"""Windows shell integration, registered from Velopack's install/update/uninstall hooks.

Adds (per-user, no admin):
  - right-click "Convert with FileMorph" on files and folders
  - FileMorph in the "Send to" menu
  - FileMorph in "Open with"
Everything is removed again on uninstall.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_KEYS = [r"Software\Classes\*\shell\FileMorph", r"Software\Classes\Directory\shell\FileMorph",
         r"Software\Classes\Applications\FileMorph.exe"]


def _sendto_link() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "SendTo" / "FileMorph.lnk"


def install(exe: str | None = None) -> None:
    if sys.platform != "win32":
        return
    import winreg
    exe = exe or sys.executable
    cmd = f'"{exe}" "%1"'
    icon = f'"{exe}",0'
    for base in _KEYS[:2]:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Convert with FileMorph")
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
            winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _KEYS[2]) as k:
        winreg.SetValueEx(k, "FriendlyAppName", 0, winreg.REG_SZ, "FileMorph")
    # SupportedTypes is what makes Windows offer FileMorph under "Open with" for these files
    try:
        from .formats import FORMATS
        exts = sorted({e.lower() for f in FORMATS.values() for e in f.exts})
    except Exception:
        exts = []
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _KEYS[2] + r"\SupportedTypes") as k:
        for e in exts:
            winreg.SetValueEx(k, "." + e.lstrip("."), 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _KEYS[2] + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
    try:
        import win32com.client
        link = _sendto_link()
        link.parent.mkdir(parents=True, exist_ok=True)
        sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(link))
        sc.TargetPath = exe
        sc.IconLocation = f"{exe},0"
        sc.Description = "Convert with FileMorph"
        sc.Save()
    except Exception as e:  # Send-to is a nicety; never fail the install over it
        _log(f"Send to shortcut not created: {e!r}")
    _notify_shell()


def uninstall() -> None:
    if sys.platform != "win32":
        return
    import winreg
    for base in _KEYS:
        _delete_tree(winreg, winreg.HKEY_CURRENT_USER, base)
    try:
        _sendto_link().unlink(missing_ok=True)
    except OSError:
        pass
    _notify_shell()


def _delete_tree(winreg, root, path: str) -> None:
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    child = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(winreg, root, path + "\\" + child)
        winreg.DeleteKey(root, path)
    except OSError:
        pass


def _log(msg: str) -> None:
    try:
        import time
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FileMorph" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "install.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except OSError:
        pass


def _notify_shell() -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass
