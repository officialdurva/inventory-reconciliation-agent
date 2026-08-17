"""Boundary-robustness checks.

The two components that read genuinely external input - a scan payload, a
warehouse record - must never crash on malformed input. They must report it
as evidence the arbiter can reason about (usually driving straight to
ESCALATE), the same as any other kind of corruption this project models.
This is the exact boundary the whole project is about being robust to, so
it's the one place a crash would be most self-defeating.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import decision_log, decision_log_report, fixtures, precedent_memory, product_risk, warehouse_client as wc
from src.embedded_metadata_reader import read_embedded_metadata
from src.models import Decision
from src.pipeline import process_return
from src.reliability_scoring import score_embedded_metadata_reliability


def setup_function(_):
    fixtures.seed_all()
    precedent_memory.reset()
    product_risk.reset()
    decision_log.reset()


def test_empty_scan_payload_does_not_crash():
    result = read_embedded_metadata({})
    assert result.batch_code is None
    assert result.expiry_date is None
    assert "no batch code field in scan payload" in result.parse_errors
    assert any("unparseable expiry date" in e for e in result.parse_errors)


def test_none_scan_payload_does_not_crash():
    result = read_embedded_metadata(None)
    assert result.batch_code is None
    assert result.raw_code == "<missing>"


def test_non_string_batch_code_does_not_crash():
    result = read_embedded_metadata({"batch_code_raw": 12345, "expiry_raw": "2026-12-01"})
    assert result.batch_code is None
    assert any("not a string" in e for e in result.parse_errors)


def test_non_numeric_scan_confidence_does_not_crash():
    result = read_embedded_metadata({
        "batch_code_raw": "B-7712-9", "expiry_raw": "2026-12-01", "scan_confidence": "high",
    })
    assert result.confidence == 0.0
    assert any("non-numeric scan_confidence" in e for e in result.parse_errors)


def test_missing_scan_fields_escalates_when_no_sor_evidence_either():
    """The pipeline's job is to turn corrupted input into a decision, never a crash."""
    trace = process_return("MALFORMED", "SKU-COMPLETELY-UNKNOWN", {})
    assert trace["arbitration"].decision == Decision.ESCALATE
    assert trace["assignment"].resolved is False


def test_malformed_sor_record_is_skipped_not_fatal():
    wc.seed("SKU-BADREC", [{"batch_id": "B-1234-5"}])  # missing expiry_date/bin_id/qty/last_updated_days_ago
    metadata = read_embedded_metadata({"batch_code_raw": "B-1234-5", "expiry_raw": "2026-12-01"})
    result = wc.query_sor("SKU-BADREC", metadata)
    assert result.candidates == []
    assert any("skipped malformed SOR record" in e for e in result.query_errors)


# --- explicit-null regression tests -----------------------------------------
# .get(key, default) only falls back when the key is ABSENT. A payload with
# an explicit null for the key (a very real shape for a real JSON API) still
# returns None, silently bypassing the default. These four bugs were found by
# a review pass and are guarded against separately from the missing-key tests
# above, which don't exercise this path at all.

def test_explicit_null_condition_notes_does_not_crash_the_scorer():
    metadata = read_embedded_metadata({
        "batch_code_raw": "B-7712-9", "expiry_raw": "2026-12-01", "condition_notes": None,
    })
    assert metadata.condition_notes == ""
    score_embedded_metadata_reliability(metadata)  # must not raise


def test_precedent_record_with_null_features_is_skipped_not_fatal():
    with open(precedent_memory.STORE_PATH, "w", encoding="utf-8") as f:
        json.dump([{
            "sku": "SKU-NULLFEAT", "features": None, "case_id": "c1",
            "resolution_batch_id": "B-1", "resolution_bin_id": "BIN-1",
            "resolution_expiry": "2026-12-01", "note": "x",
        }], f)
    precedent, similarity = precedent_memory.find_similar("SKU-NULLFEAT", [0.5, 0.5, 0.5, 0.5, 0.5])
    assert precedent is None
    assert similarity == 0.0


def test_precedent_record_with_null_resolution_expiry_does_not_crash_auto_apply():
    with open(precedent_memory.STORE_PATH, "w", encoding="utf-8") as f:
        json.dump([{
            "sku": "SKU-4402", "features": [0.9, 0.1, 0.4, 0.03, 1.0], "case_id": "c1",
            "resolution_batch_id": "B-4407-5", "resolution_bin_id": "B-C1",
            "resolution_expiry": None, "note": "x", "ruleset_version": decision_log.RULESET_VERSION,
        }], f)
    case = fixtures.CASES["B_ambiguous_conflict"]
    trace = process_return("B", case["sku"], case["raw_scan"])  # must not raise
    assert trace["precedent_used"] is None  # malformed precedent should not have been usable


def test_decision_log_with_null_reliability_score_does_not_crash_report():
    with open(decision_log.LOG_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "decision": "ESCALATE", "resolved": False,
            "reliability_embedded_metadata": None, "reliability_sor": 0.2,
        }) + "\n")
    report = decision_log_report.summarize()  # must not raise
    assert report["total"] == 1
