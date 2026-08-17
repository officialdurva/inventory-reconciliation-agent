"""Translates a technical, escalated-case reasoning string into a short,
plain-language instruction.

Returns-desk review: the people actually handed an escalated case don't need
the reliability math in `arbitration.reasoning` - they need to know what to
go check. This is a thin, deliberately simple mapping from decision shape to
next step, not a generated explanation - it never invents a reason the
underlying decision didn't already have.
"""
from __future__ import annotations

from .models import BinAssignment, Decision


def build_action_hint(arbitration, embedded_metadata, assignment: BinAssignment) -> str:
    if assignment.resolved:
        return "no action needed - resolved automatically"

    if arbitration.decision == Decision.ESCALATE:
        if not embedded_metadata.batch_code:
            return "batch code unreadable - re-scan the item, or manually key the code from the physical label"
        return (
            "route to supervisor for manual batch verification - neither the scan nor the "
            "system record is trustworthy enough to act on alone"
        )

    if arbitration.decision == Decision.TRUST_SOR:
        return (
            "system record is ambiguous - physically check the expiry printed on the item "
            "against the listed candidate bins to break the tie"
        )

    # TRUST_EMBEDDED_METADATA but still unresolved
    if not embedded_metadata.batch_code:
        return "batch code unreadable even though the scan was otherwise trusted - manually key the code from the physical label"
    return (
        "scanned batch code has no matching system record - check for an unlogged batch, "
        "or confirm the item wasn't mislabeled, before filing"
    )
