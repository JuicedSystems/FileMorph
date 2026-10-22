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

MAX_AGE = 60  # seconds: older notes are leftovers (a crash or quit mid-hand-off), not a fresh request


def inbox_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    d = Path(base) / "FileMorph" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def post(paths: list[str]) -> Path:
    """Hand files (or, with an empty list, just "show yourself") to the running FileMorph.
    Returns the note's path: it disappears once the running copy has picked it up."""
    d = inbox_dir()
    name = f"{time.time_ns()}-{os.getpid()}"
    tmp = d / f"{name}.tmp"
    tmp.write_text(json.dumps({"paths": [str(p) for p in paths]}), encoding="utf-8")
    note = d / f"{name}.json"
    os.replace(tmp, note)  # atomic: the reader never sees half a note
    return note


def wait_taken(note: Path, timeout: float = 20.0) -> bool:
    """True once the running copy has read the note. False if nobody did (it's hung or quitting)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not note.exists():
            return True
        time.sleep(0.05)
    try:
        note.unlink()  # take it back so it isn't replayed later
    except FileNotFoundError:
        return True  # picked up at the last moment
    except OSError:
        pass
    return False


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
