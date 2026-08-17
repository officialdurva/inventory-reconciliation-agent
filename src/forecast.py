"""Downstream harm proof: a small FEFO (first-expire-first-out) allocator.

Real warehouses ship the earliest-labeled-expiry stock first. That allocator
only ever sees the LABEL the reconciliation step assigned, never physical
truth - so a wrong batch assignment doesn't cause an immediate error, it
causes silently-wrong shipment ordering that surfaces later as expired stock
going out the door. This module makes that surfacing concrete and measurable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShipmentEvent:
    day: int
    bin_name: str
    units_shipped: int
    remaining_in_bin: int


def simulate_fefo(bins: list, daily_demand: int, horizon_days: int):
    """bins: list of {name, qty, labeled_expiry_day}. Ships earliest-labeled-expiry first."""
    pool = sorted(bins, key=lambda b: b["labeled_expiry_day"])
    remaining = {b["name"]: b["qty"] for b in pool}
    timeline = []
    for day in range(1, horizon_days + 1):
        to_ship = daily_demand
        for b in pool:
            if to_ship <= 0:
                break
            avail = remaining[b["name"]]
            if avail <= 0:
                continue
            take = min(avail, to_ship)
            remaining[b["name"]] -= take
            to_ship -= take
            timeline.append(ShipmentEvent(day, b["name"], take, remaining[b["name"]]))
        if to_ship > 0:
            timeline.append(ShipmentEvent(day, "STOCKOUT", to_ship, 0))
    return timeline, remaining


def expired_shipment_exposure(timeline, bin_name: str, true_expiry_day: int) -> dict:
    """Units shipped from bin_name on/after the item's TRUE expiry day - i.e. shipped
    past best-before because the system's label said it was still fine."""
    late_units = sum(e.units_shipped for e in timeline if e.bin_name == bin_name and e.day >= true_expiry_day)
    ship_days = [e.day for e in timeline if e.bin_name == bin_name and e.units_shipped > 0]
    return {
        "units_shipped_on_or_after_true_expiry": late_units,
        "shipment_day_range": (min(ship_days), max(ship_days)) if ship_days else None,
    }


def bin_exhaustion_day(timeline, bin_name: str):
    """First day this bin's remaining quantity hits zero - the day a stock-out
    would be predicted for this specific batch/bin. Forecast-analyst review:
    the expiry-shipment metric above proves one kind of harm (expired stock
    goes out); this proves the other kind the original task spec named
    (incorrect stock-out predictions) - a mislabeled return means the
    correctly-labeled bin never gets credited with it, so its own tracked
    quantity runs out sooner than physical reality, even though nothing
    actually shipped wrong yet."""
    depleted_days = [e.day for e in timeline if e.bin_name == bin_name and e.remaining_in_bin == 0]
    return min(depleted_days) if depleted_days else None
