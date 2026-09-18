"""The advisory lock that stops two processes owning one data directory.

This is layer 4 of the four defending the single-engine invariant
(.claude/docs/08-deployment.md §4): a StatefulSet with one replica, a no-surge rollout, and an
RWO volume are the first three, and each of them can fail in a way that still schedules a second
pod on the *same* node — where RWO offers no protection at all. The lock is what catches that.

A process that cannot take the lock exits rather than trading against a book it does not own.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)

LOCK_FILENAME = ".lock"


class DataDirectoryLocked(RuntimeError):
    """Another process already holds the data directory lock."""


class SingleWriterLock:
    """An advisory `flock` on `<data_dir>/.lock`, held for the life of the process."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / LOCK_FILENAME
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise DataDirectoryLocked(
                    f"{self.path} is held by another process; refusing to start"
                ) from exc
            raise
        os.truncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.fsync(fd)
        self._fd = fd
        logger.info("data directory lock acquired", extra={"lock_path": str(self.path)})

    def release(self) -> None:
        if self._fd is None:
            return
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None
        logger.info("data directory lock released", extra={"lock_path": str(self.path)})

    def __enter__(self) -> SingleWriterLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
