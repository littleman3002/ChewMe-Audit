"""Langfuse export adapter.

Reads a Langfuse trace export (JSON array or JSONL of trace objects).
Expected shape per trace: {"id": ..., "observations": [{"id": ...,
"type": "GENERATION"|"SPAN"|..., "input": ..., "output": ...,
"name": ...}, ...]}.
Tool results are taken from observation outputs; generations contribute
their input+output as assistant steps. Anything else is best-effort.
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


def load_langfuse(path):
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
        idx = 0
        for ob in obj.get("observations", []) or []:
            otype = str(ob.get("type", "")).upper()
            name = str(ob.get("name", ""))
            if otype == "GENERATION":
                txt = _text_of(ob.get("input")) + "\n" + _text_of(ob.get("output"))
                trace.steps.append(Step(tid, idx, txt, role="assistant"))
            else:
                txt = _text_of(ob.get("output")) or _text_of(ob.get("input"))
                if txt.strip():
                    trace.steps.append(Step(tid, idx, txt, role="tool",
                                            tool_name=name))
            idx += 1
        if trace.steps:
            traces.append(trace)
    return traces
