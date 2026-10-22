"""User-initiated updates via Velopack.

Nothing here runs on its own: the app only checks when the user asks, and only
installs after the user clicks "Update". Releases are published by CI with
`vpk pack` + `vpk upload github` (see .github/workflows/build-windows.yml).

Flow: check() -> UpdateOffer (version, notes, size) -> download(offer, progress)
      -> apply_and_restart(offer)  (Velopack swaps the app folder and relaunches)
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .. import UPDATE_URL, __version__


class UpdateError(Exception):
    """Message is safe to show to the user."""


@dataclass
class UpdateOffer:
    version: str
    notes_markdown: str
    size_bytes: int
    is_delta: bool
    raw: Any = None  # velopack.UpdateInfo


class Updater:
    """Thin wrapper around velopack.UpdateManager with friendly errors."""

    def __init__(self, source: str | None = None):
        self.source = source or os.environ.get("FILEMORPH_UPDATE_URL") or UPDATE_URL
        self._mgr = None
        self._why_unavailable: str | None = None
        try:
            import velopack
            self._mgr = velopack.UpdateManager(_make_source(velopack, self.source))
        except ImportError:
            self._why_unavailable = "The update component is missing from this build."
        except Exception as e:  # not installed via Velopack (running from source / portable copy)
            msg = str(e).lower()
            if "not properly installed" in msg or "does not exist" in msg:
                self._why_unavailable = ("This copy wasn't installed with FileMorph-win-Setup.exe, "
                                         "so it can't update itself. Install it to get updates.")
            else:
                self._why_unavailable = f"Updates aren't available: {str(e).splitlines()[0]}"

    @property
    def available(self) -> bool:
        return self._mgr is not None

    @property
    def why_unavailable(self) -> str | None:
        return self._why_unavailable

    def current_version(self) -> str:
        if self._mgr is not None:
            try:
                return self._mgr.get_current_version()
            except Exception:
                pass
        return __version__

    def pending_restart(self) -> str | None:
        """A version already downloaded earlier and waiting for a restart, if any."""
        if self._mgr is None:
            return None
        try:
            asset = self._mgr.get_update_pending_restart()
            return asset.Version if asset else None
        except Exception:
            return None

    def check(self) -> UpdateOffer | None:
        if self._mgr is None:
            raise UpdateError(self._why_unavailable or "Updates aren't available.")
        try:
            info = self._mgr.check_for_updates()
        except Exception as e:
            raise UpdateError(_friendly(e, "check for updates")) from e
        if info is None:
            return None
        target = info.TargetFullRelease
        deltas = list(info.DeltasToTarget or [])
        size = sum(d.Size for d in deltas) if deltas else target.Size
        return UpdateOffer(target.Version, target.NotesMarkdown or "", int(size or 0), bool(deltas), info)

    def download(self, offer: UpdateOffer, progress: Callable[[int], None] | None = None) -> None:
        if self._mgr is None:
            raise UpdateError(self._why_unavailable or "Updates aren't available.")
        try:
            if progress is not None:
                self._mgr.download_updates(offer.raw, progress)
            else:
                self._mgr.download_updates(offer.raw)
        except Exception as e:
            raise UpdateError(_friendly(e, "download the update")) from e

    def apply_pending(self) -> None:
        """Install a version that was downloaded earlier ("Restart to update")."""
        if self._mgr is None:
            raise UpdateError(self._why_unavailable or "Updates aren't available.")
        try:
            asset = self._mgr.get_update_pending_restart()
        except Exception as e:
            raise UpdateError(_friendly(e, "install the update")) from e
        if asset is None:
            raise UpdateError("The downloaded update is no longer there. Check for updates again.")
        try:
            self._mgr.apply_updates_and_restart(asset)
        except Exception as e:
            raise UpdateError(_friendly(e, "install the update")) from e

    def apply_and_restart(self, offer: UpdateOffer) -> None:
        """Exits this process; Velopack installs the new version and relaunches it."""
        if self._mgr is None:
            raise UpdateError(self._why_unavailable or "Updates aren't available.")
        try:
            self._mgr.apply_updates_and_restart(offer.raw)
        except Exception as e:
            raise UpdateError(_friendly(e, "install the update")) from e


def _make_source(velopack, url: str):
    """GitHub repos are read through the GitHub releases API; anything else is a plain file host."""
    if re.match(r"^https?://(www\.)?github\.com/[^/]+/[^/]+/?$", url):
        return velopack.GithubSource(url.rstrip("/"))
    return url


def _log(action: str, e: Exception) -> None:
    """Keep the raw error (the on-screen message is simplified) in %LOCALAPPDATA%\\FileMorph\\logs."""
    try:
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "FileMorph" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "updates.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {action}: {type(e).__name__}: {e}\n")
    except OSError:
        pass


def _friendly(e: Exception, action: str) -> str:
    _log(action, e)
    full = str(e) or type(e).__name__
    text = full.splitlines()[0]
    low = full.lower()
    # The panel's heading already says what failed ("Couldn't check for updates"); this is the why.
    # Most specific first: HTTP errors also mention "network" in their text.
    if "404" in low or (action == "check for updates" and "not found" in low):
        return "No published updates were found. The release page may be private or not set up yet."
    if "401" in low or "403" in low or "rate limit" in low:
        return "The update server is busy or refused the request. Try again in a few minutes."
    if "checksum" in low or "hash" in low or re.search(r"\bsha-?(1|256|512)?\b", low):
        return "The download was damaged on the way. Please try again."
    if any(k in low for k in ("dns", "resolve", "connect", "timed out", "timeout", "network", "unreachable")):
        return "Check your internet connection and try again."
    return f"Something went wrong ({text})."


def human_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"
