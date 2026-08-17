"""Decision #2: given decision #1, which specific batch/bin does the stock go to.

Trusting a source does not automatically resolve a bin - e.g. trusting SOR
when SOR itself returned two plausible candidates still requires a
tie-break, and trusting embedded metadata when no SOR record actually
confirms it still fails. Both paths can independently end in "no bin
assigned" - there is no default bin.
"""
from __future__ import annotations

from .models import BinAssignment, Decision

EXPIRY_MATCH_TOLERANCE_DAYS = 5


def resolve_bin(arbitration, embedded_metadata, sor) -> BinAssignment:
    if arbitration.decision == Decision.ESCALATE:
        return BinAssignment(False, None, None, None, "no bin assigned: arbitration escalated, awaiting manual review")

    if arbitration.decision == Decision.TRUST_SOR:
        if len(sor.candidates) == 1:
            c = sor.candidates[0]
            return BinAssignment(
                True, c.batch_id, c.bin_id, c.expiry_date,
                f"single unambiguous SOR candidate: batch {c.batch_id} -> bin {c.bin_id}",
            )
        if embedded_metadata.expiry_date:
            matches = [
                c for c in sor.candidates
                if abs((c.expiry_date - embedded_metadata.expiry_date).days) <= EXPIRY_MATCH_TOLERANCE_DAYS
            ]
            if len(matches) == 1:
                c = matches[0]
                rejected = len(sor.candidates) - 1
                return BinAssignment(
                    True, c.batch_id, c.bin_id, c.expiry_date,
                    f"SOR ambiguous ({len(sor.candidates)} candidates) but physical expiry "
                    f"{embedded_metadata.expiry_date} uniquely matches the record updated "
                    f"{c.last_updated_days_ago}d ago -> bin {c.bin_id} "
                    f"(rejected {rejected} other candidate(s) with higher/newer activity but non-matching expiry)",
                )
        return BinAssignment(
            False, None, None, None,
            f"no bin assigned: {len(sor.candidates)} SOR candidates remain ambiguous "
            f"even after cross-checking physical expiry",
        )

    # TRUST_EMBEDDED_METADATA
    if not embedded_metadata.batch_code:
        return BinAssignment(False, None, None, None, "no bin assigned: embedded metadata trusted but batch code unreadable")

    matches = [
        c for c in sor.candidates
        if c.batch_id == embedded_metadata.batch_code
        and embedded_metadata.expiry_date
        and abs((c.expiry_date - embedded_metadata.expiry_date).days) <= EXPIRY_MATCH_TOLERANCE_DAYS
    ]
    if len(matches) == 1:
        c = matches[0]
        return BinAssignment(
            True, c.batch_id, c.bin_id, c.expiry_date,
            f"embedded metadata trusted: batch {c.batch_id} confirmed against the one SOR record "
            f"matching both code and physical expiry -> bin {c.bin_id}",
        )
    if len(matches) > 1:
        return BinAssignment(
            False, None, None, None,
            "no bin assigned: embedded metadata trusted but multiple SOR bins share this batch id with matching expiry",
        )
    return BinAssignment(
        False, None, None, None,
        f"no bin assigned: embedded metadata trusted (batch {embedded_metadata.batch_code}) but none of the "
        f"{len(sor.candidates)} SOR candidate(s) for this SKU confirm it (code without matching "
        f"expiry, or no code match at all); possible unlogged batch or mislabeled item, needs manual entry",
    )
