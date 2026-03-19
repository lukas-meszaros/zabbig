"""
locking.py — File-based run lock to prevent overlapping cron executions.

Uses O_CREAT | O_EXCL for atomic lock creation (no race condition).
The lock file contains the PID of the holding process, useful for debugging.
A stale lock (process no longer running) is automatically cleared.
"""
from __future__ import annotations

import errno
import logging
import os
import signal

log = logging.getLogger(__name__)


class LockError(RuntimeError):
    """Raised when the lock cannot be acquired."""


class RunLock:
    """Context manager that acquires and releases a PID file lock."""

    def __init__(self, lock_file: str) -> None:
        self.lock_file = lock_file
        self._acquired = False

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, *_) -> None:
        self.release()

    def acquire(self) -> None:
        """
        Attempt to acquire the lock.
        Raises LockError if another live process holds it.
        Clears stale locks automatically.
        """
        try:
            fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise LockError(f"Cannot create lock file {self.lock_file}: {exc}") from exc
            # File already exists — check if the holding process is still alive
            if self._is_stale():
                log.warning("Removing stale lock file: %s", self.lock_file)
                try:
                    os.unlink(self.lock_file)
                except FileNotFoundError:
                    pass
                self.acquire()
                return
            raise LockError(
                f"Another instance is already running (lock file: {self.lock_file}). "
                "If you are sure no other instance is running, delete the lock file manually."
            )
        else:
            try:
                os.write(fd, str(os.getpid()).encode())
            finally:
                os.close(fd)
            self._acquired = True
            log.debug("Lock acquired: %s (pid=%d)", self.lock_file, os.getpid())

    def release(self) -> None:
        if self._acquired:
            try:
                os.unlink(self.lock_file)
            except FileNotFoundError:
                pass
            self._acquired = False
            log.debug("Lock released: %s", self.lock_file)

    def _is_stale(self) -> bool:
        """Return True if the lock file contains a PID that no longer exists."""
        try:
            with open(self.lock_file, "r") as fh:
                pid = int(fh.read().strip())
        except (OSError, ValueError):
            return True

        try:
            os.kill(pid, 0)  # signal 0 = check-if-exists, no signal sent
            return False  # process still running
        except ProcessLookupError:
            return True  # process gone
        except PermissionError:
            return False  # process exists but we can't signal it — treat as live
