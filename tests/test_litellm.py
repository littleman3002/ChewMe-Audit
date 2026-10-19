"""Tests for the LiteLLM standard-logging-payload adapter."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit.adapters import litellm as ll
from chewme_audit import cli as cli_mod


def _write(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
    return path


def _payload(trace_id, start, messages, response_text=None, tool_calls=None):
    msg = {"role": "assistant", "content": response_text or ""}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "trace_id": trace_id,
        "startTime": start,
        "messages": messages,
        "response": {"choices": [{"message": msg}]},
    }


def test_round_trip_no_double_count():
    # Two payloads: the second payload's message list repeats the first
    # payload's response verbatim. The assistant turn must appear once.
    tc = [{"function": {"name": "Bash", "arguments": '{"command": "ls"}'}}]
    p1 = _payload("t1", 1000,
                  [{"role": "user", "content": "list the files"}],
                  response_text="I'll list them.", tool_calls=tc)
    p2 = _payload("t1", 2000,
                  [{"role": "user", "content": "list the files"},
                   {"role": "assistant", "content": "I'll list them.",
                    "tool_calls": tc},
                   {"role": "tool", "name": "Bash",
                    "content": "a.py\nb.py"}],
                  response_text="Found a.py and b.py.")
    path = _write([p1, p2])
    try:
        traces = ll.load_litellm(path)
    finally:
        os.unlink(path)
    assert len(traces) == 1
    t = traces[0]
    assert t.trace_id == "t1"
    assert len(t.steps) == 4, [s.text[:40] for s in t.steps]
    assert t.steps[0].role == "user" and "list the files" in t.steps[0].text
    assert t.steps[1].role == "assistant"
    assert t.steps[1].tool_name == "Bash"
    assert "I'll list them." in t.steps[1].text
    assert t.steps[2].role == "tool" and t.steps[2].tool_name == "Bash"
    assert "a.py" in t.steps[2].text
    assert t.steps[3].role == "assistant"
    assert "Found a.py" in t.steps[3].text
    # the repeated assistant message must not produce a second step
    assert sum("I'll list them." in s.text for s in t.steps) == 1


def test_groups_by_trace_id_and_orders_by_start_time():
    p_b = _payload("tB", 3000, [{"role": "user", "content": "b2"}],
                   response_text="rb2")
    p_a1 = _payload("tA", 2000,
                    [{"role": "user", "content": "a1"},
                     {"role": "assistant", "content": "ra1"},
                     {"role": "user", "content": "a2"}],
                    response_text="ra2")
    p_a0 = _payload("tA", 1000, [{"role": "user", "content": "a1"}],
                    response_text="ra1")
    path = _write([p_b, p_a1, p_a0])  # out of order on purpose
    try:
        traces = ll.load_litellm(path)
    finally:
        os.unlink(path)
    assert [t.trace_id for t in traces] == ["tB", "tA"]
    ta = traces[1]
    texts = [s.text for s in ta.steps]
    assert texts == ["a1", "ra1", "a2", "ra2"], texts


def test_session_id_fallback_and_file_stem():
    p = _payload(None, 1000, [{"role": "user", "content": "hi"}],
                 response_text="hello")
    del p["trace_id"]
    p["session_id"] = "sess-9"
    path = _write([p])
    try:
        traces = ll.load_litellm(path)
    finally:
        os.unlink(path)
    assert traces[0].trace_id == "sess-9"

    p2 = {"startTime": 1000,
          "messages": [{"role": "user", "content": "hi"}],
          "response": "plain string response"}
    path2 = _write([p2])
    try:
        traces2 = ll.load_litellm(path2)
    finally:
        os.unlink(path2)
    stem = os.path.splitext(os.path.basename(path2))[0]
    assert traces2[0].trace_id == stem
    assert traces2[0].steps[1].text == "plain string response"


def test_skips_blank_and_bad_lines():
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n")
        f.write("not json\n")
        f.write(json.dumps(_payload("t", 1000,
                                    [{"role": "user", "content": "ok"}],
                                    response_text="fine")) + "\n")
    try:
        traces = ll.load_litellm(path)
    finally:
        os.unlink(path)
    assert len(traces) == 1
    assert len(traces[0].steps) == 2


def test_cli_dispatch():
    p = _payload("t", 1000, [{"role": "user", "content": "hi"}],
                 response_text="hello")
    path = _write([p])
    try:
        traces = cli_mod.load_traces(path, "litellm")
    finally:
        os.unlink(path)
    assert len(traces) == 1 and traces[0].trace_id == "t"
