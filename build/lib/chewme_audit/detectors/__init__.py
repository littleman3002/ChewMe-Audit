"""Detector registry."""

from . import near_duplicates, oversized_outputs, pretty_print, repeated_calls
from . import unmeasurable

MEASURABLE = [
    repeated_calls,
    near_duplicates,
    oversized_outputs,
    pretty_print,
]


def run_all(trace, provider="deepseek", include_unmeasurable=True):
    findings = []
    for mod in MEASURABLE:
        findings.extend(mod.run(trace, provider))
    if include_unmeasurable:
        findings.extend(unmeasurable.cache_layout_notes(trace))
        findings.extend(unmeasurable.reasoning_notes(trace))
    return findings
