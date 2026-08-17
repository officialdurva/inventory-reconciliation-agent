"""Reads decision_log.jsonl back and summarizes it.

Data-analyst review: logging decisions is only half the job - without
anything reading it back, decision_log.py was audit theater. Escalation
rate and the average reliability score behind each decision type are the
first two numbers anyone doing calibration work would ask for, so those are
what this computes. Nothing here is a statistical model - it's descriptive
aggregation over whatever has actually been logged so far.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from .decision_log import LOG_PATH


def _numeric(value, default=0.0):
    """.get(key, default) alone doesn't catch a field present with an
    explicit null - json `null` decodes to None, bypassing the default and
    crashing sum() downstream. Coerce anything non-numeric to the default."""
    return value if isinstance(value, (int, float)) else default


def _load_records() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    records = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a partially-written/corrupted line shouldn't fail the whole report
    return records


def summarize() -> dict:
    records = _load_records()
    total = len(records)
    if total == 0:
        return {"total": 0}

    by_decision = defaultdict(list)
    resolved_count = 0
    for r in records:
        by_decision[r.get("decision", "UNKNOWN")].append(r)
        if r.get("resolved"):
            resolved_count += 1

    decision_breakdown = {}
    for decision, recs in by_decision.items():
        decision_breakdown[decision] = {
            "count": len(recs),
            "avg_reliability_embedded_metadata": round(
                sum(_numeric(r.get("reliability_embedded_metadata")) for r in recs) / len(recs), 3
            ),
            "avg_reliability_sor": round(sum(_numeric(r.get("reliability_sor")) for r in recs) / len(recs), 3),
        }

    return {
        "total": total,
        "resolved_rate": round(resolved_count / total, 3),
        "escalation_rate": round(len(by_decision.get("ESCALATE", [])) / total, 3),
        "by_decision": decision_breakdown,
    }
