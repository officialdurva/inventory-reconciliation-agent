import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import decision_log, fixtures, precedent_memory, product_risk, warehouse_client as wc
from src.arbiter import arbitrate
from src.embedded_metadata_reader import read_embedded_metadata
from src.models import Decision, EmbeddedMetadataReadResult, SORCandidate, SORQueryResult
from src.naive_baseline import naive_pick
from src.pipeline import process_return


def setup_function(_):
    fixtures.seed_all()
    precedent_memory.reset()
    product_risk.reset()
    decision_log.reset()


def test_case_a_trusts_sor_over_corrupted_embedded_metadata():
    case = fixtures.CASES["A_corrupted_embedded_metadata"]
    trace = process_return("A", case["sku"], case["raw_scan"])
    assert trace["arbitration"].decision == Decision.TRUST_SOR
    assert trace["assignment"].resolved
    assert trace["assignment"].bin_id == "B-A1"


def test_case_b_escalates_with_no_default_bin():
    case = fixtures.CASES["B_ambiguous_conflict"]
    trace = process_return("B", case["sku"], case["raw_scan"])
    assert trace["assignment"].resolved is False
    assert trace["assignment"].batch_id is None
    assert trace["assignment"].bin_id is None


def test_precedent_resolves_repeat_case_without_reescalating():
    case = fixtures.CASES["B_ambiguous_conflict"]
    trace = process_return("B", case["sku"], case["raw_scan"])
    features = precedent_memory.build_feature_vector(
        trace["arbitration"].reliability_embedded_metadata,
        trace["arbitration"].reliability_sor,
        len(trace["sor"].candidates),
        trace["sor"].candidates[0].last_updated_days_ago,
        trace["embedded_metadata"].checksum_valid,
    )
    precedent_memory.record_resolution(
        "B", case["sku"], features, "B-4407-5", "B-C1", fixtures._iso(62), "human-confirmed"
    )

    repeat = fixtures.CASES["B_repeat_same_conflict"]
    trace2 = process_return("B-repeat", repeat["sku"], repeat["raw_scan"])
    assert trace2["assignment"].resolved is True
    assert trace2["assignment"].bin_id == "B-C1"
    assert trace2["precedent_used"] is not None


def test_case_c_agent_disagrees_with_naive_baseline():
    case = fixtures.CASES["C_obvious_choice_is_wrong"]
    trace = process_return("C", case["sku"], case["raw_scan"])
    naive = naive_pick(trace["sor"])
    assert trace["assignment"].bin_id == "B-OLD"
    assert naive.bin_id == "B-FRESH"
    assert naive.bin_id != trace["assignment"].bin_id


def test_case_d_both_fail_escalates_with_no_default():
    case = fixtures.CASES["D_both_fail"]
    trace = process_return("D", case["sku"], case["raw_scan"])
    assert trace["assignment"].resolved is False
    assert trace["assignment"].batch_id is None
    assert trace["assignment"].bin_id is None


def test_decision_is_a_runtime_computation_not_a_hardcoded_branch():
    """Same evidence *shape* as Case A, but small numeric changes flip the outcome -
    proving the branch taken depends on the actual numbers, not a switch on case identity."""
    embedded_metadata = read_embedded_metadata({
        "batch_code_raw": "B-77?2-9",
        "expiry_raw": "2026-12-10",
        "scan_confidence": 0.55,
    })

    stale_sor = SORQueryResult(candidates=[
        SORCandidate(batch_id="B-7712-9", expiry_date=date(2026, 12, 10), bin_id="B-A1",
                     qty=30, last_updated_days_ago=3, match_score=0.5),
    ])
    fresh_result = arbitrate("SKU-1001", embedded_metadata, stale_sor)
    assert fresh_result.decision == Decision.TRUST_SOR

    very_stale_sor = SORQueryResult(candidates=[
        SORCandidate(batch_id="B-7712-9", expiry_date=date(2026, 12, 10), bin_id="B-A1",
                     qty=30, last_updated_days_ago=400, match_score=0.5),
    ])
    stale_result = arbitrate("SKU-1001", embedded_metadata, very_stale_sor)
    assert stale_result.decision == Decision.ESCALATE
    assert fresh_result.decision != stale_result.decision


def test_high_risk_product_demands_more_evidence_on_identical_numbers():
    """Same embedded metadata and SOR evidence as the fresh_result case above - the only
    thing that changes is the product's risk profile - and that alone flips
    TRUST_SOR into ESCALATE."""
    embedded_metadata = read_embedded_metadata({
        "batch_code_raw": "B-77?2-9",
        "expiry_raw": "2026-12-10",
        "scan_confidence": 0.55,
    })
    sor = SORQueryResult(candidates=[
        SORCandidate(batch_id="B-7712-9", expiry_date=date(2026, 12, 10), bin_id="B-A1",
                     qty=30, last_updated_days_ago=3, match_score=0.5),
    ])

    baseline = arbitrate("SKU-LOWRISK", embedded_metadata, sor)
    assert baseline.decision == Decision.TRUST_SOR

    product_risk.set_risk("SKU-HIGHRISK", 3.0, "regulated pharmaceutical")
    high_risk = arbitrate("SKU-HIGHRISK", embedded_metadata, sor)
    assert high_risk.decision == Decision.ESCALATE
    assert high_risk.reliability_embedded_metadata == baseline.reliability_embedded_metadata
    assert high_risk.reliability_sor == baseline.reliability_sor


def test_low_risk_product_can_lower_the_bar_on_identical_numbers():
    """A margin too thin to act on at baseline risk becomes decisive once the
    product is marked low-stakes - the multiplier moves the bar in both directions."""
    embedded_metadata = EmbeddedMetadataReadResult(
        raw_code="B-1234-5", batch_code="B-1234-5", expiry_date=date(2026, 12, 1),
        condition_notes="", confidence=0.30, checksum_valid=True, parse_errors=[],
    )
    sor = SORQueryResult(candidates=[
        SORCandidate(batch_id="B-1234-5", expiry_date=date(2026, 12, 1), bin_id="B-X1",
                     qty=10, last_updated_days_ago=0, match_score=0.40),
    ])

    baseline = arbitrate("SKU-BASELINE", embedded_metadata, sor)
    assert baseline.decision == Decision.ESCALATE  # margin=0.10 < baseline threshold 0.15

    product_risk.set_risk("SKU-LOWSTAKES", 0.5, "cheap, non-perishable item")
    low_risk = arbitrate("SKU-LOWSTAKES", embedded_metadata, sor)
    assert low_risk.decision == Decision.TRUST_SOR  # margin=0.10 > scaled threshold 0.075
