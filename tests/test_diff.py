"""Tests for diff mode: before/after comparison.

Covers the three-question contract (net change / disappeared / remains),
trace alignment (trace_id + order fallback), and the fix classification
(resolved / reduced / new / unchanged).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import diff as diffmod
from chewme_audit import counting as counting_mod
from chewme_audit import report
from chewme_audit.model import Step, Trace

# Tests run without the lab's provider tokenizers; force a priceable
# basis so dollar assertions hold. Pricing logic is basis-independent.
_basis = counting_mod.PRICEABLE.copy().pop()
counting_mod.count = lambda text, provider="deepseek": (len(text) // 4, _basis)

ERROR_TEXT = ("Error: timeout waiting for tool result after 30s "
              "(retry with backoff) " * 4)
OVERSIZED_TEXT = ("x" * 100 + "DISTINCTIVEVALUE001 " * 120)  # >2KB, unreferenced
NEW_CALL_TEXT = ("status check: all systems nominal, queue depth 0 " * 4)


def _steps(texts, trace_id):
    return [Step(trace_id, i, t) for i, t in enumerate(texts)]


def _before_after():
    before = Trace("task-1", _steps(
        [ERROR_TEXT] * 4          # error loop -> error_loop_dedup
        + [OVERSIZED_TEXT]       # oversized, unreferenced
        + ["final answer: done"],
        "task-1"))
    after = Trace("task-1", _steps(
        [ERROR_TEXT]             # loop fixed: single occurrence
        + ["final answer: done"]  # oversized output gone
        + [NEW_CALL_TEXT] * 3,   # NEW repeated call introduced
        "task-1"))
    return before, after


def _build(before_traces, after_traces, **kw):
    return diffmod.build_diff(before_traces, after_traces, "deepseek",
                              framework="generic", **kw)


def test_net_delta_negative():
    b, a = _before_after()
    _, _, d = _build([b], [a])
    assert d["waste_tokens_delta"] < 0, d["waste_tokens_delta"]
    assert d["waste_dollars_delta"] is not None
    assert d["waste_dollars_delta"] < 0


def test_error_loop_resolved_and_new_call_classified_new():
    b, a = _before_after()
    _, _, d = _build([b], [a])
    resolved_keys = {(e["detector"], e["fix_key"]) for e in d["resolved"]}
    assert ("repeated_calls", "error_loop_dedup") in resolved_keys, d["resolved"]
    new_keys = {(e["detector"], e["fix_key"]) for e in d["new"]}
    assert ("repeated_calls", "memoize_repeated_call") in new_keys, d["new"]
    # oversized output gone too
    assert any(e["detector"] == "oversized_unreferenced" for e in d["resolved"])


def test_reduced_classification():
    # same class, waste down >10% but not gone -> reduced
    b = Trace("t", _steps([ERROR_TEXT] * 6, "t"))
    a = Trace("t", _steps([ERROR_TEXT] * 2, "t"))
    _, _, d = _build([b], [a])
    reduced = {(e["detector"], e["fix_key"]): e for e in d["reduced"]}
    key = ("repeated_calls", "error_loop_dedup")
    assert key in reduced, d["reduced"]
    assert reduced[key]["reduction_pct"] > 0.10
    # surviving fix key -> re-surfaced as not fully applied
    assert any(n["fix_key"] == "error_loop_dedup"
               for n in d["not_fully_applied"])


def test_unchanged_classification():
    b = Trace("t", _steps([ERROR_TEXT] * 3, "t"))
    a = Trace("t", _steps([ERROR_TEXT] * 3, "t"))
    _, _, d = _build([b], [a])
    assert d["waste_tokens_delta"] == 0
    assert any(e["status"] == "unchanged" for e in d["unchanged"])


def test_alignment_by_trace_id():
    b1 = Trace("alpha", _steps(["x"], "alpha"))
    b2 = Trace("beta", _steps(["y"], "beta"))
    a2 = Trace("beta", _steps(["y"], "beta"))
    a1 = Trace("alpha", _steps(["x"], "alpha"))
    pairs, ub, ua, method = diffmod.align_traces([b1, b2], [a2, a1])
    assert method == "trace_id"
    assert [(b.trace_id, a.trace_id) for b, a in pairs] == [
        ("alpha", "alpha"), ("beta", "beta")]
    assert ub == [] and ua == []


def test_alignment_order_fallback():
    # id-less traces (bare observations get fallback ids, but here we
    # force the fallback path with duplicate ids)
    b1 = Trace("dup", _steps(["x"], "dup"))
    b2 = Trace("dup", _steps(["y"], "dup"))
    a1 = Trace("dup", _steps(["x"], "dup"))
    pairs, ub, ua, method = diffmod.align_traces([b1, b2], [a1])
    assert method == "order"
    assert len(pairs) == 1
    assert pairs[0][0] is b1 and pairs[0][1] is a1
    assert ub == ["dup"] and ua == []  # never silently dropped


def test_alignment_unmatched_listed():
    b = Trace("gone", _steps(["x"], "gone"))
    a = Trace("fresh", _steps(["y"], "fresh"))
    pairs, ub, ua, method = diffmod.align_traces([b], [a])
    assert pairs == []
    assert ub == ["gone"] and ua == ["fresh"]


def test_diff_markdown_answers_three_questions():
    b, a = _before_after()
    _, rep_after, d = _build([b], [a])
    md = report.to_markdown(rep_after, diff=d)
    assert "## 1) Net change" in md
    assert "## 2) What disappeared / shrank" in md
    assert "## 3) What remains or got worse" in md
    assert "Resolved" in md and "New" in md


def test_diff_json_has_structured_fields():
    import json
    b, a = _before_after()
    _, rep_after, d = _build([b], [a])
    out = json.loads(report.to_json(rep_after, diff=d))
    assert "diff" in out
    dd = out["diff"]
    assert dd["waste_tokens_delta"] < 0
    assert isinstance(dd["resolved"], list)
    assert isinstance(dd["new"], list)
    assert dd["alignment"]["method"] == "trace_id"
    # honesty labels survive
    assert any("alignment" in lab for lab in dd["labels"])
