"""Generic JSONL adapter.

Accepted line shapes (auto-detected per line):
  1. Generic: {"trace_id": ..., "step": N | "step_idx": N,
                "text": ... | "content": ... | "observation": ...,
                "role": ..., "tool_name": ...}
  2. Nebius/SWE-agent style: {"traj_id": ..., "step_idx": N, "text": ...}
  3. Bare observation: {"text": ...}  -> grouped into one trace "trace-0"
"""

import json

from ..model import Step, Trace


def _coerce_step(obj, fallback_trace, fallback_idx):
    if not isinstance(obj, dict):
        return None, fallback_trace, fallback_idx
    trace_id = (obj.get("trace_id") or obj.get("traj_id")
                or obj.get("trajectory_id") or fallback_trace)
    step_idx = obj.get("step", obj.get("step_idx", fallback_idx))
    text = obj.get("text", obj.get("content", obj.get("observation", "")))
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return None, trace_id, fallback_idx
    step = Step(
        trace_id=str(trace_id),
        step_idx=int(step_idx) if isinstance(step_idx, int) else fallback_idx,
        text=text,
        role=str(obj.get("role", "tool")),
        tool_name=str(obj.get("tool_name", obj.get("tool", ""))),
    )
    return step, str(trace_id), fallback_idx + 1


def load_jsonl(path):
    """Return list[Trace] from a JSONL file."""
    by_trace = {}
    order = []
    fallback_trace = "trace-0"
    fallback_idx = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            step, tid, fallback_idx = _coerce_step(obj, fallback_trace, fallback_idx)
            if step is None:
                continue
            if tid not in by_trace:
                by_trace[tid] = Trace(trace_id=tid)
                order.append(tid)
            by_trace[tid].steps.append(step)
    traces = [by_trace[tid] for tid in order]
    for t in traces:
        t.steps.sort(key=lambda s: s.step_idx)
    return traces
