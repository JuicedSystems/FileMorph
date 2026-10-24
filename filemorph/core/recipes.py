"""Recipes: a saved conversion (format + options + where + name), optionally watching a folder.

Stored as JSON in %LOCALAPPDATA%\\FileMorph so the running app, Explorer's right-click menu
(`FileMorph.exe --recipe <id> files...`) and the tests all read the same thing. No Qt in here.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .formats import FORMATS, detect

MAX_RECIPES = 30
RENAME_HELP = "{name} original name · {date} · {time} · {n} number in batch"
_TOKENS = ("{name}", "{date}", "{time}", "{n}")
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TEMP_SUFFIXES = (".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload", ".!ut", ".filemorph-part")


def data_dir() -> Path:
    """%LOCALAPPDATA%/FileMorph (FILEMORPH_DATA overrides it, for tests)."""
    override = os.environ.get("FILEMORPH_DATA")
    d = Path(override) if override else Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "FileMorph"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Recipe:
    name: str
    target: str
    options: dict = field(default_factory=dict)
    save_dir: str = ""          # "" = next to the original
    rename: str = ""            # "" = FileMorph's usual name
    watch_dir: str = ""         # folder to watch ("" = none)
    watching: bool = False
    watch_since: float = 0.0    # when watching started (files already there then are left alone)
    sources: list = field(default_factory=list)  # format keys it was made for ([] = anything that fits)
    id: str = field(default_factory=lambda: secrets.token_hex(4))

    @property
    def tag(self) -> str:
        return FORMATS[self.target].tag

    def summary(self) -> str:
        """'PDF → OCR · watching Scans' style line for lists."""
        src = "/".join(FORMATS[k].tag for k in self.sources[:2]) + ("…" if len(self.sources) > 2 else "")
        bits = [f"{src} → {self.tag}" if src else f"→ {self.tag}"]
        bits.append(f"to {Path(self.save_dir).name or self.save_dir}" if self.save_dir else "next to original")
        if self.rename:
            bits.append(f"named {self.rename}")
        if self.watch_dir:
            where = Path(self.watch_dir).name or self.watch_dir
            bits.append(f"watching {where}" if self.watching else f"paused: {where}")
        return " · ".join(bits)

    def accepts(self, fmt_key: str, registry) -> bool:
        """Can and should this recipe take a file of this format? A recipe made for photos isn't
        offered for a PDF just because a PDF could technically become a JPG too."""
        if fmt_key == self.target or self.target not in registry.targets(fmt_key):
            return False
        if not self.sources:
            return True
        return fmt_key in self.sources or FORMATS[fmt_key].category in {FORMATS[s].category for s in self.sources}


def _clean_recipe(d) -> Recipe | None:
    if not isinstance(d, dict) or d.get("target") not in FORMATS or not isinstance(d.get("name"), str):
        return None
    r = Recipe(name=d["name"].strip()[:60] or FORMATS[d["target"]].tag, target=d["target"])
    if isinstance(d.get("options"), dict):
        r.options = {k: v for k, v in d["options"].items() if isinstance(k, str)
                     and isinstance(v, (str, int, float, bool))}
    for k in ("save_dir", "rename", "watch_dir"):
        if isinstance(d.get(k), str):
            setattr(r, k, d[k])
    r.watching = bool(d.get("watching")) and bool(r.watch_dir)
    if isinstance(d.get("watch_since"), (int, float)):
        r.watch_since = float(d["watch_since"])
    if isinstance(d.get("sources"), list):
        r.sources = [k for k in d["sources"] if isinstance(k, str) and k in FORMATS][:12]
    if isinstance(d.get("id"), str) and re.fullmatch(r"[0-9a-f]{4,16}", d["id"]):
        r.id = d["id"]
    return r


def path() -> Path:
    return data_dir() / "recipes.json"


def load() -> list[Recipe]:
    """Saved recipes. A damaged file is set aside (recipes.json.bad), never a reason to crash."""
    p = path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.get("recipes", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        try:
            os.replace(p, p.with_suffix(".json.bad"))
        except OSError:
            pass
        return []
    out, seen = [], set()
    for d in items:
        r = _clean_recipe(d)
        if r and r.id not in seen:
            seen.add(r.id)
            out.append(r)
    return out[:MAX_RECIPES]


def save(recipes: list[Recipe]) -> None:
    p = path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": 1, "recipes": [asdict(r) for r in recipes[:MAX_RECIPES]]}, indent=1),
                   encoding="utf-8")
    os.replace(tmp, p)  # atomic: Explorer launching a recipe never reads half a file


def find(recipes: list[Recipe], rid: str) -> Recipe | None:
    return next((r for r in recipes if r.id == rid), None)


def default_name(target: str, src_keys: set[str] | None = None) -> str:
    src = "/".join(sorted(FORMATS[k].tag for k in src_keys)) if src_keys and len(src_keys) <= 2 else ""
    return f"{src} → {FORMATS[target].tag}" if src else f"Make {FORMATS[target].tag}"


# ------------------------------------------------------------------ names
def render_name(pattern: str, src: Path, n: int = 1, now: float | None = None) -> str | None:
    """File name (without extension) from a pattern, or None for FileMorph's usual name."""
    pattern = (pattern or "").strip()
    if not pattern:
        return None
    t = time.localtime(now if now is not None else time.time())
    out = (pattern.replace("{name}", src.stem).replace("{date}", time.strftime("%Y-%m-%d", t))
           .replace("{time}", time.strftime("%H-%M-%S", t)).replace("{n}", str(n)))
    out = _BAD_CHARS.sub("_", out).strip().rstrip(". ")
    return out[:150] or None


def example_name(pattern: str, target: str) -> str:
    stem = render_name(pattern, Path("Holiday photo.heic"), 1) or f"Holiday photo{FORMATS[target].name_suffix}"
    ext = "heic" if FORMATS[target].keep_ext else FORMATS[target].ext
    return f"{stem}.{ext}"


# ------------------------------------------------------------------ watch folders
def file_key(p: Path, st: os.stat_result | None = None) -> str:
    st = st or p.stat()
    return f"{str(p).lower()}|{st.st_size}|{st.st_mtime_ns}"


class Ledger:
    """What a watched recipe already did: inputs it converted (path + size + time, so an edited file
    counts as new) and outputs it wrote (path only: never feed our own output back in)."""
    KEEP = 5000

    def __init__(self, file: Path | None = None):
        self.file = file or data_dir() / "watch-ledger.json"
        self.data: dict[str, dict[str, float]] = {}
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.data = {k: {kk: float(vv) for kk, vv in v.items() if isinstance(vv, (int, float))}
                             for k, v in raw.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def seen(self, rid: str, p: Path, st: os.stat_result | None = None) -> bool:
        d = self.data.get(rid, {})
        low = str(p).lower()
        if f"out|{low}" in d or f"base|{low}" in d:
            return True
        try:
            return file_key(p, st) in d
        except OSError:
            return True

    def add(self, rid: str, src: Path | None = None, outputs: list[Path] = ()) -> None:
        d = self.data.setdefault(rid, {})
        now = time.time()
        if src is not None:
            try:
                d[file_key(src)] = now
            except OSError:
                pass
        for o in outputs:
            d[f"out|{str(o).lower()}"] = now
        if len(d) > self.KEEP:  # oldest conversions go first; the baseline is kept
            old = sorted((kv for kv in d.items() if not kv[0].startswith("base|")), key=lambda kv: kv[1])
            for k, _ in old[: len(d) - self.KEEP]:
                del d[k]

    def baseline(self, recipe: "Recipe") -> int:
        """Watching starts: whatever is in the folder now is left alone, whatever arrives later
        is new (by name, so a file copied in with an old date still counts as new)."""
        self.data[recipe.id] = {k: v for k, v in self.data.get(recipe.id, {}).items() if not k.startswith("base|")}
        n = 0
        now = time.time()
        try:
            for e in os.scandir(recipe.watch_dir):
                if e.is_file(follow_symlinks=False):
                    self.data[recipe.id][f"base|{e.path.lower()}"] = now
                    n += 1
        except OSError:
            pass
        return n

    def forget(self, rid: str) -> None:
        self.data.pop(rid, None)

    def save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            os.replace(tmp, self.file)
        except OSError:
            pass


def ignorable(p: Path) -> bool:
    """Partial downloads, Office lock files, hidden and temp files."""
    n = p.name.lower()
    return (n.startswith((".", "~$", "~")) or n.endswith(_TEMP_SUFFIXES) or n in ("thumbs.db", "desktop.ini"))


def candidates(recipe: Recipe, registry, ledger: Ledger) -> list[tuple[Path, os.stat_result]]:
    """Files in the watched folder (top level) that this recipe should convert, oldest first."""
    folder = Path(recipe.watch_dir)
    suffix = FORMATS[recipe.target].name_suffix.lower()
    out = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    for e in entries:
        try:
            if not e.is_file(follow_symlinks=False):
                continue
            p = Path(e.path)
            if ignorable(p) or (suffix and p.stem.lower().endswith(suffix)):
                continue
            st = e.stat()
            fmt = detect(p)
            if fmt is None or not recipe.accepts(fmt.key, registry) or ledger.seen(recipe.id, p, st):
                continue
            out.append((p, st))
        except OSError:
            continue
    return sorted(out, key=lambda x: x[1].st_mtime)


class Settle:
    """A file is ready once its size and time stop changing for `quiet` seconds and it can be
    opened (a phone import, a scanner or a browser download may still be writing it)."""

    def __init__(self, quiet: float = 2.0):
        self.quiet = quiet
        self.last: dict[str, tuple[int, int, float]] = {}

    def ready(self, p: Path, st: os.stat_result, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        k = str(p).lower()
        sig = (st.st_size, st.st_mtime_ns)
        prev = self.last.get(k)
        if prev is None or prev[:2] != sig:
            self.last[k] = (*sig, now)
            return False
        if now - prev[2] < self.quiet or st.st_size == 0:
            return False
        try:
            with open(p, "rb"):
                pass
        except OSError:
            return False  # still locked by the program writing it
        self.last.pop(k, None)
        return True
