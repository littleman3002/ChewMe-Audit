"""chewme-audit CLI.

Reads a team's agent traces and outputs a prioritized cost-audit
report: every fixable waste pattern, its measured dollar cost, and a
concrete copy-paste fix.

No API keys needed — token counting is local. Estimates out of the box
from trace exports; hand it your API logs (--api-log) if you want
exacts. What each input needs:
  - JSONL: one observation per line (auto-detected schema; see adapters/jsonl.py)
  - Langfuse: trace export JSON/JSONL (use --format langfuse)
  - LangSmith: run export JSON/JSONL (use --format langsmith)
  - Claude Code: CLI session transcript, ~/.claude/projects/*/*.jsonl
    (use --format claude-code)
  - LiteLLM: standard logging payload JSONL, one object per LLM call
    (use --format litellm; see adapters/litellm.py for the export snippet)
  - API log: JSONL of per-request usage with cache hit/miss split
    (see api_log.py for accepted shapes)
"""

import argparse
import json
import sys
import time

from . import api_log as api_log_mod
from . import detectors, pricing, receipt as receipt_mod, report
from .detectors import unverified_final_state as ufs_mod
from . import fixes as fixlib
from .adapters import jsonl as jsonl_adapter
from .adapters import langfuse as langfuse_adapter
from .adapters import langsmith as langsmith_adapter
from .adapters import claude_code as claude_code_adapter
from .adapters import litellm as litellm_adapter


def load_traces(path, fmt):
    if fmt == "langfuse":
        return langfuse_adapter.load_langfuse(path)
    if fmt == "langsmith":
        return langsmith_adapter.load_langsmith(path)
    if fmt == "claude-code":
        return claude_code_adapter.load_claude_code(path)
    if fmt == "litellm":
        return litellm_adapter.load_litellm(path)
    return jsonl_adapter.load_jsonl(path)


def load_pricing_overrides(spec):
    """spec: path to a JSON file, or inline JSON like
    '{"deepseek": {"miss_per_mtok": 0.20}}'. Merged over recorded sheets."""
    if not spec:
        return None
    try:
        with open(spec, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    try:
        return json.loads(spec)
    except json.JSONDecodeError:
        print(f"could not read --pricing as a file or JSON: {spec}",
              file=sys.stderr)
        sys.exit(2)


def main(argv=None):
    t0 = time.perf_counter()
    ap = argparse.ArgumentParser(
        prog="chewme-audit",
        description="Audit agent traces for fixable cost waste.")
    ap.add_argument("traces", nargs="+",
                    help="trace file: one for audit, two (before after) with --diff")
    ap.add_argument("--diff", action="store_true",
                    help=("diff mode: compare two trace files (before.jsonl "
                          "after.jsonl). All other flags apply to both sides; "
                          "--api-log applies the same log to both."))
    ap.add_argument("--provider", default="deepseek",
                    help="deepseek | grok | xai | claude | anthropic | openai | gemini | google (default: deepseek)")
    ap.add_argument("--format", default="jsonl", dest="fmt",
                    choices=["jsonl", "langfuse", "langsmith", "claude-code",
                             "litellm"],
                    help="input format: jsonl | langfuse | langsmith | claude-code (Claude Code CLI transcripts, ~/.claude/projects/) | litellm (LiteLLM standard logging payload JSONL) (default: jsonl)")
    ap.add_argument("--output", default="markdown", dest="output",
                    choices=["markdown", "json"],
                    help="report format (default: markdown)")
    ap.add_argument("--framework", default="generic",
                    choices=fixlib.frameworks(),
                    help="copy-paste fixes for this framework")
    ap.add_argument("--receipt", action="store_true",
                    help="also emit tamper-evident per-finding receipts as JSON")
    ap.add_argument("--api-log", default=None, dest="api_log",
                    help=("provider API log (JSONL, per-request usage with "
                          "cache hit/miss). With it, dollar figures use EXACT "
                          "cache accounting; without it, every figure is "
                          "labeled estimated. In --diff mode the same log "
                          "applies to both sides."))
    ap.add_argument("--out", default=None,
                    help="write report to file instead of stdout")
    ap.add_argument("--pricing", default=None,
                    help=("pricing overrides: path to a JSON file or inline "
                          "JSON, e.g. '{\"deepseek\": {\"miss_per_mtok\": 0.20}}'. "
                          "Merged over the recorded sheets; use it to re-verify "
                          "or correct rates."))
    ap.add_argument("--total-bill", action="store_true", dest="total_bill",
                    help=("OPT-IN: include the illustrative total-bill share "
                          "(assumes outputs ~50%% of bill). Off by default so "
                          "nobody quotes it without the label."))
    ap.add_argument("--workdir-diff", default=None, dest="workdir_diff",
                    help=("path to a unified diff of the working tree "
                          "(before/after the agent ran). Gives the "
                          "blind-edit risk check exact write evidence "
                          "instead of inference from git output in the "
                          "trace."))
    args = ap.parse_args(argv)

    sheets = pricing.apply_overrides(load_pricing_overrides(args.pricing))

    if args.diff:
        if len(args.traces) != 2:
            ap.error("--diff needs exactly two trace files: "
                     "before.jsonl after.jsonl")
        return run_diff(args, sheets, t0)

    if len(args.traces) != 1:
        ap.error("expected one trace file (two with --diff)")

    traces = load_traces(args.traces[0], args.fmt)
    if not traces:
        print("no traces parsed from input", file=sys.stderr)
        return 1

    api_records = (api_log_mod.load_api_log(args.api_log)
                   if args.api_log else None)

    findings_by_trace = {}
    risk = {"assessed": True, "reason": "", "writes_checked": 0,
            "flagged": 0, "ledger": []}
    ufs_infos = []
    wd_text = None
    if args.workdir_diff:
        with open(args.workdir_diff, encoding="utf-8") as f:
            wd_text = f.read()
    for t in traces:
        findings_by_trace[t.trace_id] = detectors.run_all(t, args.provider)
        bf, br = detectors.blind_edit.assess_and_flag(t, wd_text)
        findings_by_trace[t.trace_id].extend(bf)
        risk["writes_checked"] += br["writes_checked"]
        risk["flagged"] += br["flagged"]
        for e in br["ledger"]:
            risk["ledger"].append(dict(e, trace_id=t.trace_id))
        if not br["assessed"]:
            risk["assessed"] = False
            risk["reason"] = br["reason"]
        uf, ui = ufs_mod.assess_and_flag(t)
        findings_by_trace[t.trace_id].extend(uf)
        ufs_infos.append(ui)
    ufs = ufs_mod.aggregate(ufs_infos)

    rep = report.build(traces, findings_by_trace, args.provider,
                       args.framework, api_log_records=api_records,
                       sheets=sheets, include_total_bill=args.total_bill,
                       risk=risk, ufs=ufs)
    rep["audit_wall_seconds"] = time.perf_counter() - t0

    if args.receipt:
        payload = {
            "report": json.loads(report.to_json(rep)),
            "receipts": receipt_mod.issue_all(
                [f for fs in findings_by_trace.values() for f in fs],
                args.provider, priced=rep["dollars_shown"], sheets=sheets),
        }
        text = json.dumps(payload, indent=2)
    elif args.output == "json":
        text = report.to_json(rep)
    else:
        text = report.to_markdown(rep)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


def run_diff(args, sheets, t0):
    """Diff mode: audit before and after, then prove the delta."""
    from . import diff as diffmod

    before_traces = load_traces(args.traces[0], args.fmt)
    after_traces = load_traces(args.traces[1], args.fmt)
    if not before_traces or not after_traces:
        print("no traces parsed from one of the inputs", file=sys.stderr)
        return 1

    api_records = (api_log_mod.load_api_log(args.api_log)
                   if args.api_log else None)

    rep_before, rep_after, diff_obj = diffmod.build_diff(
        before_traces, after_traces, args.provider, args.framework,
        api_log_records=api_records, sheets=sheets,
        include_total_bill=args.total_bill)
    rep_after["audit_wall_seconds"] = time.perf_counter() - t0

    if args.receipt:
        # Receipts describe the current (after) state — the findings you
        # can still act on.
        after_findings = {}
        for t in after_traces:
            after_findings[t.trace_id] = detectors.run_all(t, args.provider)
        payload = {
            "report": json.loads(report.to_json(rep_after, diff=diff_obj)),
            "receipts": receipt_mod.issue_all(
                [f for fs in after_findings.values() for f in fs],
                args.provider, priced=rep_after["dollars_shown"],
                sheets=sheets),
        }
        text = json.dumps(payload, indent=2)
    elif args.output == "json":
        text = report.to_json(rep_after, diff=diff_obj)
    else:
        text = report.to_markdown(rep_after, diff=diff_obj)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
