"""Waste detectors — one module per class.

Rules are ported from the pre-registered premise test
(tokenizer-lab/reports/prereg-audit-premise.md), not re-derived.
Every detector returns a list of Finding; dollar figures are attached
later by the report layer from the recorded price sheets.
"""

from dataclasses import dataclass, field


@dataclass
class Finding:
    detector: str            # e.g. "repeated_calls"
    trace_id: str
    step_idx: int            # step where the waste was observed
    waste_tokens: int
    token_basis: str
    summary: str             # one-line human description
    detail: dict = field(default_factory=dict)   # evidence (hashes, pairs, ...)
    fix_key: str = ""        # key into fixes.snippets
    measurable: bool = True  # False for classes that need API logs
    covers: frozenset = field(default_factory=frozenset)  # step indices whose
        # tokens this finding's waste accounts for; empty == {step_idx}.
        # Run-level findings (e.g. a 283-repeat run) list every covered
        # step so aggregation can dedupe overlaps across detectors.
