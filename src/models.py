from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    TRUST_EMBEDDED_METADATA = "TRUST_EMBEDDED_METADATA"
    TRUST_SOR = "TRUST_SOR"
    ESCALATE = "ESCALATE"


@dataclass
class EmbeddedMetadataReadResult:
    raw_code: str
    batch_code: Optional[str]
    expiry_date: Optional[date]
    condition_notes: str
    confidence: float
    checksum_valid: bool
    parse_errors: list = field(default_factory=list)


@dataclass
class SORCandidate:
    batch_id: str
    expiry_date: date
    bin_id: str
    qty: int
    last_updated_days_ago: int
    match_score: float


@dataclass
class SORQueryResult:
    candidates: list = field(default_factory=list)
    query_errors: list = field(default_factory=list)


@dataclass
class ArbitrationResult:
    decision: Decision
    reliability_embedded_metadata: float
    reliability_sor: float
    margin: float
    reasoning: str
    # Compliance review: risk context needs to be a structured field, not just
    # buried inside the reasoning string, so an auditor can filter the log for
    # "high-risk SKU that got auto-resolved" without parsing free text.
    risk_multiplier: float = 1.0
    risk_reason: str = "no risk profile set - using default caution level"


@dataclass
class BinAssignment:
    resolved: bool
    batch_id: Optional[str]
    bin_id: Optional[str]
    expiry_date: Optional[date]
    reasoning: str


@dataclass
class Precedent:
    case_id: str
    features: list
    sku: str
    resolution_batch_id: str
    resolution_bin_id: str
    resolution_expiry: str
    note: str
    # Which decision_log.RULESET_VERSION was active when this was recorded -
    # a precedent confirmed under one set of cost thresholds shouldn't be
    # silently reused after those thresholds change (see pipeline.py).
    ruleset_version: str = ""
