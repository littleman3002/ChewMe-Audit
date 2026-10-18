"""Cross-trace duplication: waste that per-trace detectors cannot see.

When N agents work the same task (separate traces), they redundantly
perform identical observations: the same file listing, the same file
read, the same exploration command. Per-trace detectors treat each
trace in isolation, so this duplication is invisible to them.

This module finds byte-identical (whitespace-normalized) tool
observations appearing in more than one trace. For an observation
found in k traces, (k-1) copies are duplication waste.

Honesty notes:
- Only tool observations are compared (assistant messages are
  agent-specific by construction).
- "Identical" means normalized-text identical; near-duplicates across
  traces are NOT flagged (conservative: avoids false positives from
  similar-but-distinct work).
- This measures duplication of OBSERVATIONS, not of outcomes: two
  agents reading the same file is duplication even if both needed it.
  Whether the duplication was avoidable (better partitioning) is a
  separate judgment the report does not make.
"""

import hashlib

from .detectors.base import Finding


def _normalize(text):
    return " ".join(text.split())


def _hash(text):
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def find_cross_trace_duplicates(traces, provider="deepseek"):
    """Return (groups, total_dup_tokens).

    groups: list of dicts, one per observation hash seen in >1 trace:
      {sha256, n_traces, trace_ids, waste_tokens, sample}
    total_dup_tokens: sum over groups of (n_traces - 1) * tokens.
    """
    from . import counting

    by_hash = {}
    for trace in traces:
        for s in trace.steps:
            if s.role != "tool":
                continue
            h = _hash(s.text)
            e = by_hash.setdefault(h, {"trace_ids": set(), "sample": s.text})
            e["trace_ids"].add(trace.trace_id)
    groups = []
    total = 0
    for h, e in by_hash.items():
        tids = sorted(e["trace_ids"])
        if len(tids) < 2:
            continue
        n_tokens, _ = counting.count(e["sample"], provider)
        waste = (len(tids) - 1) * n_tokens
        total += waste
        groups.append({
            "sha256": h[:16],
            "n_traces": len(tids),
            "trace_ids": tids,
            "tokens_each": n_tokens,
            "waste_tokens": waste,
            "sample": e["sample"][:200],
        })
    groups.sort(key=lambda g: -g["waste_tokens"])
    return groups, total


def as_findings(groups, provider="deepseek"):
    """Represent cross-trace duplication as findings (one per group)."""
    from . import counting
    findings = []
    for g in groups:
        _, basis = counting.count(g["sample"], provider)
        findings.append(Finding(
            detector="cross_trace_duplication",
            trace_id=",".join(g["trace_ids"]),
            step_idx=-1,
            waste_tokens=g["waste_tokens"],
            token_basis=basis,
            summary=(f"identical tool observation in {g['n_traces']} traces "
                     f"({g['waste_tokens']:,} duplicated tokens)"),
            detail={"sha256": g["sha256"], "trace_ids": g["trace_ids"],
                    "tokens_each": g["tokens_each"],
                    "sample": g["sample"][:200]},
            fix_key="partition_agent_work",
            measurable=True,
        ))
    return findings


def markdown_report(groups, total_dup_tokens, provider, sheets=None):
    from . import pricing
    L = ["# Cross-trace duplication report", ""]
    L.append(f"**{len(groups)}** identical observations found in more than "
             f"one trace.")
    L.append(f"Duplication waste: **{total_dup_tokens:,} tokens**")
    dollars = pricing.waste_dollars(total_dup_tokens, provider, sheets)
    if dollars is not None:
        L.append(f"(${dollars:.4f} at {provider} miss rate)")
    L.append("")
    for g in groups[:20]:
        L.append(f"- `{g['sha256']}` — {g['n_traces']} traces, "
                 f"{g['waste_tokens']:,} duplicated tokens "
                 f"({g['tokens_each']:,} each): "
                 f"{g['sample'][:100].replace(chr(10), ' ')}")
    if len(groups) > 20:
        L.append(f"- …and {len(groups) - 20} more")
    return "\n".join(L)
