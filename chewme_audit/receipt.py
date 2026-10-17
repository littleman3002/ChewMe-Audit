"""Tamper-evident per-finding receipts (--receipt mode).

Adapted from the lab's savings-receipt concept
(tokenizer-lab/reports/savings-receipt.md): each finding gets a
receipt carrying the counts and dollars behind it plus a SHA-256 over
the canonical fields. The customer holds their own traces; the receipt
carries only hashes of text, never the text itself — no PII in the
receipt.

Verification: recompute the hash over the canonical fields; any
modified count or dollar figure breaks it.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from . import pricing


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def issue(finding, provider, priced=True):
    dollars = (pricing.waste_dollars(finding.waste_tokens, provider)
               if priced else None)
    sheet = pricing.get_sheet(provider)
    body = {
        "receipt_id": uuid.uuid4().hex,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "kind": "audit_finding",
        "detector": finding.detector,
        "trace_id": finding.trace_id,
        "step_idx": finding.step_idx,
        "waste_tokens": finding.waste_tokens,
        "waste_dollars": dollars,
        "token_basis": finding.token_basis,
        "pricing_basis": ("model:" + sheet["model"]) if sheet else "unknown",
        "price_note": "waste priced at cache-miss rate (waste spans are 100% cache misses)",
        "summary": finding.summary,
        "fix_key": finding.fix_key,
    }
    body["receipt_hash"] = hashlib.sha256(
        _canonical(body).encode("utf-8")).hexdigest()
    return body


def verify(receipt):
    """True iff the receipt is untampered."""
    given = receipt.get("receipt_hash")
    if not given:
        return False
    body = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest() == given


def issue_all(findings, provider, priced=True):
    return [issue(f, provider, priced) for f in findings if f.measurable]
