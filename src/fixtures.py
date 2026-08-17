"""Deterministic test/demo fixtures - four cases, each isolating a specific
failure mode described in the task spec.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import warehouse_client as wc

TODAY = date(2026, 8, 14)


def _d(days_from_today: int) -> date:
    return TODAY + timedelta(days=days_from_today)


def _iso(days_from_today: int) -> str:
    return _d(days_from_today).isoformat()


def seed_all() -> None:
    wc.reset()

    # Case A: embedded metadata corrupted (unreadable batch code), SOR clean & single-candidate.
    wc.seed("SKU-1001", [
        {"batch_id": "B-7712-9", "expiry_date": _d(120), "bin_id": "B-A1", "qty": 30, "last_updated_days_ago": 3},
    ])

    # Case B: embedded metadata internally consistent, but conflicts with SOR - two plausible
    # batch records for the SKU, neither of which confirms the physical expiry.
    wc.seed("SKU-4402", [
        {"batch_id": "B-4407-5", "expiry_date": _d(62), "bin_id": "B-C1", "qty": 20, "last_updated_days_ago": 10},
        {"batch_id": "B-4409-5", "expiry_date": _d(98), "bin_id": "B-C2", "qty": 15, "last_updated_days_ago": 12},
    ])

    # Case C: reused batch id across two SOR records - the "obvious"/most-recently-active
    # record is fresh-looking, the physically-correct one is old and near-expiry.
    wc.seed("SKU-9001", [
        {"batch_id": "B-1145-1", "expiry_date": _d(291), "bin_id": "B-FRESH", "qty": 40, "last_updated_days_ago": 3},
        {"batch_id": "B-1145-1", "expiry_date": _d(16), "bin_id": "B-OLD", "qty": 6, "last_updated_days_ago": 210},
    ])

    # Case D: both components fail at once - embedded metadata unreadable AND SOR ambiguous/stale.
    wc.seed("SKU-5501", [
        {"batch_id": "B-9981-4", "expiry_date": _d(40), "bin_id": "B-E1", "qty": 10, "last_updated_days_ago": 300},
        {"batch_id": "B-9982-1", "expiry_date": _d(70), "bin_id": "B-E2", "qty": 8, "last_updated_days_ago": 280},
    ])


CASES = {
    "A_corrupted_embedded_metadata": {
        "sku": "SKU-1001",
        "raw_scan": {
            "batch_code_raw": "B-77?2-9",
            "expiry_raw": _iso(120),
            "condition_notes": "box damp, label partially torn",
            "scan_confidence": 0.55,
        },
        "expected_decision": "TRUST_SOR",
    },
    "B_ambiguous_conflict": {
        "sku": "SKU-4402",
        "raw_scan": {
            "batch_code_raw": "B-4407-5",
            "expiry_raw": _iso(30),
            "condition_notes": "sealed, good condition",
            "scan_confidence": 0.92,
        },
        "expected_resolved": False,
    },
    "B_repeat_same_conflict": {
        "sku": "SKU-4402",
        "raw_scan": {
            "batch_code_raw": "B-4407-5",
            "expiry_raw": _iso(28),
            "condition_notes": "sealed, good condition",
            "scan_confidence": 0.90,
        },
    },
    "C_obvious_choice_is_wrong": {
        "sku": "SKU-9001",
        "raw_scan": {
            "batch_code_raw": "B-1145-1",
            "expiry_raw": _iso(16),
            "condition_notes": "unopened, good condition",
            "scan_confidence": 0.95,
        },
        "expected_decision": "TRUST_EMBEDDED_METADATA",
        "expected_bin": "B-OLD",
        "true_expiry_day": 16,
    },
    "D_both_fail": {
        "sku": "SKU-5501",
        "raw_scan": {
            "batch_code_raw": "B-99?1-4",
            "expiry_raw": "2026-1?-05",
            "condition_notes": "label soaked, mostly illegible",
            "scan_confidence": 0.40,
        },
        "expected_resolved": False,
    },
}
