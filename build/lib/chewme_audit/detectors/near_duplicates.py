"""Detector: near-duplicate re-sends (perturbation cache-breakers).

Pre-registered rule: consecutive observations in a trajectory with
difflib.SequenceMatcher ratio >= 0.85. Small perturbations defeat
prefix caching by construction. Waste = tokens of the re-sent
observation.

The audit distinguishes fixable re-sends (full file re-view after a
one-line edit -> send a diff) from normal iteration (grep retried with
different terms) by surfacing the pair and its diff.
"""

import difflib

from .. import counting
from .base import Finding

DETECTOR = "near_duplicate_resends"
THRESHOLD = 0.85


def run(trace, provider="deepseek"):
    steps = trace.steps
    findings = []
    for prev, cur in zip(steps, steps[1:]):
        if not prev.text or not cur.text:
            continue
        ratio = difflib.SequenceMatcher(None, prev.text, cur.text).ratio()
        if ratio < THRESHOLD:
            continue
        n_tokens, basis = counting.count(cur.text, provider)
        diff_hint = _diff_hint(prev.text, cur.text)
        findings.append(Finding(
            detector=DETECTOR,
            trace_id=trace.trace_id,
            step_idx=cur.step_idx,
            waste_tokens=n_tokens,
            token_basis=basis,
            summary=(f"near-duplicate re-send (similarity {ratio:.2f}, "
                     f"{n_tokens} tokens re-sent)"),
            detail={
                "similarity": round(ratio, 3),
                "prev_step": prev.step_idx,
                "diff_hint": diff_hint,
                "tool_name": cur.tool_name,
            },
            fix_key="diff_read" if diff_hint == "small_diff" else "review_resend",
        ))
    return findings


def _diff_hint(a, b):
    """Classify the pair: small diff (fixable via diff-read) or rework."""
    sm = difflib.SequenceMatcher(None, a.splitlines(), b.splitlines())
    changed = sum(1 for tag, _, _, _, _ in sm.get_opcodes() if tag != "equal")
    total = max(len(a.splitlines()), len(b.splitlines()), 1)
    return "small_diff" if changed / total < 0.2 else "rework"
