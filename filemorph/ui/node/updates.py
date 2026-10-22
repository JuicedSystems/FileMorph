"""Runs update checks/downloads off the UI thread."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ...core.updater import UpdateError, UpdateOffer, Updater


class _Job(QObject):
    checked = Signal(object, str)      # UpdateOffer | None, error message ("" = ok)
    progress = Signal(int)             # 0..100
    downloaded = Signal(str)           # error message ("" = ok)

    def __init__(self, updater: Updater, kind: str, offer: UpdateOffer | None = None):
        super().__init__()
        self.updater, self.kind, self.offer = updater, kind, offer

    @Slot()
    def run(self):
        if self.kind == "check":
            try:
                self.checked.emit(self.updater.check(), "")
            except UpdateError as e:
                self.checked.emit(None, str(e))
            except Exception as e:  # pragma: no cover - defensive
                self.checked.emit(None, f"Couldn't check for updates. ({e})")
        else:
            try:
                self.updater.download(self.offer, lambda pct: self.progress.emit(int(pct)))
                self.downloaded.emit("")
            except UpdateError as e:
                self.downloaded.emit(str(e))
            except Exception as e:  # pragma: no cover
                self.downloaded.emit(f"Couldn't download the update. ({e})")


class UpdateRunner(QObject):
    """Owns the thread for one check or download at a time."""
    checked = Signal(object, str)
    progress = Signal(int)
    downloaded = Signal(str)

    def __init__(self, updater: Updater, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.thread: QThread | None = None
        self.job: _Job | None = None

    @property
    def busy(self) -> bool:
        return self.thread is not None

    def _start(self, job: _Job):
        self.thread = QThread(self)
        self.job = job
        job.moveToThread(self.thread)
        self.thread.started.connect(job.run)
        job.checked.connect(self.checked)
        job.progress.connect(self.progress)
        job.downloaded.connect(self.downloaded)
        job.checked.connect(self._finish)
        job.downloaded.connect(self._finish)
        self.thread.finished.connect(job.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _finish(self, *_):
        if self.thread:
            self.thread.quit()
            self.thread.wait(2000)
        self.thread = None
        self.job = None

    def check(self):
        if not self.busy:
            self._start(_Job(self.updater, "check"))

    def download(self, offer: UpdateOffer):
        if not self.busy:
            self._start(_Job(self.updater, "download", offer))

    def shutdown(self, wait_ms: int = 3000) -> bool:
        """On quit: give a running check/download a moment; True if no thread is left running."""
        t = self.thread
        if t is None:
            return True
        for sig in (self.checked, self.progress, self.downloaded):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        t.quit()
        return t.wait(wait_ms)
