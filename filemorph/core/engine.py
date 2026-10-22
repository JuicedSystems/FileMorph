"""Runs a conversion plan for one file (or merges several into one PDF)."""
from __future__ import annotations

import errno
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable

from .converters import build_registry
from .formats import FORMATS, detect
from .registry import Cancelled, ConversionError, Ctx

ProgressFn = Callable[[float, str], None]


def cleanup_stale_temp(max_age_hours: float = 12) -> int:
    """Remove work folders left behind by a crash or a forced exit. Only folders older than
    max_age_hours are touched, so a conversion running in another session is never disturbed."""
    import time
    root = Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    try:
        for d in root.glob("filemorph-*"):
            try:
                if d.is_dir() and not d.is_symlink() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


def _new_tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="filemorph-"))


def _execute(src: Path, src_fmt: str, dst_fmt: str, final_dir: Path, options: dict,
             progress: ProgressFn | None, cancel: threading.Event | None, tmp: Path) -> list[Path]:
    """Run the plan, leaving results in final_dir. Returns produced paths."""
    plan = build_registry().plan(src_fmt, dst_fmt)
    if not plan:
        raise ConversionError(f"Converting {FORMATS[src_fmt].label} to {FORMATS[dst_fmt].label} isn't supported.")
    cur = src
    n = len(plan)
    outputs: list[Path] = []
    for i, edge in enumerate(plan):
        final = i == n - 1
        step_dir = final_dir if final else tmp / f"step{i}"
        step_dir.mkdir(parents=True, exist_ok=True)
        dst = step_dir / f"{src.stem}.{FORMATS[edge.dst].ext}"

        def hop_progress(frac: float, msg: str, _i=i, _label=edge.label):
            if progress:
                progress((_i + frac) / n, msg or _label)

        ctx = Ctx(edge.src, edge.dst, tmp, options, hop_progress, cancel)
        ctx.progress(0.0, edge.label)
        result = edge.fn(cur, dst, ctx)
        produced = [Path(p) for p in result] if result else [dst]
        produced = [p for p in produced if p.exists() and (p.is_dir() or p.stat().st_size > 0)]
        if not produced:
            raise ConversionError("The conversion finished but produced an empty file.")
        if final:
            outputs = produced
        else:
            cur = produced[0]
    return outputs


def fallback_dir() -> Path:
    """Where results go when the chosen folder can't be written (Downloads\\FileMorph)."""
    home = Path.home()
    d = home / "Downloads"
    return (d if d.exists() else home) / "FileMorph"


def _suffixed(name: str, is_dir: bool, n: int) -> str:
    if n == 0:
        return name
    p = Path(name)
    if is_dir and name.endswith("_media"):
        return f"{name[:-6]}-{n}_media"  # media folder names stay link-safe (no spaces/brackets)
    if is_dir:
        return f"{name} ({n})"
    return f"{p.stem} ({n}){p.suffix}"


def _free_names(produced: list[Path], out_dir: Path) -> list[Path]:
    """One shared suffix for the whole set, so 'Report - page 1.png, Report - page 2.png' and a
    Markdown file with its media folder keep matching names."""
    n = 0
    while True:
        targets = [out_dir / _suffixed(p.name, p.is_dir(), n) for p in produced]
        if not any(t.exists() for t in targets):
            return targets
        n += 1


def _relink_markdown(produced: list[Path], targets: list[Path]) -> dict[Path, str]:
    """If a media folder gets a new name, point the Markdown file's links at it.
    Returns the original texts so a failed publish can undo the edit."""
    renames = {p.name: t.name for p, t in zip(produced, targets) if p.is_dir() and p.name != t.name}
    originals: dict[Path, str] = {}
    if not renames:
        return originals
    for p in produced:
        if p.suffix.lower() == ".md" and p.is_file():
            text = p.read_text(encoding="utf-8")
            originals[p] = text
            for a, b in renames.items():
                text = text.replace(a + "/", b + "/")
            p.write_text(text, encoding="utf-8")
    return originals


def _remove(path: Path) -> None:
    try:
        shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
    except OSError:
        pass


def _place(src: Path, target: Path) -> str:
    """Put one result in place without ever leaving a half-written file under the real name.
    Same drive: an instant rename. Other drive: copy to a hidden temp name, then rename.
    Returns how it was placed, for rollback."""
    try:
        os.rename(src, target)
        return "renamed"
    except OSError as e:
        if getattr(e, "errno", None) != errno.EXDEV and getattr(e, "winerror", None) != 17:
            raise  # not a cross-drive move: a real failure (permissions, disk full...)
    part = target.with_name(f".{target.name}.filemorph-part")
    try:
        if src.is_dir():
            shutil.copytree(src, part)
        else:
            shutil.copy2(src, part)
        os.replace(part, target)
    except BaseException:
        _remove(part)
        raise
    return "copied"


def _publish_into(produced: list[Path], out_dir: Path) -> list[Path]:
    """All or nothing: either every result is in out_dir, or none is and the temp copies are intact."""
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = _free_names(produced, out_dir)
    originals = _relink_markdown(produced, targets)
    placed: list[tuple[Path, Path, str]] = []
    try:
        for p, t in zip(produced, targets):
            placed.append((p, t, _place(p, t)))
    except BaseException:
        for p, t, how in reversed(placed):
            if how == "renamed":
                try:
                    os.rename(t, p)  # back to the temp folder, ready for the fallback location
                except OSError:
                    pass
            else:
                _remove(t)
        for f, text in originals.items():
            try:
                f.write_text(text, encoding="utf-8")
            except OSError:
                pass
        raise
    return targets


def _publish(produced: list[Path], out_dir: Path) -> list[Path]:
    """Move results from the temp folder to the destination without overwriting anything.
    If that folder refuses the write (read-only share, Controlled Folder Access, full disk on a
    USB stick...), the results go to Downloads\\FileMorph instead of being lost."""
    try:
        return _publish_into(produced, out_dir)
    except OSError:
        fb = fallback_dir()
        try:
            same = out_dir.resolve() == fb.resolve()
        except OSError:
            same = False
        if same:
            raise
        return _publish_into(produced, fb)


def convert_file(src: Path, dst_fmt: str, out_dir: Path | None = None, options: dict | None = None,
                 progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> list[Path]:
    src = Path(src)
    fmt = detect(src)
    if fmt is None:
        raise ConversionError("This file type isn't recognised.")
    if not src.exists():
        raise ConversionError("The file no longer exists.")
    out_dir = Path(out_dir) if out_dir else src.parent
    tmp = _new_tmp()
    try:
        produced = _execute(src, fmt.key, dst_fmt, tmp / "out", options or {}, progress, cancel, tmp)
        if cancel and cancel.is_set():
            raise Cancelled()
        return _publish(produced, out_dir)
    except (ConversionError, Cancelled):
        raise
    except PermissionError as e:
        raise ConversionError("Windows blocked access to a file. Close it in other apps or choose a "
                              "different save location.") from e
    except MemoryError as e:
        raise ConversionError("This file is too large to convert on this computer.") from e
    except Exception as e:
        raise ConversionError(f"Something went wrong: {e}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def merge_to_pdf(srcs: list[Path], out_path: Path, options: dict | None = None,
                 progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> list[Path]:
    """Convert every file to PDF and combine them, in order, into one document."""
    import pymupdf
    tmp = _new_tmp()
    try:
        merged = pymupdf.open()
        n = len(srcs)
        for i, s in enumerate(srcs):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            fmt = detect(s)
            if fmt is None:
                raise ConversionError(f"{s.name}: this file type isn't recognised.")

            def sub(frac, msg, _i=i):
                if progress:
                    progress((_i + frac * 0.95) / n, f"{s.name}: {msg}")
            if fmt.key == "pdf":
                part = s
            else:
                part_dir = tmp / f"part{i}"
                part = _execute(s, fmt.key, "pdf", part_dir, options or {}, sub, cancel, tmp)[0]
            with pymupdf.open(part) as d:
                if d.needs_pass:
                    raise ConversionError(f"{s.name} is password-protected.")
                merged.insert_pdf(d)
        tmp_out = tmp / "out" / out_path.name
        tmp_out.parent.mkdir(parents=True, exist_ok=True)
        merged.save(tmp_out, garbage=3, deflate=True)
        merged.close()
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        return _publish([tmp_out], out_path.parent)
    except (ConversionError, Cancelled):
        raise
    except Exception as e:
        raise ConversionError(f"Something went wrong: {e}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
