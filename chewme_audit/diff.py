"""Diff mode: before/after comparison of two audit runs.

The complete loop: find -> recommend fix -> apply -> prove the delta.

Alignment assumption (v1, documented, not overbuilt): traces are matched
by `trace_id` when both sides carry non-empty, unique trace_ids;
otherwise they are matched by order. Traces that don't match are listed
as unmatched_before / unmatched_after and are NEVER silently dropped.
No fuzzy task hashing in v1 — real users will tell us the matching rules
they need.
"""

from . import detectors, pricing, report
from . import fixes as fixlib


def align_traces(before, after):
    """Match traces between the before and after runs.

    Returns (pairs, unmatched_before, unmatched_after, method) where
    pairs is a list of (before_trace, after_trace), the unmatched lists
    carry trace_ids, and method is "trace_id" or "order".
    """
    before_ids = [t.trace_id for t in before]
    after_ids = [t.trace_id for t in after]
    use_ids = (
        all(before_ids) and all(after_ids)
        and len(set(before_ids)) == len(before_ids)
        and len(set(after_ids)) == len(after_ids)
    )
    pairs, unmatched_before, unmatched_after = [], [], []
    if use_ids:
        after_by_id = {t.trace_id: t for t in after}
        used = set()
        for b in before:
            a = after_by_id.get(b.trace_id)
            if a is not None and b.trace_id not in used:
                pairs.append((b, a))
                used.add(b.trace_id)
            else:
                unmatched_before.append(b.trace_id)
        for a in after:
            if a.trace_id not in used:
                unmatched_after.append(a.trace_id)
        method = "trace_id"
    else:
        n = min(len(before), len(after))
        pairs = list(zip(before[:n], after[:n]))
        unmatched_before = [t.trace_id for t in before[n:]]
        unmatched_after = [t.trace_id for t in after[n:]]
        method = "order"
    return pairs, unmatched_before, unmatched_after, method


def _group(findings):
    """Sum measurable findings by (detector, fix_key)."""
    g = {}
    for f in findings:
        if not f.measurable:
            continue
        key = (f.detector, f.fix_key)
        d = g.setdefault(key, {"tokens": 0, "count": 0})
        d["tokens"] += f.waste_tokens
        d["count"] += 1
    return g


def _dollars(tokens, provider, sheets, priced):
    if not priced or tokens is None:
        return None
    return pricing.waste_dollars(tokens, provider, sheets)


def build_diff(before_traces, after_traces, provider, framework="generic",
               api_log_records=None, sheets=None, include_total_bill=False):
    """Run the full audit on both sides and diff them.

    Returns (rep_before, rep_after, diff) where the reports come straight
    from report.build (same machinery, same honesty labels) and diff is
    the delta object described below.
    """
    sheets = sheets or pricing.SHEETS
    pairs, unmatched_before, unmatched_after, method = align_traces(
        before_traces, after_traces)

    fb = {id(t): detectors.run_all(t, provider) for t in before_traces}
    fa = {id(t): detectors.run_all(t, provider) for t in after_traces}
    rep_before = report.build(
        before_traces,
        {t.trace_id: fb[id(t)] for t in before_traces},
        provider, framework, api_log_records=api_log_records,
        sheets=sheets, include_total_bill=include_total_bill)
    rep_after = report.build(
        after_traces,
        {t.trace_id: fa[id(t)] for t in after_traces},
        provider, framework, api_log_records=api_log_records,
        sheets=sheets, include_total_bill=include_total_bill)

    priced = rep_before["dollars_shown"] and rep_after["dollars_shown"]

    # Classify per (detector, fix_key) on MATCHED traces only.
    gb, ga = {}, {}
    for b, a in pairs:
        for key, d in _group(fb[id(b)]).items():
            acc = gb.setdefault(key, {"tokens": 0, "count": 0})
            acc["tokens"] += d["tokens"]
            acc["count"] += d["count"]
        for key, d in _group(fa[id(a)]).items():
            acc = ga.setdefault(key, {"tokens": 0, "count": 0})
            acc["tokens"] += d["tokens"]
            acc["count"] += d["count"]

    resolved, reduced, new, unchanged = [], [], [], []
    for key in sorted(set(gb) | set(ga)):
        detector, fix_key = key
        bt = gb.get(key, {"tokens": 0, "count": 0})
        at = ga.get(key, {"tokens": 0, "count": 0})
        entry = {
            "detector": detector,
            "fix_key": fix_key,
            "before_tokens": bt["tokens"],
            "after_tokens": at["tokens"],
            "before_dollars": _dollars(bt["tokens"], provider, sheets, priced),
            "after_dollars": _dollars(at["tokens"], provider, sheets, priced),
        }
        if key not in ga:
            entry["status"] = "resolved"
            resolved.append(entry)
        elif key not in gb:
            entry["status"] = "new"
            new.append(entry)
        elif at["tokens"] < bt["tokens"] * 0.9:
            entry["status"] = "reduced"
            entry["reduction_pct"] = round(
                1 - at["tokens"] / bt["tokens"], 4) if bt["tokens"] else 0.0
            reduced.append(entry)
        else:
            entry["status"] = "unchanged"
            unchanged.append(entry)

    # Per-detector token deltas (matched + unmatched traces, from reports).
    by_detector = {}
    for det, d in rep_before["by_detector"].items():
        by_detector.setdefault(det, {})["before_tokens"] = d["waste_tokens"]
    for det, d in rep_after["by_detector"].items():
        by_detector.setdefault(det, {})["after_tokens"] = d["waste_tokens"]
    for det, d in by_detector.items():
        d.setdefault("before_tokens", 0)
        d.setdefault("after_tokens", 0)
        d["delta_tokens"] = d["after_tokens"] - d["before_tokens"]
        if priced:
            d["delta_dollars"] = round(
                _dollars(d["after_tokens"], provider, sheets, priced)
                - _dollars(d["before_tokens"], provider, sheets, priced), 6)
        else:
            d["delta_dollars"] = None

    wb = rep_before["total_waste_tokens"]
    wa = rep_after["total_waste_tokens"]
    ib = rep_before["total_input_tokens"]
    ia = rep_after["total_input_tokens"]

    # Fix keys surviving on both sides: the fix wasn't fully applied
    # (or the agent found a new way to loop) — re-surface the snippet.
    not_fully_applied = []
    for entry in reduced + unchanged:
        if not entry["fix_key"]:
            continue
        fix = fixlib.get(entry["fix_key"], framework)
        if not fix:
            continue
        not_fully_applied.append({
            "fix_key": entry["fix_key"],
            "detector": entry["detector"],
            "title": fix["title"],
            "safety": fix["safety"],
            "snippet": fix["snippet"],
            "note": ("still present after the fix run — the fix wasn't "
                     "fully applied, or the agent found a new way to loop."),
            "residual_tokens": entry["after_tokens"],
        })

    diff = {
        "provider": provider,
        "pricing_basis": rep_after["pricing_basis"],
        "framework": framework,
        "alignment": {
            "method": method,
            "matched": len(pairs),
            "unmatched_before": unmatched_before,
            "unmatched_after": unmatched_after,
        },
        "before": {
            "n_traces": rep_before["n_traces"],
            "n_steps": rep_before["n_steps"],
            "total_input_tokens": ib,
            "total_input_dollars": rep_before["total_input_dollars"],
            "total_waste_tokens": wb,
            "total_waste_dollars": rep_before["total_waste_dollars"],
            "cache_accounting": rep_before["cache_accounting"],
        },
        "after": {
            "n_traces": rep_after["n_traces"],
            "n_steps": rep_after["n_steps"],
            "total_input_tokens": ia,
            "total_input_dollars": rep_after["total_input_dollars"],
            "total_waste_tokens": wa,
            "total_waste_dollars": rep_after["total_waste_dollars"],
            "cache_accounting": rep_after["cache_accounting"],
        },
        "waste_tokens_delta": wa - wb,
        "waste_dollars_delta": (
            (rep_after["total_waste_dollars"] or 0)
            - (rep_before["total_waste_dollars"] or 0)
            if priced else None),
        "input_tokens_delta": ia - ib,
        "input_dollars_delta": (
            (rep_after["total_input_dollars"] or 0)
            - (rep_before["total_input_dollars"] or 0)
            if priced and rep_before["total_input_dollars"] is not None
            and rep_after["total_input_dollars"] is not None else None),
        "by_detector": by_detector,
        "resolved": resolved,
        "reduced": reduced,
        "new": new,
        "unchanged": unchanged,
        "not_fully_applied": not_fully_applied,
        "labels": [
            "diff alignment: matched by trace_id"
            if method == "trace_id" else
            "diff alignment: matched by ORDER (trace_ids absent or "
            "non-unique) — verify the pairing before quoting",
            "classification is per (detector, fix_key) on matched traces "
            "only; unmatched traces are listed, never silently dropped",
            "reduced = waste tokens down more than 10% on the same class",
        ],
    }
    return rep_before, rep_after, diff


def diff_markdown(diff):
    """The Diff section: three questions in under 10 seconds.

    1) Net change (tokens + $). 2) What disappeared/shrank.
    3) What remains or got worse.
    """
    L = []
    L.append("# Diff: before → after")
    L.append("")
    b, a = diff["before"], diff["after"]

    def money(v):
        return f"${v:.4f}" if v is not None else "n/a"

    # 1) Net change
    L.append("## 1) Net change")
    L.append("")
    wd = diff["waste_tokens_delta"]
    wdd = diff["waste_dollars_delta"]
    arrow = "↓" if wd < 0 else ("↑" if wd > 0 else "=")
    L.append(f"- Waste: **{b['total_waste_tokens']:,} tokens "
             f"({money(b['total_waste_dollars'])})** → "
             f"**{a['total_waste_tokens']:,} tokens "
             f"({money(a['total_waste_dollars'])})** "
             f"{arrow} {wd:+,} tokens"
             + (f" ({wdd:+.4f} $)" if wdd is not None else ""))
    ind = diff["input_tokens_delta"]
    indd = diff["input_dollars_delta"]
    L.append(f"- Total input: {b['total_input_tokens']:,} → "
             f"{a['total_input_tokens']:,} tokens ({ind:+,})"
             + (f" ({indd:+.4f} $)" if indd is not None else ""))
    L.append(f"- Residual waste left: **{a['total_waste_tokens']:,} tokens "
             f"({money(a['total_waste_dollars'])})**")
    L.append("")

    def entry_line(e):
        d = (f"${e['after_dollars']:.4f}" if e["after_dollars"] is not None
             else f"{e['after_tokens']:,} tokens")
        return (f"- **[{e['detector']}]** `{e['fix_key'] or 'no-fix-key'}`: "
                f"{e['before_tokens']:,} → {e['after_tokens']:,} tokens "
                f"({d})")

    # 2) What disappeared / shrank
    L.append("## 2) What disappeared / shrank")
    L.append("")
    if diff["resolved"]:
        L.append("**Resolved** (present before, gone after):")
        for e in diff["resolved"]:
            d = (f"${e['before_dollars']:.4f}"
                 if e["before_dollars"] is not None else "")
            L.append(f"- **[{e['detector']}]** `{e['fix_key'] or 'no-fix-key'}`: "
                     f"{e['before_tokens']:,} tokens {d} eliminated")
        L.append("")
    if diff["reduced"]:
        L.append("**Reduced** (waste down >10% on the same class):")
        for e in diff["reduced"]:
            L.append(f"{entry_line(e)} — down {e['reduction_pct']:.0%}")
        L.append("")
    if not diff["resolved"] and not diff["reduced"]:
        L.append("_Nothing resolved or reduced._")
        L.append("")

    # 3) What remains or got worse
    L.append("## 3) What remains or got worse")
    L.append("")
    if diff["new"]:
        L.append("**New** (absent before, present after — don't ship a "
                 "partial win and call it done):")
        for e in diff["new"]:
            L.append(entry_line(e))
        L.append("")
    if diff["unchanged"]:
        L.append("**Unchanged**:")
        for e in diff["unchanged"]:
            L.append(entry_line(e))
        L.append("")
    if not diff["new"] and not diff["unchanged"]:
        L.append("_Nothing remains — clean._")
        L.append("")

    if diff["not_fully_applied"]:
        L.append("## Fixes not fully applied")
        L.append("")
        for n in diff["not_fully_applied"]:
            L.append(f"### {n['title']}")
            L.append(f"_{n['note']}_")
            L.append(f"_Residual: {n['residual_tokens']:,} tokens._")
            L.append(f"_{n['safety']}_")
            L.append("")
            L.append(f"```python\n{n['snippet']}\n```")
            L.append("")

    al = diff["alignment"]
    L.append("## Diff honesty labels")
    L.append("")
    L.append(f"- Aligned {al['matched']} traces by **{al['method']}**.")
    if al["unmatched_before"]:
        L.append(f"- Unmatched before: {', '.join(al['unmatched_before'])}")
    if al["unmatched_after"]:
        L.append(f"- Unmatched after: {', '.join(al['unmatched_after'])}")
    for lab in diff["labels"]:
        L.append(f"- {lab}")
    L.append("")
    return L
