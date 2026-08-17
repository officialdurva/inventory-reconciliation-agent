# Inventory Reconciliation Agent

Reconciles partial stock returns when the physical embedded metadata on the
returned item (batch code, expiry date, condition notes) conflicts with the
warehouse system of record (SOR). Pure Python, no external services, no API
keys.

## What kind of "agent" this is

No LLM, no learned model, no training data, no embeddings - "agent" here
means a deterministic, rule-based decision system that reasons over
continuous reliability scores at runtime (see below), not a modern
LLM-agent. That's a deliberate choice, not a placeholder for one: a
high-stakes, low-latency, fully-auditable decision like "which bin does
this stock go in" is a good fit for exactly this kind of cheap, reproducible
logic. If a learned or LLM-based component gets added later (e.g. a real
OCR/scanning model, or an LLM writing the `action_hints.py` explanations),
that's a distinct, separable upgrade to one of the two "component" boundaries
(`embedded_metadata_reader.py`, `warehouse_client.py`) - not a rewrite of the
decision core in `arbiter.py`/`bin_resolver.py`.

## Why it's structured this way

The core problem is evidence fusion under uncertainty with a reject option,
not a lookup table: two independently-failing sources (an embedded metadata scan and a
SOR query) each estimate the same latent fact - which batch this item really
is - and the agent has to decide, per return, which to trust, or admit
neither is trustworthy enough to act on.

Two sequential, runtime decisions per return:

1. **Arbitration** (`src/arbiter.py`) - trust embedded metadata, trust SOR, or escalate.
   Driven by continuous reliability scores (`src/reliability_scoring.py`),
   not a switch on "case type". The same code produces different decisions
   for different numbers - see
   `tests/test_pipeline.py::test_decision_is_a_runtime_computation_not_a_hardcoded_branch`.
2. **Bin resolution** (`src/bin_resolver.py`) - given decision 1, which
   specific batch/bin. This can independently fail even when decision 1
   succeeded (e.g. embedded metadata trusted, but no SOR record actually confirms it)
   - there is no default bin anywhere in this path.

A third piece, **precedent memory** (`src/precedent_memory.py`), sits outside
both decisions: when a return can't be resolved by evidence alone, it's
escalated to a human - and once that human's resolution is recorded, a later
return with a near-identical evidence signature (cosine similarity over a
small feature vector, same SKU) reuses it instead of re-escalating from
zero. This is deliberately conservative: it never fires on a case that
hasn't been confirmed by a person at least once, and it's scoped per-SKU so
a resolution never silently jumps to a different product.

## The two failure modes

- **Corrupted embedded metadata** (`src/embedded_metadata_reader.py`) - unreadable batch code,
  checksum mismatch, unparseable date. Handled in Case A.
- **Internally consistent but conflicting** - the embedded metadata scan is clean
  (valid checksum, no parse errors) but doesn't match a SOR record cleanly.
  Handled in Case B (escalates) and Case C (resolves correctly against the
  "obvious"-but-wrong answer).
- **Both at once** - Case D. Neither source clears the confidence floor;
  arbitration escalates directly, and no precedent exists yet, so it stays
  escalated. No fallback to a default bin.

## Per-product risk (`src/product_risk.py`)

`ESCALATE_MARGIN_THRESHOLD` and `MIN_ABSOLUTE_CONFIDENCE` are a single global
bar by default - but a wrong assignment doesn't cost the same for every
product. A regulated or perishable item being misfiled is a real problem; a
cheap, non-perishable one is a shrug. `product_risk.py` lets a SKU carry a
risk multiplier that scales both thresholds in `arbiter.py` up or down, so
the *same* evidence can land on different sides of the decision depending on
what's actually at stake. `run_demo.py`'s Case A is replayed unchanged except
for a risk flag on the SKU, and the decision flips from `TRUST_SOR` to
`ESCALATE` - see `tests/test_pipeline.py::test_high_risk_product_demands_more_evidence_on_identical_numbers`
and `::test_low_risk_product_can_lower_the_bar_on_identical_numbers` for both
directions. The multipliers themselves are still placeholders (`3.0`, `0.5`)
- in production these would come from real cost data, same caveat as the
base thresholds below.

## Proving the harm is real (Case C)

Case C: a batch id got reused across two SOR records - one recently
"active" and fresh-looking, one old and near the item's actual expiry. A
naive implementation (`src/naive_baseline.py`) just grabs whichever record
was most recently touched - the fresh-looking one. The agent instead
cross-checks the physical item's own printed expiry against both candidates
and correctly picks the old, near-expiry one.

`run_demo.py` feeds both outcomes into a small FEFO (first-expire-first-out)
shipment simulator (`src/forecast.py`) - the same allocation logic a real
warehouse uses, which only ever sees the *label* a reconciliation step
assigned, never physical truth. Result:

- Naive assignment: the mislabeled unit ships as part of the "fresh" batch
  between days 4-24, well past its true expiry on day 16 - **an expired
  unit gets shipped to a customer, undetected.**
- Agent's assignment: the unit is correctly prioritized and fully shipped
  by day 4, three days before it would actually expire.

This is the concrete, measurable divergence the task asks for - not an
assertion that the decision "would matter downstream."

## Running it

```
python run_demo.py       # full narrated walkthrough of all four cases
python -m pytest tests   # automated assertions (install pytest first: pip install pytest)
```

## What a real deployment would change

- `embedded_metadata_reader.py` and `warehouse_client.py` would call real
  OCR/scanning hardware and the actual SOR API instead of fixtures.
- `ESCALATE_MARGIN_THRESHOLD` and `MIN_ABSOLUTE_CONFIDENCE` in
  `reliability_scoring.py` are placeholders; in production they should be
  derived from an actual cost ratio (cost of a wrong bin assignment vs. cost
  of a manual review), not picked by feel.
- `precedent_memory.py` uses a flat JSON file and a hand-rolled cosine
  similarity for clarity; at scale this is a vector-store lookup problem.
