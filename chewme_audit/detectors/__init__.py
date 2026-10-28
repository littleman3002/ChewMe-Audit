"""Detector registry."""

from . import near_duplicates, oversized_outputs, pretty_print, repeated_calls
from . import unmeasurable
from . import blind_edit  # noqa: F401  (risk flags; run separately, not in run_all)
from . import unverified_final_state  # noqa: F401  (risk flags; run separately, not in run_all)
from . import dead_context  # noqa: F401  (measurable waste; joined
# MEASURABLE after its precision validation passed — v2: 90.0%
# precision on 100 hand-checked flags (Wilson 95% CI [82.6%,
# 94.5%]), 0 misses in 27 live files, Stage C passed 2026-10-27;
# v2 supersedes v1 (96.0% on its own slice). See the validation
# report at ~/workspace/eth-paper/dead-context-v2-report.md.)

MEASURABLE = [
    repeated_calls,
    near_duplicates,
    oversized_outputs,
    pretty_print,
    dead_context,
]


def run_all(trace, provider="deepseek", include_unmeasurable=True):
    findings = []
    for mod in MEASURABLE:
        findings.extend(mod.run(trace, provider))
    if include_unmeasurable:
        findings.extend(unmeasurable.cache_layout_notes(trace))
        findings.extend(unmeasurable.reasoning_notes(trace))
    return findings
