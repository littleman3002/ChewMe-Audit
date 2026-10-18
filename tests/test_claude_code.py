"""Tests for the Claude Code CLI transcript adapter."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit.adapters import claude_code as cc


def _write(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
    return path


def test_round_trip_tool_use_and_result():
    lines = [
        {"type": "user", "sessionId": "sess-1",
         "message": {"role": "user", "content": "list the files"}},
        {"type": "assistant", "sessionId": "sess-1",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "I'll list them."},
             {"type": "tool_use", "id": "tu_1", "name": "Bash",
              "input": {"command": "ls"}}]}},
        {"type": "user", "sessionId": "sess-1",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "tu_1",
              "content": "a.py\nb.py"}]}},
        {"type": "result", "sessionId": "sess-1", "subtype": "success"},
        {"type": "system", "sessionId": "sess-1", "subtype": "init"},
    ]
    path = _write(lines)
    try:
        traces = cc.load_claude_code(path)
    finally:
        os.unlink(path)
    assert len(traces) == 1
    t = traces[0]
    assert t.trace_id == "sess-1"
    # user text, assistant text, tool_use call, tool_result = 4 steps;
    # result/system lines skipped
    assert len(t.steps) == 4, [s.text[:40] for s in t.steps]
    assert t.steps[0].role == "user" and "list the files" in t.steps[0].text
    assert t.steps[1].role == "assistant"
    assert t.steps[2].tool_name == "Bash" and "ls" in t.steps[2].text
    assert t.steps[3].role == "tool"
    assert t.steps[3].tool_name == "Bash"  # id -> name mapped
    assert "a.py" in t.steps[3].text


def test_repeated_tool_results_detectable():
    # Same observation twice -> repeated_calls should fire downstream.
    res = {"type": "user", "sessionId": "s",
           "message": {"role": "user", "content": [
               {"type": "tool_result", "tool_use_id": "t1",
                "content": "x" * 3000}]}}
    lines = [
        {"type": "assistant", "sessionId": "s",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Read",
              "input": {"path": "f"}}]}},
        res, res,
    ]
    path = _write(lines)
    try:
        traces = cc.load_claude_code(path)
    finally:
        os.unlink(path)
    tools = [s for s in traces[0].steps if s.role == "tool"]
    assert len(tools) == 2
    assert tools[0].text == tools[1].text


def test_malformed_lines_skipped():
    path = _write([
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "hi"}]}},
        "not json at all",
        {"type": "assistant", "message": {}},
        42,
    ])
    try:
        traces = cc.load_claude_code(path)
    finally:
        os.unlink(path)
    assert len(traces[0].steps) == 1
    # falls back to file stem when no sessionId
    assert traces[0].trace_id == os.path.splitext(
        os.path.basename(path))[0]
