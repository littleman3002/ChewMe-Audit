#!/usr/bin/env python3
"""Regenerate the 1M-token calibration traces (deterministic).

The calibration trajectories are assembled, not observed: the real
error-loop observation from traces/worked_example/before.jsonl
(byte-identical) repeated to reach exactly 1,000,000 input tokens.

Usage:
    CHEWME_LAB=~/workspace/tokenizer-lab python3 generate.py
Writes before.jsonl / after.jsonl into this directory.

Requires the chewme_audit package importable and the DeepSeek
tokenizer lab path in CHEWME_LAB (same requirement as the CLI).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from chewme_audit.adapters import jsonl as A
from chewme_audit import counting

TARGET_TOKENS = 1_000_000
TRACE_ID = "calibration__dvc-7734-loop-1M::assembled"
HERE = os.path.dirname(os.path.abspath(__file__))
WORKED = os.path.join(HERE, "..", "worked_example")


def norm(s):
    return " ".join(s.split())


def main():
    before = A.load_jsonl(os.path.join(WORKED, "before.jsonl"))
    t = next(x for x in before if "dvc-7734" in x.trace_id)
    loop_text = next(s.text for s in t.steps if "Usage: edit <start_line>" in s.text)
    loop_toks, _ = counting.count(loop_text, "deepseek")

    prefix, suffix, seen = [], [], False
    for s in t.steps:
        if norm(s.text) == norm(loop_text):
            seen = True
            continue
        (prefix if not seen else suffix).append(s.text)
    non_loop = sum(counting.count(x, "deepseek")[0] for x in prefix + suffix)
    n = round((TARGET_TOKENS - non_loop) / loop_toks)

    before_steps = prefix + [loop_text] * n + suffix
    total = sum(counting.count(x, "deepseek")[0] for x in before_steps)
    assert total == TARGET_TOKENS, f"expected {TARGET_TOKENS}, got {total}"

    after = A.load_jsonl(os.path.join(WORKED, "after.jsonl"))
    ta = next(x for x in after if "dvc-7734" in x.trace_id)
    loop_text_a = next(s.text for s in ta.steps
                       if "Usage: edit <start_line>" in s.text)
    rest, seen = [], False
    for s in ta.steps:
        if norm(s.text) == norm(loop_text_a) and not seen:
            seen = True
            continue
        if seen:
            rest.append(s.text)
    after_steps = prefix + [loop_text_a] + rest

    for name, steps in (("before.jsonl", before_steps), ("after.jsonl", after_steps)):
        with open(os.path.join(HERE, name), "w") as fh:
            for i, txt in enumerate(steps, 1):
                fh.write(json.dumps(
                    {"trace_id": TRACE_ID, "step": i, "role": "tool", "text": txt}
                ) + "\n")
    print(f"wrote before.jsonl ({len(before_steps)} steps, {total} tokens)")
    print(f"wrote after.jsonl ({len(after_steps)} steps)")


if __name__ == "__main__":
    main()
