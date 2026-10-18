"""Claude Code CLI transcript adapter.

Reads a Claude Code session transcript (~/.claude/projects/<slug>/<session>.jsonl).
Line shapes (per current CLI format):
  {"type": "assistant", "message": {"content": [{"type": "text", "text": ...},
   {"type": "tool_use", "id": ..., "name": ..., "input": {...}}]}, ...}
  {"type": "user", "message": {"content": "plain text"}}  -> user step
  {"type": "user", "message": {"content": [{"type": "tool_result",
   "tool_use_id": ..., "content": ...}]}}  -> tool steps
  {"type": "result" | "system" | "summary", ...}  -> skipped (session metadata)

One file becomes one Trace (trace_id = sessionId when present, else the
file stem). tool_use ids are mapped back to names so tool_result steps
carry their tool name.
"""

import json
import os

from ..model import Step, Trace


def _block_text(block):
    """Render a content block's text payload as a string."""
    if block is None:
        return ""
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        c = block.get("content", "")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts = []
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(str(b.get("text", "")))
                else:
                    parts.append(_block_text(b))
            return "\n".join(p for p in parts if p)
        try:
            return json.dumps(c, ensure_ascii=False)
        except Exception:
            return str(c)
    if isinstance(block, list):
        return "\n".join(p for p in (_block_text(b) for b in block) if p)
    return str(block)


def load_claude_code(path):
    """Return [Trace] from a Claude Code transcript JSONL file."""
    stem = os.path.splitext(os.path.basename(path))[0]
    trace_id = stem
    steps = []
    tool_names = {}  # tool_use id -> tool name, for labeling results later
    idx = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if not trace_id or trace_id == stem:
                sid = obj.get("sessionId")
                if sid:
                    trace_id = str(sid)
            ltype = obj.get("type")
            msg = obj.get("message") or {}
            content = msg.get("content")

            if ltype == "assistant":
                blocks = content if isinstance(content, list) else [content]
                for b in blocks:
                    if not isinstance(b, dict):
                        if _block_text(b).strip():
                            steps.append(Step(trace_id, idx, _block_text(b),
                                              role="assistant"))
                            idx += 1
                        continue
                    btype = b.get("type")
                    if btype == "text":
                        txt = str(b.get("text", ""))
                        if txt.strip():
                            steps.append(Step(trace_id, idx, txt,
                                              role="assistant"))
                            idx += 1
                    elif btype == "tool_use":
                        name = str(b.get("name", ""))
                        if b.get("id"):
                            tool_names[str(b["id"])] = name
                        try:
                            inp = json.dumps(b.get("input"),
                                             ensure_ascii=False)
                        except Exception:
                            inp = str(b.get("input"))
                        txt = ("[%s] %s" % (name, inp)).strip() if name \
                            else inp
                        if txt.strip():
                            steps.append(Step(trace_id, idx, txt,
                                              role="assistant",
                                              tool_name=name))
                            idx += 1
            elif ltype == "user":
                blocks = content if isinstance(content, list) else [content]
                for b in blocks:
                    if not isinstance(b, dict):
                        txt = _block_text(b)
                        if txt.strip():
                            steps.append(Step(trace_id, idx, txt,
                                              role="user"))
                            idx += 1
                        continue
                    if b.get("type") == "tool_result":
                        name = tool_names.get(str(b.get("tool_use_id", "")),
                                              "")
                        txt = _block_text(b.get("content"))
                        if txt.strip():
                            label = ("[%s result] " % name) if name else ""
                            steps.append(Step(trace_id, idx, label + txt,
                                              role="tool", tool_name=name))
                            idx += 1
                    elif b.get("type") == "text":
                        txt = str(b.get("text", ""))
                        if txt.strip():
                            steps.append(Step(trace_id, idx, txt,
                                              role="user"))
                            idx += 1
            # "result", "system", "summary": session metadata, not I/O.

    trace = Trace(trace_id=trace_id)
    trace.steps = steps
    return [trace]
