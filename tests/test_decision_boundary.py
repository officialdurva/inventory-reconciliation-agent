"""Property-based sensitivity checks over the arbitration decision boundary.

tests/test_pipeline.py proves specific behaviors at hand-picked example
points. This file instead sweeps randomized inputs to check invariants that
should hold everywhere, not just at the chosen fixtures - a Monte Carlo
argument, not a confusion matrix, since there is no ground-truth label for a
randomly generated synthetic case (unlike the fixtures, which were built
around a known-correct answer).
"""
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import product_risk
from src.arbiter import arbitrate
from src.models import Decision, EmbeddedMetadataReadResult, SORCandidate, SORQueryResult

random.seed(0)
N_TRIALS = 200


def setup_function(_):
    product_risk.reset()


def _random_metadata():
    return EmbeddedMetadataReadResult(
        raw_code="B-1234-5",
        batch_code="B-1234-5" if random.random() > 0.1 else None,
        expiry_date=date(2026, 12, 1),
        condition_notes=random.choice(["", "sealed, good condition", "box damp, torn label"]),
        confidence=random.uniform(0, 1),
        checksum_valid=random.random() > 0.3,
        parse_errors=["x"] * random.randint(0, 3),
    )


def _random_sor():
    n = random.randint(0, 3)
    candidates = [
        SORCandidate(
            batch_id="B-1234-5", expiry_date=date(2026, 12, 1), bin_id=f"BIN-{i}",
            qty=10, last_updated_days_ago=random.randint(0, 400), match_score=random.uniform(0, 1),
        )
        for i in range(n)
    ]
    candidates.sort(key=lambda c: c.match_score, reverse=True)
    return SORQueryResult(candidates=candidates)


def test_decision_is_deterministic():
    """Same inputs must always produce the same decision - no hidden state/randomness."""
    for _ in range(N_TRIALS):
        metadata = _random_metadata()
        sor = _random_sor()
        first = arbitrate("SKU-RAND", metadata, sor)
        second = arbitrate("SKU-RAND", metadata, sor)
        assert first.decision == second.decision
        assert first.margin == second.margin


def test_higher_risk_multiplier_never_makes_escalation_less_likely():
    """Raising a SKU's risk multiplier scales up the cost of a wrong assignment,
    which can only raise the evidence bar, never lower it, for identical evidence.
    So if baseline evidence was already too weak to act on, a higher-risk
    version of the same evidence must still escalate."""
    for _ in range(N_TRIALS):
        metadata = _random_metadata()
        sor = _random_sor()
        baseline = arbitrate("SKU-BASE", metadata, sor)

        product_risk.set_risk("SKU-HIGH", random.uniform(1.0, 5.0), "test")
        high = arbitrate("SKU-HIGH", metadata, sor)
        product_risk.reset()

        if baseline.decision == Decision.ESCALATE:
            assert high.decision == Decision.ESCALATE


def test_trust_embedded_metadata_only_when_it_actually_leads():
    """Whenever the decision is to trust embedded metadata, its reliability score
    must be strictly greater than the SOR's - the arbiter should never claim to
    trust the losing side."""
    for _ in range(N_TRIALS):
        metadata = _random_metadata()
        sor = _random_sor()
        result = arbitrate("SKU-RAND", metadata, sor)
        if result.decision == Decision.TRUST_EMBEDDED_METADATA:
            assert result.reliability_embedded_metadata > result.reliability_sor
        elif result.decision == Decision.TRUST_SOR:
            assert result.reliability_sor > result.reliability_embedded_metadata
