"""API-log adapter: exact cache accounting from provider request logs.

When the user hands us their provider API logs (per-request usage with
cache hit/miss split), dollar figures use EXACT cache accounting.
Without it, the tool estimates and labels every figure as estimated.

Accepted JSONL shapes (one record per request, auto-detected):
  1. Generic: {"request_id": ..., "trace_id": ..., "step": N,
                "prompt_tokens": P, "cached_tokens": C,
                "completion_tokens": O}
  2. OpenAI-style: {"id": ..., "usage": {"prompt_tokens": P,
       "completion_tokens": O, "prompt_tokens_details": {"cached_tokens": C}},
       "metadata": {"trace_id": ..., "step": N}}
     (trace_id/step fall back to request order when absent)

Records are joined to trace steps by (trace_id, step_idx); unmatched
records are ignored, unmatched steps fall back to estimation (labeled).
"""

import json
from dataclasses import dataclass


@dataclass
class RequestUsage:
    request_id: str
    trace_id: str
    step_idx: int
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def load_api_log(path):
    """Return list[RequestUsage] from a JSONL API log."""
    records = []
    order = 0
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
            usage = obj.get("usage", obj)
            prompt = _int(usage.get("prompt_tokens",
                                    obj.get("prompt_tokens", 0)))
            cached = _int((usage.get("prompt_tokens_details") or {}).get(
                "cached_tokens", obj.get("cached_tokens", 0)))
            completion = _int(usage.get("completion_tokens",
                                        obj.get("completion_tokens", 0)))
            meta = obj.get("metadata", {}) if isinstance(
                obj.get("metadata"), dict) else {}
            trace_id = str(obj.get("trace_id", meta.get("trace_id",
                                                        f"request-{order}")))
            step = obj.get("step", obj.get("step_idx", meta.get("step", order)))
            records.append(RequestUsage(
                request_id=str(obj.get("request_id", obj.get("id", f"req-{order}"))),
                trace_id=trace_id,
                step_idx=_int(step, order),
                prompt_tokens=prompt,
                cached_tokens=min(cached, prompt),
                completion_tokens=completion,
            ))
            order += 1
    return records


def index_by_step(records):
    """{(trace_id, step_idx): RequestUsage}."""
    return {(r.trace_id, r.step_idx): r for r in records}
