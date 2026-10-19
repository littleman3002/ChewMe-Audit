"""LiteLLM standard-logging-payload adapter.

Reads a JSONL file of LiteLLM standard logging objects — one per LLM
call. Export them with a small custom callback on `success_callback`:

    import json
    import litellm
    from litellm.integrations.custom_logger import CustomLogger

    class JsonlLogger(CustomLogger):
        def log_success_event(self, kwargs, response_obj, start_time,
                              end_time):
            payload = kwargs.get("standard_logging_object")
            if payload:
                with open("litellm_calls.jsonl", "a") as f:
                    f.write(json.dumps(payload, default=str) + "\\n")

    litellm.callbacks = [JsonlLogger()]

One payload becomes the steps for one LLM call in an agent loop.
Payloads are grouped into traces by `trace_id` (fallback: `session_id`,
then `metadata` trace/session id, then one trace per file) and ordered
by `startTime`.

Per payload, only the *new* inbound messages (delta vs the previous
payload's message list) become user/tool/system steps. Assistant turns
are taken from the payload's `response`, not from `messages`: the next
payload's message list repeats the previous response verbatim, so
reading assistant turns from `messages` would double-count them.
"""

import json
import os

from ..model import Step, Trace


def _render_content(content):
    """Render an OpenAI-format message content (str or block list)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(str(b.get("text", "")))
                elif "text" in b:
                    parts.append(str(b["text"]))
                else:
                    parts.append(json.dumps(b, ensure_ascii=False))
            else:
                parts.append(str(b))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _tool_calls_text(msg):
    """Return (text, first_tool_name) for an OpenAI-format tool_calls list."""
    text = ""
    tool_name = ""
    for tc in msg.get("tool_calls") or []:
        fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
        name = str(fn.get("name", ""))
        call_txt = "[%s] %s" % (name or "tool_call", fn.get("arguments", ""))
        text = (text + "\n" + call_txt).strip() if text else call_txt
        if not tool_name:
            tool_name = name
    return text, tool_name


def _steps_for_payload(payload, trace_id, start_idx, seen_msg_count):
    """Return (steps, new_seen_count, next_idx) for one logging payload."""
    steps = []
    idx = start_idx
    messages = payload.get("messages") or []
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]

    # Delta vs the previous payload: only newly appended messages.
    # Assistant messages are skipped on purpose (see module docstring).
    new_messages = messages[seen_msg_count:] \
        if seen_msg_count < len(messages) else []
    for msg in new_messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "user"))
        if role == "assistant":
            continue
        text = _render_content(msg.get("content")).strip()
        tool_name = str(msg.get("name", ""))
        calls_txt, calls_tool = _tool_calls_text(msg)
        if calls_txt:
            text = (text + "\n" + calls_txt).strip() if text else calls_txt
            tool_name = tool_name or calls_tool
        if text:
            steps.append(Step(trace_id, idx, text, role=role,
                              tool_name=tool_name))
            idx += 1
    seen = len(messages)

    # The model's response for this call.
    resp = payload.get("response")
    rtext = ""
    r_tool = ""
    if isinstance(resp, dict):
        choices = resp.get("choices") or []
        if choices and isinstance(choices[0], dict):
            m = choices[0].get("message") or {}
            rtext = _render_content(m.get("content")).strip()
            calls_txt, calls_tool = _tool_calls_text(m)
            if calls_txt:
                rtext = (rtext + "\n" + calls_txt).strip() \
                    if rtext else calls_txt
                r_tool = calls_tool
    elif isinstance(resp, str):
        rtext = resp.strip()
    if rtext:
        steps.append(Step(trace_id, idx, rtext, role="assistant",
                          tool_name=r_tool))
        idx += 1
    return steps, seen, idx


def _trace_key(payload):
    for k in ("trace_id", "session_id"):
        v = payload.get(k)
        if v:
            return str(v)
    md = payload.get("metadata") or {}
    for k in ("trace_id", "session_id"):
        v = md.get(k)
        if v:
            return str(v)
    return ""


def load_litellm(path):
    """Return [Trace] from a JSONL of LiteLLM standard logging objects."""
    payloads = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                payloads.append(obj)

    groups = {}
    order = []
    for p in payloads:
        key = _trace_key(p) or "__single__"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)

    traces = []
    for key in order:
        g = sorted(groups[key], key=lambda p: p.get("startTime") or 0)
        trace_id = key if key != "__single__" else os.path.splitext(
            os.path.basename(path))[0]
        steps = []
        seen = 0
        idx = 0
        for p in g:
            new_steps, seen, idx = _steps_for_payload(p, trace_id, idx, seen)
            steps.extend(new_steps)
        trace = Trace(trace_id=trace_id)
        trace.steps = steps
        traces.append(trace)
    return traces
