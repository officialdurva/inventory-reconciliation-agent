"""The Donnie-style piece: remembers how past unresolved cases were resolved.

Without this, every return that hits the same conflict pattern for the same
SKU re-escalates from zero forever. With it, a new case whose evidence
profile is close enough (cosine similarity over a small feature vector) to
a previously *human-resolved* case can reuse that resolution instead of
escalating again - but only above a deliberately high similarity bar, and
never for a case that hasn't been confirmed by a person at least once.
"""
from __future__ import annotations

import json
import math
import os

from . import file_lock
from .decision_log import RULESET_VERSION
from .models import Precedent

STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "memory_store.json")
AUTO_RESOLVE_SIMILARITY = 0.90


def _load():
    if not os.path.exists(STORE_PATH):
        return []
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(records):
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def reset():
    with file_lock.locked(STORE_PATH):
        _save([])


def build_feature_vector(rel_embedded_meta, rel_sor, candidate_count, staleness_days, checksum_valid) -> list:
    return [
        rel_embedded_meta,
        rel_sor,
        min(candidate_count, 5) / 5,
        min(staleness_days, 365) / 365,
        1.0 if checksum_valid else 0.0,
    ]


# Plain cosine similarity implicitly claims every feature is equally
# informative, which was never justified for a 5-dim vector mixing two
# continuous reliability scores with one binary flag. These weights are
# still a manual judgment call, not fit from data - but now an explicit,
# visible one: order matches build_feature_vector's return order
# [rel_embedded_meta, rel_sor, candidate_count, staleness, checksum_valid].
FEATURE_WEIGHTS = [1.5, 1.5, 1.0, 1.0, 0.5]


def _weighted(vec):
    return [v * w ** 0.5 for v, w in zip(vec, FEATURE_WEIGHTS)]


def _cosine_similarity(a, b) -> float:
    a, b = _weighted(a), _weighted(b)
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _is_usable_record(r) -> bool:
    """A stored precedent needs a real feature vector and a real resolution to
    be usable. .get(key, default) alone doesn't catch a field present with an
    explicit null (json `null` decodes to Python None, which bypasses the
    default) - so this checks types/emptiness directly. Same philosophy as
    warehouse_client.py skipping a malformed SOR record: a corrupted entry
    gets dropped here, not propagated downstream into a crash."""
    if not isinstance(r, dict):
        return False
    features = r.get("features")
    if not isinstance(features, list) or not features:
        return False
    return all(
        isinstance(r.get(field), str) and r.get(field)
        for field in ("sku", "resolution_batch_id", "resolution_bin_id", "resolution_expiry")
    )


def find_similar(sku: str, features: list):
    """Returns (Precedent | None, similarity). Scoped to the same SKU on purpose -
    a resolution for one SKU's conflict pattern should not silently apply to another.
    Records failing _is_usable_record are skipped entirely rather than crashing
    the lookup - the store is a hand-editable flat file, and a partially-written
    or corrupted record shouldn't take down every other lookup for that SKU."""
    with file_lock.locked(STORE_PATH):
        records = [r for r in _load() if r.get("sku") == sku and _is_usable_record(r)]
    if not records:
        return None, 0.0
    best, best_sim = None, 0.0
    for r in records:
        sim = _cosine_similarity(features, r["features"])
        if sim > best_sim:
            best, best_sim = r, sim
    if best is None:
        return None, 0.0
    return (
        Precedent(
            case_id=best.get("case_id", ""),
            features=best["features"],
            sku=best["sku"],
            resolution_batch_id=best["resolution_batch_id"],
            resolution_bin_id=best["resolution_bin_id"],
            resolution_expiry=best["resolution_expiry"],
            note=best.get("note", ""),
            ruleset_version=best.get("ruleset_version", ""),
        ),
        best_sim,
    )


def record_resolution(case_id, sku, features, resolution_batch_id, resolution_bin_id, resolution_expiry, note):
    with file_lock.locked(STORE_PATH):
        records = _load()
        records.append(
            {
                "case_id": case_id,
                "sku": sku,
                "features": features,
                "resolution_batch_id": resolution_batch_id,
                "resolution_bin_id": resolution_bin_id,
                "resolution_expiry": resolution_expiry,
                "note": note,
                "ruleset_version": RULESET_VERSION,
            }
        )
        _save(records)
