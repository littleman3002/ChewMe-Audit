"""Detector: oversized unreferenced outputs.

Pre-registered rule (heuristic, labeled as such): observation larger
than 2 KB whose distinctive values never appear later in the
trajectory. Distinctive values = alphanumeric tokens of length >= 12.
Waste = tokens of the output (its first inclusion; subsequent re-sends
are counted by the repeat detectors).
"""

import re

from .. import counting
from .base import Finding

DETECTOR = "oversized_unreferenced"
SIZE_THRESHOLD = 2048
TOKEN_RE = re.compile(r"[A-Za-z0-9]{12,}")


def run(trace, provider="deepseek"):
    steps = trace.steps
    # index of distinctive tokens per later step for forward-reference check
    later_tokens = []
    acc = set()
    for s in reversed(steps):
        later_tokens.append(set(acc))
        acc |= set(TOKEN_RE.findall(s.text))
    later_tokens.reverse()

    findings = []
    for i, s in enumerate(steps):
        if len(s.text) < SIZE_THRESHOLD:
            continue
        distinctive = set(TOKEN_RE.findall(s.text))
        if not distinctive:
            continue
        referenced = distinctive & later_tokens[i]
        if referenced:
            continue
        n_tokens, basis = counting.count(s.text, provider)
        findings.append(Finding(
            detector=DETECTOR,
            trace_id=trace.trace_id,
            step_idx=s.step_idx,
            waste_tokens=n_tokens,
            token_basis=basis,
            summary=(f"{len(s.text)/1024:.1f} KB output, none of its "
                     f"{len(distinctive)} distinctive values referenced later "
                     f"({n_tokens} tokens)"),
            detail={
                "bytes": len(s.text),
                "distinctive_values": len(distinctive),
                "tool_name": s.tool_name,
            },
            fix_key="truncate_tool_output",
        ))
    return findings
