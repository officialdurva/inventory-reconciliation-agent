"""Per-product risk profiles: how cautious the agent should be, given what a
misassignment on THIS product would actually cost.

Not every wrong bin assignment is equally bad. Filing a cheap, non-perishable
item under the wrong batch is a shrug. Filing a regulated or perishable item
under the wrong batch can mean a customer receiving expired medication. A
single global confidence bar treats both the same - this module scales how
much evidence the agent demands before acting, per product, instead.
"""
from __future__ import annotations

DEFAULT_RISK_MULTIPLIER = 1.0

# sku -> {"multiplier": float, "reason": str}
# multiplier > 1.0 = more cautious (demand more evidence before acting alone)
# multiplier < 1.0 = less cautious (a wrong guess here is cheap; don't make a
#                     human review something low-stakes as readily)
RISK_PROFILES = {}


def set_risk(sku: str, multiplier: float, reason: str = "") -> None:
    RISK_PROFILES[sku] = {"multiplier": multiplier, "reason": reason}


def reset() -> None:
    RISK_PROFILES.clear()


def get_risk(sku: str):
    profile = RISK_PROFILES.get(sku)
    if profile is None:
        return DEFAULT_RISK_MULTIPLIER, "no risk profile set - using default caution level"
    return profile["multiplier"], profile["reason"]
