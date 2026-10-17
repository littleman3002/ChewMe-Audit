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
  - API log: JSONL of per-request usage with cache hit/miss split
    (see api_log.py for accepted shapes)
"""

import argparse
import json
import sys

from . import api_log as api_log_mod
from . import detectors, receipt as receipt_mod, report
from . import fixes as fixlib
from .adapters import jsonl as jsonl_adapter
from .adapters import langfuse as langfuse_adapter
from .adapters import langsmith as langsmith_adapter


def load_traces(path, fmt):
    if fmt == "langfuse":
        return langfuse_adapter.load_langfuse(path)
    if fmt == "langsmith":
        return langsmith_adapter.load_langsmith(path)
    return jsonl_adapter.load_jsonl(path)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="chewme-audit",
        description="Audit agent traces for fixable cost waste.")
    ap.add_argument("traces", help="trace file (JSONL, Langfuse or LangSmith export)")
    ap.add_argument("--provider", default="deepseek",
                    help="deepseek (default) | grok | xai")
    ap.add_argument("--format", default="jsonl", dest="fmt",
                    choices=["jsonl", "langfuse", "langsmith"],
                    help="input format (default: jsonl)")
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
                          "labeled estimated."))
    ap.add_argument("--out", default=None,
                    help="write report to file instead of stdout")
    args = ap.parse_args(argv)

    traces = load_traces(args.traces, args.fmt)
    if not traces:
        print("no traces parsed from input", file=sys.stderr)
        return 1

    api_records = (api_log_mod.load_api_log(args.api_log)
                   if args.api_log else None)

    findings_by_trace = {}
    for t in traces:
        findings_by_trace[t.trace_id] = detectors.run_all(t, args.provider)

    rep = report.build(traces, findings_by_trace, args.provider,
                       args.framework, api_log_records=api_records)

    if args.receipt:
        payload = {
            "report": json.loads(report.to_json(rep)),
            "receipts": receipt_mod.issue_all(
                [f for fs in findings_by_trace.values() for f in fs],
                args.provider, priced=rep["dollars_shown"]),
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


if __name__ == "__main__":
    raise SystemExit(main())
