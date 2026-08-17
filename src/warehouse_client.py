"""Simulates querying the warehouse system of record (SOR).

Independently failing component #2. Failure modes it can produce:
  - no records at all for the SKU
  - multiple plausible candidate batches (ambiguity)
  - stale records (not touched in a long time, so may no longer reflect
    physical reality)
Match score against the physical batch code is computed here (string
similarity) - this is the point where component #1's output and component
#2's output actually interact, rather than being judged in isolation.
"""
from __future__ import annotations

import difflib

from .models import SORCandidate, SORQueryResult

DB = {}


def seed(sku: str, records: list) -> None:
    DB[sku] = records


def reset() -> None:
    DB.clear()


def _fuzzy_ratio(a, b) -> float:
    if not a or not b:
        return 0.5  # no physical code to compare against -> neutral prior, not zero
    return difflib.SequenceMatcher(None, a, b).ratio()


def query_sor(sku: str, embedded_metadata) -> SORQueryResult:
    records = DB.get(sku, [])
    if not records:
        return SORQueryResult(candidates=[], query_errors=[f"no SOR records found for sku {sku}"])

    candidates = []
    query_errors = []
    for rec in records:
        # A real SOR API can return a malformed row without invalidating the
        # whole query - one bad record should be skipped and reported, not
        # crash the query for every other candidate that parsed fine.
        try:
            score = _fuzzy_ratio(embedded_metadata.batch_code, rec["batch_id"])
            candidates.append(
                SORCandidate(
                    batch_id=rec["batch_id"],
                    expiry_date=rec["expiry_date"],
                    bin_id=rec["bin_id"],
                    qty=rec["qty"],
                    last_updated_days_ago=rec["last_updated_days_ago"],
                    match_score=score,
                )
            )
        except (KeyError, TypeError) as e:
            query_errors.append(f"skipped malformed SOR record for sku {sku}: {e}")
    candidates.sort(key=lambda c: c.match_score, reverse=True)
    return SORQueryResult(candidates=candidates, query_errors=query_errors)
