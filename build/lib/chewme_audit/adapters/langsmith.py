"""LangSmith export adapter.

Reads a LangSmith run export (JSON array or JSONL of run objects).
Expected shape per run: {"id": ..., "name": ..., "run_type": "tool"|...,
"inputs": ..., "outputs": ..., "child_runs": [...]}.
Runs are flattened depth-first; tool runs contribute their outputs as
tool steps, llm runs contribute inputs+outputs as assistant steps.
"""

import json

from ..model import Step, Trace


def _text_of(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _flatten(run, trace, idx):
    rtype = str(run.get("run_type", "")).lower()
    name = str(run.get("name", ""))
    if rtype == "tool":
        txt = _text_of(run.get("outputs")) or _text_of(run.get("inputs"))
        if txt.strip():
            trace.steps.append(Step(trace.trace_id, idx[0], txt,
                                    role="tool", tool_name=name))
            idx[0] += 1
    elif rtype in ("llm", "chain"):
        txt = _text_of(run.get("inputs"))
        out = _text_of(run.get("outputs"))
        if out.strip():
            txt += "\n" + out
        if txt.strip():
            trace.steps.append(Step(trace.trace_id, idx[0], txt,
                                    role="assistant"))
            idx[0] += 1
    for child in run.get("child_runs", []) or []:
        _flatten(child, trace, idx)


def load_langsmith(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    objs = []
    if raw.startswith("["):
        objs = json.loads(raw)
    else:
        for line in raw.splitlines():
            line = line.strip()
            if line:
                objs.append(json.loads(line))
    traces = []
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        tid = str(obj.get("id", obj.get("trace_id", "trace-?")))
        trace = Trace(trace_id=tid)
        _flatten(obj, trace, [0])
        if trace.steps:
            traces.append(trace)
    return traces
