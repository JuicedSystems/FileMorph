"""Single-instance hand-off through an "inbox" folder.

Explorer starts one FileMorph.exe per selected file (e.g. 200 files -> 200 processes at once).
Each extra process only has to drop a small JSON note into the inbox and exit: no Qt window,
no waiting for the running copy to answer, so nothing times out under load and no second orb
opens. The running copy watches the folder and merges whatever arrives into one batch.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MAX_AGE = 600  # seconds: older notes are leftovers from a crash, not a fresh request


def inbox_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    d = Path(base) / "FileMorph" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def post(paths: list[str]) -> None:
    """Hand files (or, with an empty list, just "show yourself") to the running FileMorph."""
    d = inbox_dir()
    name = f"{time.time_ns()}-{os.getpid()}"
    tmp = d / f"{name}.tmp"
    tmp.write_text(json.dumps({"paths": [str(p) for p in paths]}), encoding="utf-8")
    os.replace(tmp, d / f"{name}.json")  # atomic: the reader never sees half a note


def drain() -> tuple[list[str], bool]:
    """Read and remove every note. Returns (paths in arrival order, whether any note arrived)."""
    d = inbox_dir()
    now = time.time()
    paths: list[str] = []
    seen = False
    try:
        notes = sorted(d.glob("*.json"))
    except OSError:
        return [], False
    for f in notes:
        try:
            fresh = now - f.stat().st_mtime < MAX_AGE
            data = json.loads(f.read_text(encoding="utf-8")) if fresh else None
        except (OSError, ValueError):
            data = None
        try:
            f.unlink()
        except OSError:
            continue  # being written/locked: leave it for the next pass
        if not isinstance(data, dict):
            continue
        seen = True
        paths += [p for p in data.get("paths", []) if isinstance(p, str)]
    for f in d.glob("*.tmp"):  # abandoned half-writes
        try:
            if now - f.stat().st_mtime > 60:
                f.unlink()
        except OSError:
            pass
    return paths, seen
