"""Blind-edit detector — the first RISK flag (not a waste class).

A blind edit is a content-replacing write (full replace or pattern
edit) to a pre-existing file the agent had read only a small fraction
of, as evidenced by the trace itself. Risk flags are never priced:
a blind edit that works costs no tokens — its cost is damage when it
doesn't. Findings ship measurable=False, waste_tokens=0.

Flag tiers:
- direct: a Write/write_file or sed-i-style pattern edit in the trace
  with coverage < COVERAGE_THRESHOLD on a substantial file.
- inferred (per-file): a script execution followed by git output
  naming the file with deletions of pre-existing lines, where reads
  before the execution were shallow. Labeled inferred: the script may
  have read files in ways the trace cannot credit.
- inferred (trace-level): git summaries show deletions vs HEAD after
  script executions, and the files git names in the window were read
  shallowly. Deletions are trace-global at this tier; the split
  between pre-existing lines and the agent's own earlier insertions
  is not determinable, and the finding says so.
- workdir-diff: same rule as per-file inferred, but the write evidence
  comes from a user-supplied before/after diff (--workdir-diff), so it
  is not labeled inferred.

Spec: ~/workspace/chewme-launch/blind-edit-detector-spec.md (v0.2).
Suggested by u/Impressive_Laugh_176 (Reddit).
"""

from .. import coverage
from .base import Finding

DEFINITION = ("blind edit = a content-replacing write to a file the "
              "agent had read only a small fraction of")


def _pct(c):
    return f"{c:.0%}"


def flags_for(trace, assessment):
    findings = []
    for e in assessment.entries:
        base_detail = {k: v for k, v in e.items()}
        if e.get("scope") == "trace":
            a, b = e["modified_between"]
            findings.append(Finding(
                detector="blind_edit",
                trace_id=trace.trace_id,
                step_idx=e["diff_step"],
                waste_tokens=0,
                token_basis="n/a",
                summary=(
                    f"script runs between steps {a}–{b} modified "
                    f"{e['files_changed']} files; diff summaries show "
                    f"{e['global_deletions']} deletions vs HEAD. Of the "
                    f"{len(e['window_files'])} files named in git output "
                    f"in that window, {len(e['shallow_files'])} were "
                    f"read only through their first lines and "
                    f"{len(e['unread_files'])} were never read. "
                    f"Deletions are trace-global: how many were the "
                    f"agent's own earlier insertions is not determinable "
                    f"from the trace."),
                detail=base_detail,
                fix_key="",
                measurable=False,
            ))
            continue
        if e["generated"] or e["outside_workdir"] or not e["pre_existing"] \
                or not e["substantial"] or e["coverage"] is None \
                or e["coverage"] >= coverage.COVERAGE_THRESHOLD:
            continue
        kind = e["write_kind"]
        if kind in ("full_replace", "pattern_edit") and not e["inferred"]:
            label = "full replace" if kind == "full_replace" \
                else "pattern edit"
            findings.append(Finding(
                detector="blind_edit",
                trace_id=trace.trace_id,
                step_idx=e["write_step"],
                waste_tokens=0,
                token_basis="n/a",
                summary=(
                    f"{label} of {e['file']} after reading "
                    f"{e['lines_read']} of ≥{e['lines_evidenced']} "
                    f"evidenced lines ({_pct(e['coverage'])})"),
                detail=base_detail,
                fix_key="",
                measurable=False,
            ))
        elif e["inferred"] or kind == "workdir_diff":
            dels = (e.get("pure_deletions") or 0) \
                + (e.get("changed_lines") or 0)
            if dels < 1:
                continue
            last_step = max((s.step_idx for s in trace.steps), default=0)
            if e["inferred"]:
                a, b = e.get("modified_between") or [e["write_step"],
                                                     e["write_step"]]
                findings.append(Finding(
                    detector="blind_edit",
                    trace_id=trace.trace_id,
                    step_idx=e["diff_step"],
                    waste_tokens=0,
                    token_basis="n/a",
                    summary=(
                        f"(inferred from later git output) {e['file']} "
                        f"was modified between steps {a}–{b} with "
                        f"{e.get('pure_deletions', 0)} pre-existing "
                        f"lines deleted and {e.get('changed_lines', 0)} "
                        f"changed, after the agent had read "
                        f"{e['lines_read']} of ≥{e['lines_evidenced']} "
                        f"evidenced lines ({_pct(e['coverage'])})"),
                    detail=base_detail,
                    fix_key="",
                    measurable=False,
                ))
            else:
                findings.append(Finding(
                    detector="blind_edit",
                    trace_id=trace.trace_id,
                    step_idx=last_step,
                    waste_tokens=0,
                    token_basis="n/a",
                    summary=(
                        f"(from the supplied --workdir-diff) {e['file']}: "
                        f"{e.get('pure_deletions', 0)} pre-existing lines "
                        f"deleted and {e.get('changed_lines', 0)} "
                        f"changed; the trace shows the agent had read "
                        f"{e['lines_read']} of ≥{e['lines_evidenced']} "
                        f"evidenced lines ({_pct(e['coverage'])})"),
                    detail=base_detail,
                    fix_key="",
                    measurable=False,
                ))
    return findings


def assess_and_flag(trace, workdir_diff_text=None):
    """Return (findings, risk dict for the report)."""
    A = coverage.assess(trace, workdir_diff_text=workdir_diff_text)
    findings = flags_for(trace, A) if A.assessed else []
    writes_checked = sum(1 for e in A.entries if e.get("scope") == "file")
    risk = {
        "assessed": A.assessed,
        "reason": A.reason,
        "writes_checked": writes_checked,
        "flagged": len(findings),
        "ledger": A.entries,
    }
    return findings, risk


def run(trace, provider="deepseek", workdir_diff_text=None):
    findings, _ = assess_and_flag(trace, workdir_diff_text)
    return findings
