"""Basic correctness checks for the dependency-free file lock used by
precedent_memory.py and decision_log.py to guard their read-modify-write
sections against concurrent access."""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import file_lock


def test_lock_is_released_after_use(tmp_path):
    target = str(tmp_path / "thing.json")
    with file_lock.locked(target):
        assert os.path.exists(target + file_lock.LOCK_SUFFIX)
    assert not os.path.exists(target + file_lock.LOCK_SUFFIX)


def test_second_acquire_waits_for_first_to_release(tmp_path):
    target = str(tmp_path / "thing.json")
    results = []

    def hold_lock():
        with file_lock.locked(target):
            time.sleep(0.15)
        results.append("released")

    t = threading.Thread(target=hold_lock)
    t.start()
    time.sleep(0.02)  # let the thread acquire first
    with file_lock.locked(target, timeout=2):
        results.append("second acquired")
    t.join()
    assert results == ["released", "second acquired"]


def test_timeout_raises_if_lock_held_too_long(tmp_path):
    target = str(tmp_path / "thing.json")
    with file_lock.locked(target):
        raised = False
        try:
            with file_lock.locked(target, timeout=0.1):
                pass
        except TimeoutError:
            raised = True
        assert raised
