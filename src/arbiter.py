"""Decision #1: trust the physical embedded metadata, trust the SOR, or escalate.

This is a runtime choice between genuinely competing strategies - the branch
taken falls out of the reliability scores computed for THIS specific case,
not a lookup on which "case type" this is.
"""
from __future__ import annotations

from . import product_risk
from .models import ArbitrationResult, Decision
from .reliability_scoring import (
    DEFAULT_COST_MANUAL_REVIEW,
    DEFAULT_COST_MARGIN_REVIEW,
    DEFAULT_COST_WRONG_ASSIGNMENT,
    bayes_risk_threshold,
    score_embedded_metadata_reliability,
    score_sor_reliability,
)


def arbitrate(sku, embedded_metadata, sor) -> ArbitrationResult:
    rel_embedded_meta = score_embedded_metadata_reliability(embedded_metadata)
    rel_sor, sor_detail = score_sor_reliability(sor)
    margin = abs(rel_embedded_meta - rel_sor)

    risk_multiplier, risk_reason = product_risk.get_risk(sku)
    # The risk multiplier scales the *cost* of a wrong assignment, not the
    # threshold directly - bayes_risk_threshold saturates on its own as that
    # cost grows, so a large multiplier can demand more evidence without
    # ever needing a separate hardcoded ceiling to stay inside [0, 1].
    risk_adjusted_cost_wrong = DEFAULT_COST_WRONG_ASSIGNMENT * risk_multiplier
    effective_min_confidence = bayes_risk_threshold(risk_adjusted_cost_wrong, DEFAULT_COST_MANUAL_REVIEW)
    effective_margin_threshold = bayes_risk_threshold(risk_adjusted_cost_wrong, DEFAULT_COST_MARGIN_REVIEW)
    risk_note = (
        f"risk multiplier={risk_multiplier:.2f} ({risk_reason})"
        if risk_multiplier != product_risk.DEFAULT_RISK_MULTIPLIER
        else "baseline risk"
    )

    too_weak = max(rel_embedded_meta, rel_sor) < effective_min_confidence
    too_close = margin < effective_margin_threshold

    if too_weak or too_close:
        reason = "both sources below confidence floor" if too_weak else "reliability scores too close to call"
        return ArbitrationResult(
            decision=Decision.ESCALATE,
            reliability_embedded_metadata=rel_embedded_meta,
            reliability_sor=rel_sor,
            margin=margin,
            reasoning=(
                f"{reason} (embedded_meta={rel_embedded_meta:.2f}, sor={rel_sor:.2f}, margin={margin:.2f}, "
                f"required floor={effective_min_confidence:.2f}/margin={effective_margin_threshold:.2f}, "
                f"{risk_note}); {sor_detail}"
            ),
            risk_multiplier=risk_multiplier,
            risk_reason=risk_reason,
        )

    decision = Decision.TRUST_EMBEDDED_METADATA if rel_embedded_meta > rel_sor else Decision.TRUST_SOR
    return ArbitrationResult(
        decision=decision,
        reliability_embedded_metadata=rel_embedded_meta,
        reliability_sor=rel_sor,
        margin=margin,
        reasoning=f"{decision.value}: embedded_meta={rel_embedded_meta:.2f} vs sor={rel_sor:.2f} (margin={margin:.2f}, {risk_note}); {sor_detail}",
        risk_multiplier=risk_multiplier,
        risk_reason=risk_reason,
    )
