"""The 'obvious' approach a naive implementation would take, kept separate on
purpose so its output can be directly compared against the agent's.

No cross-checking against physical evidence at all: just grab whichever SOR
record for this batch id was most recently touched, on the assumption that
the most recently active record must be the right one. That assumption is
exactly what breaks in Case C.
"""
from __future__ import annotations


def naive_pick(sor):
    return min(sor.candidates, key=lambda c: c.last_updated_days_ago)
