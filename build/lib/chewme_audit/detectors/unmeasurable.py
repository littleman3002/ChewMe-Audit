"""Unmeasurable classes — reported as guidance, never as findings.

Two waste classes from the pre-registration cannot be measured from
trace exports alone; they need customer API logs:

  - cache_breaking_layouts: actual cache hit/miss behavior is unobserved
    without request logs. Structural hints (growing single-message
    context vs per-turn messages) are noted, not priced.
  - reasoning_on_trivial_steps: traces carry no reasoning-token data.

The audit is explicit about this: these are upside the tool reads
from API logs, not absence. A finding with measurable=False never
carries a dollar figure.
"""

from .base import Finding


def cache_layout_notes(trace):
    """Structural notes only — no token or dollar claims."""
    notes = []
    n = len(trace.steps)
    if n >= 10:
        notes.append(
            f"{n} steps in one growing context: early steps are re-sent "
            "every turn. Whether that re-send hits cache depends on your "
            "provider's prefix-cache behavior — check cache-hit rates in "
            "your API logs. (Not measurable from trace exports.)")
    return [Finding(
        detector="cache_breaking_layouts",
        trace_id=trace.trace_id,
        step_idx=-1,
        waste_tokens=0,
        token_basis="n/a",
        summary=n,
        detail={},
        measurable=False,
    ) for n in notes]


def reasoning_notes(trace):
    return [Finding(
        detector="reasoning_on_trivial_steps",
        trace_id=trace.trace_id,
        step_idx=-1,
        waste_tokens=0,
        token_basis="n/a",
        summary=("reasoning-token overspend is not visible in trace "
                 "exports; it needs reasoning-token counts from your API "
                 "logs."),
        detail={},
        measurable=False,
    )]
