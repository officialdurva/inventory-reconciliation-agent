"""Wires the two decisions together and applies the precedent-memory safety net."""
from __future__ import annotations

from datetime import date

from . import decision_log, precedent_memory
from .action_hints import build_action_hint
from .arbiter import arbitrate
from .bin_resolver import resolve_bin
from .embedded_metadata_reader import read_embedded_metadata
from .models import BinAssignment
from .warehouse_client import query_sor


def process_return(case_id: str, sku: str, raw_scan: dict) -> dict:
    embedded_metadata = read_embedded_metadata(raw_scan)
    sor = query_sor(sku, embedded_metadata)
    arbitration = arbitrate(sku, embedded_metadata, sor)
    assignment = resolve_bin(arbitration, embedded_metadata, sor)
    precedent_used = None

    if not assignment.resolved:
        features = precedent_memory.build_feature_vector(
            arbitration.reliability_embedded_metadata,
            arbitration.reliability_sor,
            len(sor.candidates),
            sor.candidates[0].last_updated_days_ago if sor.candidates else 999,
            embedded_metadata.checksum_valid,
        )
        precedent, similarity = precedent_memory.find_similar(sku, features)
        similarity_clears_bar = precedent and similarity >= precedent_memory.AUTO_RESOLVE_SIMILARITY
        # A precedent recorded under a different cost-threshold ruleset was
        # confirmed against assumptions that may no longer hold - reusing it
        # silently would be exactly the kind of drift decision_log's
        # ruleset_version stamping exists to catch. Require a fresh human
        # confirmation instead of auto-applying across a ruleset change.
        same_ruleset = precedent and precedent.ruleset_version == decision_log.RULESET_VERSION

        if similarity_clears_bar and same_ruleset:
            assignment = BinAssignment(
                resolved=True,
                batch_id=precedent.resolution_batch_id,
                bin_id=precedent.resolution_bin_id,
                expiry_date=date.fromisoformat(precedent.resolution_expiry),
                reasoning=(
                    f"unresolved by direct evidence ({assignment.reasoning}); resolved via precedent "
                    f"case {precedent.case_id} (similarity={similarity:.2f}): {precedent.note}"
                ),
            )
            precedent_used = (precedent, similarity)
        else:
            if similarity_clears_bar and not same_ruleset:
                note = (
                    f"nearest precedent similarity={similarity:.2f} clears the bar but was recorded "
                    f"under ruleset {precedent.ruleset_version!r} (current: {decision_log.RULESET_VERSION!r}) "
                    f"- requires re-confirmation, not auto-applied"
                )
            elif precedent:
                note = f"nearest precedent similarity={similarity:.2f} (below {precedent_memory.AUTO_RESOLVE_SIMILARITY} bar)"
            else:
                note = "no precedent on file for this SKU"
            assignment = BinAssignment(
                resolved=False,
                batch_id=None,
                bin_id=None,
                expiry_date=None,
                reasoning=f"{assignment.reasoning}; {note} -> ESCALATED to manual review",
            )

    decision_log.log_decision(case_id, sku, arbitration, assignment)

    return {
        "case_id": case_id,
        "sku": sku,
        "embedded_metadata": embedded_metadata,
        "sor": sor,
        "arbitration": arbitration,
        "assignment": assignment,
        "precedent_used": precedent_used,
        "action_hint": build_action_hint(arbitration, embedded_metadata, assignment),
    }
