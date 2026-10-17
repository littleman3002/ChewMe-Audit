"""Report builder: markdown + JSON.

Honesty rules (standing):
- Benchmark-trajectory numbers stay labeled as such.
- Dollar figures only on priceable token bases; otherwise tokens with
  the basis labeled and dollars null.
- Total-bill share assumes outputs ~50% of the bill (illustrative,
  labeled, not measured on the input traces).
- Unmeasurable classes appear as guidance, never with dollar figures.
"""

import json
from datetime import datetime, timezone

from . import api_log as api_log_mod
from . import counting, pricing
from . import fixes as fixlib


def build(traces, findings_by_trace, provider, framework="generic",
          api_log_records=None):
    sheet = pricing.get_sheet(provider)
    total_input_tokens = 0
    total_waste_tokens = 0
    basis_seen = set()
    for trace in traces:
        for s in trace.steps:
            n, basis = counting.count(s.text, provider)
            total_input_tokens += n
            basis_seen.add(basis)
    priced = all(counting.priceable_basis(b) for b in basis_seen)

    findings = [f for fs in findings_by_trace.values() for f in fs]
    measurable = [f for f in findings if f.measurable]
    for f in measurable:
        total_waste_tokens += f.waste_tokens

    # Cache accounting: EXACT when API logs are provided, estimated otherwise.
    # The API log's own token counts are authoritative for the totals, so
    # the measured path does not depend on our counting basis. Waste
    # dollars still require a priceable basis (waste tokens x miss rate).
    cache_accounting = "estimated"
    measured_input_dollars = None
    matched_requests = 0
    if api_log_records and sheet:
        idx = api_log_mod.index_by_step(api_log_records)
        total = 0.0
        for trace in traces:
            for s in trace.steps:
                rec = idx.get((trace.trace_id, s.step_idx))
                if rec is None:
                    # unmatched step: fall back to miss-price estimate (labeled)
                    n, _ = counting.count(s.text, provider)
                    total += n / 1e6 * sheet["miss_per_mtok"]
                else:
                    matched_requests += 1
                    missed = rec.prompt_tokens - rec.cached_tokens
                    total += (rec.cached_tokens / 1e6 * sheet["hit_per_mtok"]
                              + missed / 1e6 * sheet["miss_per_mtok"])
        measured_input_dollars = total
        cache_accounting = "measured" if matched_requests else "estimated"

    waste_dollars = (pricing.waste_dollars(total_waste_tokens, provider)
                     if priced else None)
    total_input_dollars = (measured_input_dollars if measured_input_dollars
                           is not None
                           else (pricing.waste_dollars(total_input_tokens, provider)
                                 if priced else None))

    input_share = (total_waste_tokens / total_input_tokens
                   if total_input_tokens else 0.0)
    # Dollar share of input spend (exact denominator when API logs present).
    input_dollar_share = (waste_dollars / total_input_dollars
                          if waste_dollars and total_input_dollars else None)
    # Illustrative total-bill share: outputs ~50% of bill (labeled).
    total_bill_share = (input_dollar_share / 2
                        if input_dollar_share is not None else None)

    by_detector = {}
    for f in measurable:
        d = by_detector.setdefault(f.detector, {"findings": 0, "waste_tokens": 0})
        d["findings"] += 1
        d["waste_tokens"] += f.waste_tokens

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "pricing_basis": ("model:" + sheet["model"]) if sheet else "unknown",
        "token_basis": sorted(basis_seen),
        "dollars_shown": priced,
        "n_traces": len(traces),
        "n_steps": sum(len(t.steps) for t in traces),
        "total_input_tokens": total_input_tokens,
        "total_input_dollars": total_input_dollars,
        "total_waste_tokens": total_waste_tokens,
        "total_waste_dollars": waste_dollars,
        "waste_share_of_input": round(input_share, 4),
        "waste_share_of_input_dollars": (
            round(input_dollar_share, 4) if input_dollar_share is not None else None),
        "waste_share_of_total_bill_illustrative": (
            round(total_bill_share, 4) if total_bill_share is not None else None),
        "cache_accounting": cache_accounting,
        "api_log_requests_matched": matched_requests,
        "by_detector": by_detector,
        "findings": findings,
        "framework": framework,
        "labels": [
            "measured on the provided traces (not a benchmark claim)",
            "waste priced at cache-miss rate (waste spans are 100% cache misses, measured)",
            ("cache accounting: EXACT (from your API logs)"
             if cache_accounting == "measured" else
             "cache accounting: ESTIMATED (no API logs provided — hand it your API logs for exacts)"),
            "total-bill share illustrative: assumes outputs ~50% of bill",
            "waste share is a lower bound: re-sends inflate every later request's prompt (superlinear), which this figure does not model",
        ],
    }


def to_markdown(rep):
    L = []
    L.append("# Agent cost audit")
    L.append("")
    L.append(f"Generated {rep['generated_at']} · provider `{rep['provider']}` "
             f"· pricing `{rep['pricing_basis']}` · token basis "
             f"`{', '.join(rep['token_basis'])}`")
    L.append("")
    L.append(f"**{rep['n_traces']} traces, {rep['n_steps']} steps.** "
             f"{rep['total_input_tokens']:,} input tokens"
             + (f" (${rep['total_input_dollars']:.4f})"
                if rep['total_input_dollars'] is not None else ""))
    L.append("")
    L.append("## Headline")
    L.append("")
    cache_tag = ("**EXACT** (API logs)" if rep['cache_accounting'] == "measured"
                 else "**ESTIMATED** (no API logs — estimates out of the box; "
                      "hand it your API logs for exacts)")
    L.append(f"- Cache accounting: {cache_tag}")
    if rep['dollars_shown']:
        L.append(f"- Measurable waste: **{rep['total_waste_tokens']:,} tokens "
                 f"(${rep['total_waste_dollars']:.4f})**")
        L.append(f"- Share of input tokens: {rep['waste_share_of_input']:.1%} (estimated)")
        if rep['waste_share_of_input_dollars'] is not None:
            L.append(f"- Share of input spend: "
                     f"**{rep['waste_share_of_input_dollars']:.1%}** "
                     f"({rep['cache_accounting']})")
        L.append(f"- Share of total bill (illustrative, outputs ~50%): "
                 f"**{rep['waste_share_of_total_bill_illustrative']:.1%}**")
    else:
        L.append(f"- Measurable waste: **{rep['total_waste_tokens']:,} tokens** "
                 f"(token basis `{', '.join(rep['token_basis'])}` — "
                 "not a billed-token basis, waste dollars not shown)")
        if rep['total_input_dollars'] is not None:
            L.append(f"- Total input spend: ${rep['total_input_dollars']:.4f} "
                     f"({rep['cache_accounting']}, from API logs)")
        L.append(f"- Share of input tokens: **{rep['waste_share_of_input']:.1%}**")
    L.append("")
    L.append("## Findings by class")
    L.append("")
    for det, d in sorted(rep["by_detector"].items(),
                         key=lambda kv: -kv[1]["waste_tokens"]):
        L.append(f"### {det}")
        L.append(f"{d['findings']} findings · {d['waste_tokens']:,} waste tokens")
        L.append("")
    L.append("## Prioritized findings")
    L.append("")
    meas = [f for f in rep["findings"] if f.measurable]
    meas.sort(key=lambda f: -f.waste_tokens)
    priced = rep["dollars_shown"]
    for f in meas[:50]:
        dollars = (pricing.waste_dollars(f.waste_tokens, rep["provider"])
                   if priced else None)
        dstr = f" (${dollars:.4f})" if dollars is not None else ""
        L.append(f"- **[{f.detector}]** {f.trace_id} step {f.step_idx}: "
                 f"{f.summary} — {f.waste_tokens:,} tokens{dstr}")
    if len(meas) > 50:
        L.append(f"\n_...and {len(meas)-50} more (see JSON output)._")
    L.append("")
    L.append("## Recommended fixes")
    L.append("")
    seen = []
    for f in meas:
        if f.fix_key and f.fix_key not in seen:
            seen.append(f.fix_key)
    for key in seen:
        fix = fixlib.get(key, rep["framework"])
        if not fix:
            continue
        L.append(f"### {fix['title']}")
        L.append(f"_{fix['safety']}_")
        L.append("")
        L.append(f"```python\n{fix['snippet']}\n```")
        L.append("")
    unmeas = [f for f in rep["findings"] if not f.measurable]
    if unmeas:
        L.append("## Needs your API logs (not measurable from traces)")
        L.append("")
        seen_det = set()
        for f in unmeas:
            if f.detector in seen_det:
                continue
            seen_det.add(f.detector)
            L.append(f"- **{f.detector}**: {f.summary}")
        L.append("")
    L.append("## Honesty labels")
    L.append("")
    for lab in rep["labels"]:
        L.append(f"- {lab}")
    L.append("")
    return "\n".join(L)


def to_json(rep):
    def _finding(f):
        return {
            "detector": f.detector,
            "trace_id": f.trace_id,
            "step_idx": f.step_idx,
            "waste_tokens": f.waste_tokens,
            "waste_dollars": (pricing.waste_dollars(f.waste_tokens, rep["provider"])
                              if rep["dollars_shown"] else None),
            "token_basis": f.token_basis,
            "summary": f.summary,
            "detail": f.detail,
            "fix_key": f.fix_key,
            "measurable": f.measurable,
        }
    out = dict(rep)
    out["findings"] = [_finding(f) for f in rep["findings"]]
    return json.dumps(out, indent=2)
