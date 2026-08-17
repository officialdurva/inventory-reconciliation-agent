"""Runs all four fixture cases through the agent and prints a plain-language trace.

This is the script to run on camera for the video: it shows, in order,
- Case A: the scanned label is corrupted -> falls back to a clean database record
- Case B: the scan looks fine but doesn't match the database -> escalates
        -> a human resolution is recorded
        -> a near-identical repeat case reuses that resolution instead of re-escalating
- Case C: the "obvious choice is wrong" case, with a naive-baseline comparison
          fed into a downstream shipment forecast to prove the harm is real
- Case D: both sources fail at once -> escalates, no default bin assigned

Output is deliberately plain-language (no internal scoring jargon) since this
is meant to be read on camera. The full technical reasoning (arb.reasoning,
asg.reasoning) is still available on every trace object for anyone who wants
the underlying math - see tests/test_pipeline.py.
"""
from __future__ import annotations

from src import decision_log, fixtures, precedent_memory, product_risk
from src.forecast import bin_exhaustion_day, expired_shipment_exposure, simulate_fefo
from src.models import Decision
from src.naive_baseline import naive_pick
from src.pipeline import process_return

WIDTH = 78

DECISION_WORDS = {
    Decision.TRUST_SOR: "Trust the warehouse database",
    Decision.TRUST_EMBEDDED_METADATA: "Trust the scanned label",
    Decision.ESCALATE: "Not confident enough either way - send to a person",
}


def _banner(title: str) -> None:
    print()
    print("=" * WIDTH)
    print(title)
    print("=" * WIDTH)


def _section(title: str) -> None:
    print()
    prefix = f"-- {title} "
    print(prefix.rstrip() if len(prefix) >= WIDTH else prefix + "-" * (WIDTH - len(prefix)))


def _confidence_words(score: float) -> str:
    if score >= 0.8:
        return "very confident"
    if score >= 0.5:
        return "somewhat confident"
    if score >= 0.35:
        return "not very confident"
    return "not confident at all"


def _print_candidates(candidates) -> None:
    if not candidates:
        print("    (no matching records)")
        return
    for c in candidates:
        print(
            f"    - batch {c.batch_id:<10} bin {c.bin_id:<8} expiry {c.expiry_date}  "
            f"(last touched {c.last_updated_days_ago} days ago)"
        )


def _print_trace(label, trace):
    _banner(label)
    md = trace["embedded_metadata"]
    sor = trace["sor"]
    arb = trace["arbitration"]
    asg = trace["assignment"]

    print("  WHAT WAS SCANNED OFF THE ITEM")
    if md.batch_code:
        print(f"    batch code: {md.batch_code}  (read cleanly)")
    else:
        print(f"    batch code could not be read clearly (the scanner read: {md.raw_code!r})")
    if md.expiry_date:
        print(f"    expiry printed on the item: {md.expiry_date}")
    else:
        print("    expiry date could not be read")

    print()
    print("  WHAT THE WAREHOUSE DATABASE SHOWS")
    _print_candidates(sor.candidates)

    print()
    print("  HOW MUCH TO TRUST EACH SOURCE")
    print(f"    the scanned label:      {_confidence_words(arb.reliability_embedded_metadata):<20} "
          f"({arb.reliability_embedded_metadata:.0%})")
    print(f"    the warehouse database: {_confidence_words(arb.reliability_sor):<20} "
          f"({arb.reliability_sor:.0%})")
    if arb.risk_multiplier != 1.0:
        print(f"    note: this item is flagged higher-risk ({arb.risk_reason}),")
        print("          so the agent demands stronger evidence before acting alone")

    print()
    print(f"  DECISION: {DECISION_WORDS[arb.decision]}")

    print()
    if asg.resolved:
        print(f"  RESULT: stock goes to bin {asg.bin_id}  (batch {asg.batch_id})")
    else:
        print("  RESULT: could not confidently assign a bin - sent to a person for manual review")
        print(f"    next step: {trace['action_hint']}")

    if trace["precedent_used"]:
        _, sim = trace["precedent_used"]
        print()
        print(f"  this exact kind of case happened before and a person already resolved it")
        print(f"  ({sim:.0%} match to that earlier case) - reusing that answer instead of asking again")

    return trace


def main():
    fixtures.seed_all()
    precedent_memory.reset()
    product_risk.reset()
    decision_log.reset()

    # --- Case A ---
    case = fixtures.CASES["A_corrupted_embedded_metadata"]
    trace = process_return("A", case["sku"], case["raw_scan"])
    _print_trace("CASE A - the scanned label is damaged, but the database is clean", trace)
    assert trace["arbitration"].decision.value == case["expected_decision"], "Case A did not trust SOR as expected"

    _section("now mark this same item as high-risk (e.g. a regulated medicine) - same evidence, nothing else changes")
    product_risk.set_risk("SKU-1001", 3.0, "regulated pharmaceutical - misassignment risk is high")
    trace_highrisk = process_return("A-highrisk", case["sku"], case["raw_scan"])
    _print_trace("CASE A REVISITED - same evidence, but now it's a high-risk item", trace_highrisk)
    assert trace_highrisk["arbitration"].decision.value == "ESCALATE", \
        "a high-risk product should demand more evidence before acting on the same numbers"
    product_risk.reset()

    # --- Case B: escalate, then teach it via precedent ---
    case = fixtures.CASES["B_ambiguous_conflict"]
    trace_b = process_return("B", case["sku"], case["raw_scan"])
    _print_trace("CASE B - the scan looks fine, but it doesn't match the database", trace_b)
    assert trace_b["assignment"].resolved == case["expected_resolved"], "Case B should have escalated"

    _section("a person resolves the case above: confirmed batch B-4407-5, bin B-C1 (the printed expiry was a misprint)")
    features = precedent_memory.build_feature_vector(
        trace_b["arbitration"].reliability_embedded_metadata,
        trace_b["arbitration"].reliability_sor,
        len(trace_b["sor"].candidates),
        trace_b["sor"].candidates[0].last_updated_days_ago,
        trace_b["embedded_metadata"].checksum_valid,
    )
    precedent_memory.record_resolution(
        case_id="B",
        sku=case["sku"],
        features=features,
        resolution_batch_id="B-4407-5",
        resolution_bin_id="B-C1",
        resolution_expiry=fixtures._iso(62),
        note="physical inspection confirmed batch B-4407-5; printed expiry on the item was a misprint",
    )

    case = fixtures.CASES["B_repeat_same_conflict"]
    trace_b2 = process_return("B-repeat", case["sku"], case["raw_scan"])
    _print_trace("CASE B (REPEAT) - the same kind of return shows up again later", trace_b2)
    assert trace_b2["assignment"].resolved, "the repeat case should have been auto-resolved via precedent"
    assert trace_b2["precedent_used"] is not None, "expected the precedent path to fire"

    # --- Case C: obvious choice is wrong, with downstream harm proof ---
    case = fixtures.CASES["C_obvious_choice_is_wrong"]
    trace_c = process_return("C", case["sku"], case["raw_scan"])
    _print_trace("CASE C - the obvious choice is wrong", trace_c)
    naive = naive_pick(trace_c["sor"])
    print()
    print("  A simpler system that just picks whichever record was touched most recently would choose:")
    print(f"    batch {naive.batch_id}, bin {naive.bin_id}, expiry {naive.expiry_date}")
    assert trace_c["assignment"].bin_id == case["expected_bin"], "agent should have picked the near-expiry bin"
    assert naive.bin_id != trace_c["assignment"].bin_id, "naive baseline should disagree with the agent here"

    true_expiry_day = case["true_expiry_day"]
    # Forecast-analyst review: a higher, more "realistic" demand rate was
    # considered here, but at coarse day-level granularity a high demand rate
    # rounds a 1-unit labeling error away entirely - both bins can exhaust on
    # the same day even though one is short a unit. Kept deliberately low so
    # the stock-out-prediction proof below stays visible; a real deployment
    # tracking at finer time granularity wouldn't need this trade-off.
    daily_demand = 2
    horizon = 40

    agent_bins = [
        {"name": "B-FRESH", "qty": 40, "labeled_expiry_day": 291},
        {"name": "B-OLD", "qty": 7, "labeled_expiry_day": true_expiry_day},  # +1 returned unit, correctly labeled
    ]
    naive_bins = [
        {"name": "B-FRESH", "qty": 41, "labeled_expiry_day": 291},  # +1 returned unit, WRONGLY labeled as fresh
        {"name": "B-OLD", "qty": 6, "labeled_expiry_day": true_expiry_day},
    ]

    agent_timeline, _ = simulate_fefo(agent_bins, daily_demand, horizon)
    naive_timeline, _ = simulate_fefo(naive_bins, daily_demand, horizon)

    agent_exposure = expired_shipment_exposure(agent_timeline, "B-OLD", true_expiry_day)
    naive_exposure = expired_shipment_exposure(naive_timeline, "B-FRESH", true_expiry_day)

    _section("what happens next if we ship from this stock (earliest-expiring stock ships first)")
    print(f"  this returned unit actually expires on day {true_expiry_day}")

    print()
    print("  IF WE PICK THE WRONG BIN (what the simpler system would do)")
    print(f"    stock ships out on days {naive_exposure['shipment_day_range']}")
    print(f"    {naive_exposure['units_shipped_on_or_after_true_expiry']} of those units ship on or "
          f"after the day they actually expire")
    print("    -> an expired item goes out to a customer, and nobody notices")
    assert naive_exposure["units_shipped_on_or_after_true_expiry"] > 0, "naive path should demonstrate real harm"

    print()
    print("  IF WE PICK THE RIGHT BIN (what this agent does)")
    print(f"    stock ships out on days {agent_exposure['shipment_day_range']}")
    print(f"    {agent_exposure['units_shipped_on_or_after_true_expiry']} of those units ship on or "
          f"after the day they actually expire")
    assert agent_exposure["units_shipped_on_or_after_true_expiry"] == 0, "agent path should avoid the harm entirely"

    print()
    print("  THERE'S A SECOND PROBLEM TOO: A FALSE 'OUT OF STOCK' WARNING")
    naive_oldbin_exhaustion = bin_exhaustion_day(naive_timeline, "B-OLD")
    agent_oldbin_exhaustion = bin_exhaustion_day(agent_timeline, "B-OLD")
    print(f"    pick the wrong bin -> the system thinks this bin runs out on day {naive_oldbin_exhaustion} "
          f"(it isn't actually empty yet)")
    print(f"    pick the right bin -> the system correctly predicts day {agent_oldbin_exhaustion}")
    assert agent_oldbin_exhaustion is None or naive_oldbin_exhaustion is None or (
        agent_oldbin_exhaustion >= naive_oldbin_exhaustion
    ), "naive mislabeling should never make the stock-out prediction later than the agent's"
    assert naive_oldbin_exhaustion != agent_oldbin_exhaustion, "the two should visibly disagree here"

    # --- Case D: both components fail, no default fallback ---
    case = fixtures.CASES["D_both_fail"]
    trace_d = process_return("D", case["sku"], case["raw_scan"])
    _print_trace("CASE D - both the scan and the database are unreliable", trace_d)
    assert trace_d["assignment"].resolved == case["expected_resolved"], "Case D should have escalated"
    assert trace_d["assignment"].batch_id is None and trace_d["assignment"].bin_id is None, \
        "Case D must not fall back to any default bin"

    _banner("ALL CASES BEHAVED AS EXPECTED")


if __name__ == "__main__":
    main()
