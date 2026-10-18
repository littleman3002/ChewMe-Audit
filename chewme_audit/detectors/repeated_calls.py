"""Detector: repeated identical calls.

Pre-registered rule: SHA-256 of normalized text; any observation text
occurring more than once within a trajectory. Waste = (occurrences-1)
x tokens of the text.

Duplicates at new positions cannot hit under prefix caching (the
context grew between occurrences), so they are priced at the miss rate.
"""

import hashlib
from collections import defaultdict

from .. import counting
from .base import Finding

DETECTOR = "repeated_calls"


def _normalize(text):
    return " ".join(text.split())


def run(trace, provider="deepseek"):
    groups = defaultdict(list)
    for s in trace.steps:
        h = hashlib.sha256(_normalize(s.text).encode("utf-8")).hexdigest()
        groups[h].append(s)
    findings = []
    for h, steps in groups.items():
        if len(steps) < 2:
            continue
        n_tokens, basis = counting.count(steps[0].text, provider)
        waste = (len(steps) - 1) * n_tokens
        first = steps[0]
        findings.append(Finding(
            detector=DETECTOR,
            trace_id=trace.trace_id,
            step_idx=steps[-1].step_idx,
            waste_tokens=waste,
            token_basis=basis,
            summary=(f"identical observation repeated {len(steps)}x "
                     f"({waste} tokens re-sent)"),
            detail={
                "occurrences": len(steps),
                "sha256": h[:16],
                "first_step": first.step_idx,
                "tool_name": first.tool_name,
                "sample": first.text[:200],
            },
            fix_key="error_loop_dedup" if _looks_like_error(first.text)
            else "memoize_repeated_call",
            # The waste is the re-sends: every occurrence after the first.
            # Listing them lets aggregation dedupe against per-step
            # detectors (e.g. near-duplicates) flagging the same steps.
            covers=frozenset(s.step_idx for s in steps[1:]),
        ))
    return findings


_ERROR_HINTS = ("error", "traceback", "exception", "failed", "timeout",
                "usage:", "invalid", "not found")


def _looks_like_error(text):
    low = text.lower()
    return any(h in low for h in _ERROR_HINTS)
