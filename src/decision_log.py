"""Append-only decision audit trail.

decision_log_report.py reads this back for calibration analysis (escalation
rate, per-decision score distributions). Compliance review added three
fields beyond the original set: `timestamp` and `ruleset_version` so a
historical decision can be tied to the exact logic that produced it (bump
RULESET_VERSION whenever arbiter.py's cost constants or thresholds change),
and structured `risk_multiplier`/`risk_reason` so a high-risk SKU that got
auto-resolved can be found by filtering the log, not by parsing reasoning text.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import file_lock

LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "decision_log.jsonl")

RULESET_VERSION = "1.1.0"


def reset() -> None:
    with file_lock.locked(LOG_PATH):
        if os.path.exists(LOG_PATH):
            os.remove(LOG_PATH)


def log_decision(case_id, sku, arbitration, assignment) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ruleset_version": RULESET_VERSION,
        "case_id": case_id,
        "sku": sku,
        "decision": arbitration.decision.value,
        "reliability_embedded_metadata": arbitration.reliability_embedded_metadata,
        "reliability_sor": arbitration.reliability_sor,
        "margin": arbitration.margin,
        "risk_multiplier": arbitration.risk_multiplier,
        "risk_reason": arbitration.risk_reason,
        "resolved": assignment.resolved,
        "bin_id": assignment.bin_id,
    }
    with file_lock.locked(LOG_PATH):
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
