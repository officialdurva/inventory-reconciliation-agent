"""Simulates the physical-embedded-metadata scanning/OCR component.

Independently failing component #1. Failure modes it can produce:
  - unparseable / garbled batch code (OCR dropped a character)
  - checksum mismatch (code parses but internal check digit is wrong)
  - unparseable expiry date
`confidence` here is only the raw, self-reported scan confidence - structural
problems are reported separately via `checksum_valid` and `parse_errors`, and
never baked into `confidence` itself. reliability_scoring.py is the single
place that turns those signals into a trust penalty; this module only
reports what it saw, it never decides trust/distrust itself.

A missing/malformed field in the scan payload is itself just another failure
mode of this component - a real OCR/scanner integration can return a
payload missing a key, or a wrong type, same as it can return a garbled
code. That must be reported as evidence (usually driving the arbiter toward
ESCALATE), never a crash - this is the boundary the whole project is about
being robust to, so it would be self-defeating to leave it unguarded.
"""
from __future__ import annotations

import re
from datetime import date

from .models import EmbeddedMetadataReadResult

CODE_RE = re.compile(r"^B-(\d{4})-(\d)$")


def read_embedded_metadata(raw_scan: dict) -> EmbeddedMetadataReadResult:
    raw_scan = raw_scan or {}
    parse_errors = []

    raw_code = raw_scan.get("batch_code_raw")
    raw_expiry = raw_scan.get("expiry_raw")
    # .get(key, "") only falls back when the key is absent - a payload with
    # an explicit "condition_notes": null still returns None here, which
    # used to crash reliability_scoring.py's _condition_penalty on .lower().
    condition_notes = raw_scan.get("condition_notes")
    if not isinstance(condition_notes, str):
        condition_notes = ""

    base_confidence_raw = raw_scan.get("scan_confidence", 0.95)
    try:
        base_confidence = float(base_confidence_raw)
    except (TypeError, ValueError):
        parse_errors.append(f"non-numeric scan_confidence in payload: {base_confidence_raw!r}")
        base_confidence = 0.0

    batch_code = None
    checksum_valid = False

    if raw_code is None:
        parse_errors.append("no batch code field in scan payload")
    elif not isinstance(raw_code, str):
        parse_errors.append(f"batch code field is not a string: {raw_code!r}")
    else:
        match = CODE_RE.match(raw_code) if "?" not in raw_code else None
        if not match:
            parse_errors.append(f"unparseable batch code from scan: '{raw_code}'")
        else:
            digits, check_digit = match.group(1), int(match.group(2))
            computed = sum(int(d) for d in digits) % 10
            checksum_valid = computed == check_digit
            batch_code = raw_code
            if not checksum_valid:
                parse_errors.append(
                    f"checksum mismatch on batch code '{raw_code}' (expected check digit {computed}, read {check_digit})"
                )

    expiry_date = None
    try:
        expiry_date = date.fromisoformat(raw_expiry)
    except (ValueError, TypeError):
        parse_errors.append(f"unparseable expiry date from scan: '{raw_expiry}'")

    confidence = max(0.0, min(1.0, base_confidence))

    return EmbeddedMetadataReadResult(
        raw_code=str(raw_code) if raw_code is not None else "<missing>",
        batch_code=batch_code,
        expiry_date=expiry_date,
        condition_notes=condition_notes,
        confidence=confidence,
        checksum_valid=checksum_valid,
        parse_errors=parse_errors,
    )
