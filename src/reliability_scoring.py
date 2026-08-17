"""Turns each raw evidence source into a 0-1 reliability score.

This is the part that must NOT collapse into a hardcoded if/else: the score
is a continuous function of several independent signals, so two inputs that
look superficially similar (e.g. same case "type") can land on different
sides of a decision depending on the exact numbers - see
tests/test_pipeline.py::test_decision_is_a_runtime_computation_not_a_hardcoded_branch
for a demonstration.

All structural-correctness penalties (checksum, parse errors, physical
condition) are applied exactly once, here - not in embedded_metadata_reader.py.
That module only reports what it saw (raw scan confidence plus the individual
signals); this module is the single place that turns those signals into a
trust score, so the same evidence never gets discounted twice through two
different code paths.
"""
from __future__ import annotations

# How fast an un-touched SOR record decays in trustworthiness (days for reliability to halve).
# Warehouse ops review: a record only gets touched on receipt or ship, so
# stock that's simply sitting untouched for 60-90 days is normal, not
# suspicious - the old 45-day half-life was distrusting perfectly good
# slow-moving stock. 90 days matches a realistic touch cadence better.
SOR_STALENESS_HALF_LIFE_DAYS = 90

# Condition-note keywords that indicate physical damage: a label that's torn
# or soaked is less trustworthy evidence even on a scan that happened to
# parse cleanly this time. Keyword-based on purpose - this is a disclosed
# heuristic, not an NLP model, and each hit compounds like the other penalties.
# Warehouse ops review: returns-desk clerks actually write "wet"/"crushed"/
# "ripped"/"stained"/"dented" far more often than "soaked" - expanded to match
# the vocabulary condition_notes actually contains in practice.
DAMAGE_KEYWORDS = (
    "damp", "torn", "illegible", "soaked", "damaged", "faded", "smudged",
    "wet", "crushed", "ripped", "stained", "dented", "moldy",
)
DAMAGE_KEYWORD_PENALTY = 0.85  # multiplier applied once per distinct keyword found


def _condition_penalty(condition_notes: str) -> float:
    hits = sum(1 for kw in DAMAGE_KEYWORDS if kw in condition_notes.lower())
    return DAMAGE_KEYWORD_PENALTY ** hits


# --- Threshold derivation (Bayes-risk), replacing bare unexplained constants ---
#
# A reliability score is treated as an (uncalibrated) proxy for P(this source
# is correct). Acting on a source is only worth it if the expected cost of
# being wrong is no worse than the expected cost of escalating to a human:
#     (1 - r) * cost_wrong_assignment <= cost_review
#     r >= 1 - cost_review / cost_wrong_assignment
#
# The cost figures below are still placeholders - no real cost data behind
# them yet, same caveat as before (see README) - but the threshold is now a
# documented, auditable function of that assumption instead of a bare magic
# number, and it saturates on its own as cost_wrong_assignment grows, so no
# separate ceiling constant is needed to keep it inside [0, 1].
DEFAULT_COST_WRONG_ASSIGNMENT = 100.0  # expected $ cost of shipping/filing under the wrong batch
DEFAULT_COST_MANUAL_REVIEW = 65.0      # expected $ cost of a human resolving one escalated case
DEFAULT_COST_MARGIN_REVIEW = 85.0      # expected $ cost of reviewing a genuinely-tied call


def bayes_risk_threshold(cost_wrong_assignment: float, cost_review: float) -> float:
    """Minimum reliability needed to act instead of escalating, given these costs."""
    if cost_wrong_assignment <= 0:
        return 1.0
    return max(0.0, min(1.0, 1 - cost_review / cost_wrong_assignment))


# Baseline (risk multiplier = 1.0) values - kept as named constants for
# readability; arbiter.py recomputes these per-SKU via bayes_risk_threshold
# directly so the risk multiplier scales the underlying cost, not a probability.
MIN_ABSOLUTE_CONFIDENCE = bayes_risk_threshold(DEFAULT_COST_WRONG_ASSIGNMENT, DEFAULT_COST_MANUAL_REVIEW)
ESCALATE_MARGIN_THRESHOLD = bayes_risk_threshold(DEFAULT_COST_WRONG_ASSIGNMENT, DEFAULT_COST_MARGIN_REVIEW)


def score_embedded_metadata_reliability(embedded_metadata) -> float:
    score = embedded_metadata.confidence
    if not embedded_metadata.checksum_valid:
        score *= 0.35
    score *= 0.7 ** len(embedded_metadata.parse_errors)
    score *= _condition_penalty(embedded_metadata.condition_notes)
    return max(0.0, min(1.0, score))


def score_sor_reliability(sor):
    """Returns (reliability, human-readable detail string)."""
    if not sor.candidates:
        return 0.0, "no matching SOR record for this SKU"

    top = sor.candidates[0]
    reliability = top.match_score

    if len(sor.candidates) > 1:
        second = sor.candidates[1]
        gap = top.match_score - second.match_score
        # margin between best and second-best candidate (same idea as margin-based
        # confidence in active learning): a wide gap means the top match is clearly
        # distinguishable, a near-zero gap means the sources are genuinely tied.
        margin_multiplier = max(0.0, min(1.0, gap / max(top.match_score, 1e-6)))
        reliability *= margin_multiplier
        detail = (
            f"ambiguity check: {len(sor.candidates)} candidates, "
            f"top/second-best match margin={gap:.2f}"
        )
    else:
        detail = "single unambiguous candidate"

    decay = 0.5 ** (top.last_updated_days_ago / SOR_STALENESS_HALF_LIFE_DAYS)
    reliability *= decay
    detail += f"; staleness decay={decay:.2f} (record {top.last_updated_days_ago}d old)"

    return max(0.0, min(1.0, reliability)), detail
