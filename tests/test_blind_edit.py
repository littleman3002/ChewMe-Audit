"""Blind-edit detector tests: §6 controls on the real traces + fixtures."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import coverage as C
from chewme_audit.adapters import claude_code as cc_adapter
from chewme_audit.adapters import jsonl as jsonl_adapter
from chewme_audit.detectors import blind_edit
from chewme_audit.model import Step, Trace

LIVE = os.path.join(os.path.dirname(__file__), "..", "traces", "live_runs")


def _flags(fname):
    traces = jsonl_adapter.load_jsonl(os.path.join(LIVE, fname))
    out = []
    for t in traces:
        f, _ = blind_edit.assess_and_flag(t)
        out.extend(f)
    return out


def test_agent1_trace_level_flag_fires():
    flags = _flags("trace_4agent_1.jsonl")
    assert len(flags) == 1, [f.summary for f in flags]
    f = flags[0]
    assert f.measurable is False and f.waste_tokens == 0
    d = f.detail
    assert d["scope"] == "trace" and d["inferred"] is True
    assert d["global_deletions"] == 117
    a, b = d["modified_between"]
    assert a < b == f.step_idx  # step-range attribution, diff step last
    assert d["shallow_files"], "expected head-only-read files named"
    assert "not determinable" in f.summary  # baseline caveat in wording


def test_clean_traces_have_no_flags():
    for fn in ("trace.jsonl", "trace_4agent_2.jsonl",
               "trace_4agent_3.jsonl", "trace_4agent_4.jsonl",
               "trace_debug2.jsonl"):
        flags = _flags(fn)
        assert flags == [], (fn, [f.summary for f in flags])


def test_debug_clobber_not_flagged_full_read_first():
    # Negative control: the agent read cache.py (as returned) before
    # overwriting it — carelessness, not blindness.
    assert _flags("trace_debug.jsonl") == []


def _call(tool, args):
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


def _trace(pairs):
    t = Trace(trace_id="t")
    t.steps = [Step("t", i, text, role=role) for i, (role, text)
               in enumerate(pairs)]
    return t


def test_pattern_edit_flagged():
    t = _trace([
        ("assistant", _call("run_bash", {"cmd": "wc -l big.py"})),
        ("tool", "[run_bash]\n[exit 0]\n500 big.py"),
        ("assistant", _call("run_bash", {"cmd": "head -5 big.py"})),
        ("tool", "[run_bash]\n[exit 0]\nl1\nl2\nl3\nl4\nl5"),
        ("assistant", _call("run_bash",
                            {"cmd": "sed -i 's/foo/bar/g' big.py"})),
        ("tool", "[run_bash]\n[exit 0]\n"),
    ])
    flags, risk = blind_edit.assess_and_flag(t)
    assert len(flags) == 1
    assert "pattern edit" in flags[0].summary
    assert risk["writes_checked"] == 1 and risk["flagged"] == 1


def test_created_file_rewrite_not_flagged():
    body = "\n".join("x" for _ in range(100))
    t = _trace([
        ("assistant", _call("write_file",
                            {"path": "new.py", "content": body})),
        ("tool", "[write_file] wrote new.py"),
        ("assistant", _call("write_file",
                            {"path": "new.py", "content": body})),
        ("tool", "[write_file] wrote new.py"),
    ])
    flags, _ = blind_edit.assess_and_flag(t)
    assert flags == []


def test_claude_code_direct_blind_write_flagged():
    lines = [
        {"type": "user", "sessionId": "s",
         "message": {"role": "user", "content": "rewrite big.py"}},
        {"type": "assistant", "sessionId": "s",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Bash",
              "input": {"command": "wc -l src/big.py"}}]}},
        {"type": "user", "sessionId": "s",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1",
              "content": "300 src/big.py"}]}},
        {"type": "assistant", "sessionId": "s",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t2", "name": "Read",
              "input": {"file_path": "src/big.py", "offset": 1,
                        "limit": 3}}]}},
        {"type": "user", "sessionId": "s",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t2",
              "content": "a\nb\nc"}]}},
        {"type": "assistant", "sessionId": "s",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t3", "name": "Write",
              "input": {"file_path": "src/big.py",
                        "content": "\n".join("x" for _ in range(300))}}]}},
        {"type": "user", "sessionId": "s",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t3",
              "content": "ok"}]}},
    ]
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
    try:
        traces = cc_adapter.load_claude_code(path)
    finally:
        os.unlink(path)
    flags, risk = blind_edit.assess_and_flag(traces[0])
    assert risk["assessed"] is True
    assert len(flags) == 1, [f.summary for f in flags]
    assert "full replace" in flags[0].summary
    assert flags[0].detail["coverage"] < 0.25


def test_unassessed_without_tool_inputs():
    t = _trace([("tool", "just an observation"),
                ("tool", "another one")])
    flags, risk = blind_edit.assess_and_flag(t)
    assert flags == []
    assert risk["assessed"] is False
    assert "could not be assessed" in risk["reason"]
