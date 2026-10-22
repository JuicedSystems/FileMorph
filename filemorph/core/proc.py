"""Run bundled command-line tools (pandoc, ffmpeg, soffice, the tracer) safely.

- No console windows on Windows (CREATE_NO_WINDOW).
- Every child is tracked; `kill_all()` stops them (and their own children) on cancel or quit.
- On Windows children also join a Job Object with KILL_ON_JOB_CLOSE, so if FileMorph itself
  crashes, Windows kills them too: no orphaned ffmpeg/soffice processes.
- `run()` enforces cancellation and timeouts from a polling loop that doesn't depend on the
  child producing output.
"""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .registry import Cancelled, ConversionError, Ctx

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW

_LIVE: set[subprocess.Popen] = set()
_EXTRA_PIDS: set[int] = set()          # processes we didn't spawn but own (Office via COM)
_LOCK = threading.Lock()
_JOB = None
_CLOSED = False  # set by kill_all(final=True): the app is quitting, start nothing new


def _job():
    """Windows Job Object that kills every child when FileMorph exits for any reason."""
    global _JOB
    if _JOB is not None or sys.platform != "win32":
        return _JOB
    try:
        import win32job
        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        _JOB = job
    except Exception:
        _JOB = False
    return _JOB


def popen(args: list[str], **kw) -> subprocess.Popen:
    if _CLOSED:
        raise Cancelled()
    kw.setdefault("stdin", subprocess.DEVNULL)
    if sys.platform == "win32":
        kw.setdefault("creationflags", NO_WINDOW)
    else:
        kw.setdefault("start_new_session", True)  # own process group -> whole tree can be killed
    p = subprocess.Popen([str(a) for a in args], **kw)
    job = _job()
    if job:
        try:
            import win32api
            import win32con
            import win32job
            h = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, p.pid)
            win32job.AssignProcessToJobObject(job, h)
        except Exception:
            pass
    with _LOCK:
        _LIVE.add(p)
        closed = _CLOSED
    if closed:  # quit raced with this launch
        kill_tree(p)
        _forget(p)
        raise Cancelled()
    return p


def _forget(p: subprocess.Popen) -> None:
    with _LOCK:
        _LIVE.discard(p)


def kill_tree(p_or_pid) -> None:
    """Kill a process and everything it started (soffice.exe -> soffice.bin, etc.)."""
    pid = p_or_pid if isinstance(p_or_pid, int) else p_or_pid.pid
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=15)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
    if not isinstance(p_or_pid, int):
        try:
            p_or_pid.wait(timeout=5)
        except Exception:
            pass


def register_pid(pid: int) -> None:
    with _LOCK:
        _EXTRA_PIDS.add(pid)


def unregister_pid(pid: int) -> None:
    with _LOCK:
        _EXTRA_PIDS.discard(pid)


def kill_all(final: bool = False) -> None:
    """Stop every tool FileMorph started. final=True (on quit) also blocks new launches."""
    global _CLOSED
    with _LOCK:
        if final:
            _CLOSED = True
        procs, pids = list(_LIVE), list(_EXTRA_PIDS)
    for p in procs:
        if p.poll() is None:
            kill_tree(p)
        _forget(p)
    for pid in pids:
        kill_tree(pid)
        unregister_pid(pid)


def run_capture(args: list[str], ctx: Ctx | None = None, *, cwd: Path | None = None, timeout: float = 1800,
                on_line: Callable[[str], None] | None = None, env: dict | None = None,
                idle_timeout: bool = False) -> tuple[int, str, str]:
    """Run a tool to completion; returns (exit code, stdout, stderr). Raises Cancelled / ConversionError(timeout).
    idle_timeout=True: `timeout` counts from the tool's last line of output (for long encodes that
    report progress), instead of from the start."""
    p = popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
              text=True, encoding="utf-8", errors="replace", env=env or _env())
    lines: queue.Queue = queue.Queue()
    out_chunks: list[str] = []
    err_chunks: list[str] = []

    def pump_out():
        for line in p.stdout:
            if on_line is not None:
                lines.put(line.rstrip())
            else:
                out_chunks.append(line)

    t_out = threading.Thread(target=pump_out, daemon=True)
    t_err = threading.Thread(target=lambda: err_chunks.append(p.stderr.read()), daemon=True)
    t_out.start()
    t_err.start()
    start = time.monotonic()
    try:
        while True:
            try:
                while True:
                    line = lines.get_nowait()
                    if idle_timeout:
                        start = time.monotonic()
                    on_line(line)  # progress callbacks run on this (worker) thread; may raise Cancelled
            except queue.Empty:
                pass
            if p.poll() is not None:
                break
            if ctx is not None and ctx.cancel_event is not None and ctx.cancel_event.is_set():
                kill_tree(p)
                raise Cancelled()
            if time.monotonic() - start > timeout:
                kill_tree(p)
                raise ConversionError("The conversion took too long and was stopped.")
            time.sleep(0.1)
        t_out.join(5)
        t_err.join(5)
        if ctx is not None and ctx.cancel_event is not None and ctx.cancel_event.is_set():
            raise Cancelled()  # killed from outside (kill_all) rather than by our own loop
        while not lines.empty():
            on_line(lines.get_nowait())
        return p.returncode, "".join(out_chunks), "".join(err_chunks)
    except BaseException:
        # Cancelled raised from a progress callback, or anything else: never leave the tool running
        if p.poll() is None:
            kill_tree(p)
        raise
    finally:
        _forget(p)


def run(args: list[str], ctx: Ctx | None = None, *, cwd: Path | None = None, timeout: float = 1800,
        on_line: Callable[[str], None] | None = None, err_msg: str = "The conversion tool failed.",
        env: dict | None = None, idle_timeout: bool = False) -> str:
    """Run a tool, honour cancellation, raise ConversionError with stderr on failure."""
    code, out, err = run_capture(args, ctx, cwd=cwd, timeout=timeout, on_line=on_line, env=env,
                                 idle_timeout=idle_timeout)
    if code != 0:
        detail = (err or "").strip().splitlines()[-3:]
        raise ConversionError(err_msg + (f"\n\nDetails: {' '.join(detail)}" if detail else ""))
    return out


def _env() -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def offline_env() -> dict:
    """Environment that makes HTTP(S) fetches by a child tool fail fast (keeps conversions offline)."""
    env = _env()
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        env[k] = "http://127.0.0.1:9"  # discard port: nothing listens
    env.pop("no_proxy", None)
    env.pop("NO_PROXY", None)
    return env


def child_cmd() -> list[str]:
    """Command that re-runs FileMorph itself as a helper process (frozen .exe or `python -m`)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "filemorph"]


def child_env() -> dict:
    env = _env()
    if not getattr(sys, "frozen", False):  # source checkout: make `-m filemorph` importable
        root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def resource_dir() -> Path:
    """Folder containing bundled files (PyInstaller-aware)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]
