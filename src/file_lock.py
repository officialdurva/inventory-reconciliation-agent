"""Minimal, dependency-free advisory file lock.

precedent_memory.py and decision_log.py both do read-modify-write against a
flat file with no protection - fine for a single-process demo, but two
concurrent process_return() calls in a real service could race on the same
write and silently drop one. Uses atomic exclusive file creation
(os.O_CREAT | os.O_EXCL) as the mutex primitive - portable across POSIX and
Windows without any extra package, unlike fcntl/msvcrt which differ per
platform. Advisory only: it only protects callers that go through this lock.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager

LOCK_SUFFIX = ".lock"
DEFAULT_TIMEOUT_SECONDS = 5
POLL_INTERVAL_SECONDS = 0.05


@contextmanager
def locked(path: str, timeout: float = DEFAULT_TIMEOUT_SECONDS):
    lock_path = path + LOCK_SUFFIX
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock on {path}")
            time.sleep(POLL_INTERVAL_SECONDS)
    try:
        yield
    finally:
        os.close(fd)
        os.remove(lock_path)
