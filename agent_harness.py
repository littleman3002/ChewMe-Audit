#!/usr/bin/env python3
"""Minimal ReAct agent harness for the live 1M-token waste measurement.

Real agent, real billed DeepSeek traffic, no waste-reducing tricks.
Every assistant message and tool result is recorded verbatim to a
JSONL trace for later audit.

Usage:
    CHEWME_LAB=~/workspace/tokenizer-lab python3 agent_harness.py \
        --workdir /tmp/agentrun/django --task-file task.txt \
        --trace /tmp/agentrun/trace.jsonl --budget 1000000
"""
import argparse
import json
import os
import secrets
import subprocess
import sys

sys.path.insert(0, "/home/hatch/workspace/custom-connectors/custom.deepseek/bin")
sys.path.insert(0, "/home/hatch/workspace/chewme-audit")
from ds_call import _post
from chewme_audit import counting

MODEL = "deepseek-chat"
TEMPERATURE = 0.2
MAX_TOKENS_STEP = 1024
CTX_SOFT = 45000          # summarize history beyond this (tokens)
RECENT_STEPS = 12         # verbatim recent steps kept in context
SUMMARY_EVERY = 20        # refresh rolling summary every N steps
HARD_CAP_MULT = 1.2

SYSTEM = """You are a coding agent working in a Linux checkout at {workdir}.
You have three tools. To use one, reply with ONLY a JSON code block:

```json
{{"tool": "run_bash", "args": {{"cmd": "..."}}}}
```
```json
{{"tool": "read_file", "args": {{"path": "..."}}}}
```
```json
{{"tool": "write_file", "args": {{"path": "...", "content": "..."}}}}
```

Paths are relative to the workdir. Keep commands safe and read-only
except for the files your task asks you to change. Work steadily,
one tool call per reply. When the task is fully done, reply:
TASK COMPLETE: <one-line summary>
Do not chat, explain, or ask questions — act."""

# Canary seeding (canary-check spec v0.2, section 3c — exact wording,
# with the run's tag substituted). Appended to the task prompt for
# seeded runs only; unseeded runs are byte-identical to before.
CANARY_RULE = (
    "\n\nCanary rule: begin every reply that contains prose with a line "
    "containing only `CANARY {tag} <n>`, where {tag} is the tag in "
    "your seed line and <n> counts your prose replies — 1 for your "
    "first reply with prose, increasing by 1 on each later reply "
    "with prose. A reply that is only tool calls, with no prose, "
    "carries no canary and does not increment the count. Never put "
    "the canary line in files, code, or commands — only as the first "
    "line of your reply text.")


def count_toks(text):
    n, _ = counting.count(text, "deepseek")
    return n


class Harness:
    def __init__(self, workdir, task, trace_path, budget, trace_id=None,
                 canary_tag=None):
        self.workdir = os.path.abspath(workdir)
        self.task = task
        self.canary_tag = canary_tag
        if canary_tag:
            self.task = task.rstrip() + CANARY_RULE.format(tag=canary_tag)
        self.trace_path = trace_path
        self.budget = budget
        self.trace_id = trace_id or "live__django-docstrings::deepseek-chat::1M"
        self.step_no = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.billed_in = 0
        self.billed_out = 0
        self.history = []          # (role, text) for context
        self.summary = "(no progress yet)"
        self.fh = open(trace_path, "w")

    def log(self, role, text):
        self.step_no += 1
        self.history.append((role, text))
        self.fh.write(json.dumps({
            "trace_id": self.trace_id, "step": self.step_no,
            "role": role, "text": text}) + "\n")
        self.fh.flush()

    def run_tool(self, tool, args):
        try:
            if tool == "run_bash":
                p = subprocess.run(args["cmd"], shell=True, cwd=self.workdir,
                                   capture_output=True, text=True, timeout=120)
                out = (p.stdout or "") + (p.stderr or "")
                return f"[exit {p.returncode}]\n" + out[:8000]
            if tool == "read_file":
                p = os.path.join(self.workdir, args["path"])
                with open(p) as fh:
                    return fh.read()[:12000]
            if tool == "write_file":
                p = os.path.join(self.workdir, args["path"])
                assert os.path.abspath(p).startswith(self.workdir), "path escape"
                with open(p, "w") as fh:
                    fh.write(args["content"])
                return f"wrote {args['path']} ({len(args['content'])} chars)"
            return f"unknown tool: {tool}"
        except Exception as e:
            return f"tool error: {type(e).__name__}: {e}"

    def api(self, messages, max_tokens=MAX_TOKENS_STEP, temperature=TEMPERATURE):
        resp = _post("/chat/completions", {
            "model": MODEL, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens})
        u = resp["usage"]
        self.billed_in += u["prompt_tokens"]
        self.billed_out += u.get("completion_tokens", 0)
        return resp["choices"][0]["message"]["content"], u["prompt_tokens"]

    def context_messages(self):
        # Estimate; summarize if too long.
        recent = self.history[-RECENT_STEPS:]
        body = "".join(f"\n[{r}]\n{t}\n" for r, t in recent)
        if count_toks(body) > CTX_SOFT:
            self.refresh_summary()
            recent = self.history[-RECENT_STEPS:]
            body = "".join(f"\n[{r}]\n{t}\n" for r, t in recent)
        return [
            {"role": "system", "content": SYSTEM.format(workdir=self.workdir)},
            {"role": "user", "content":
             f"TASK:\n{self.task}\n\nPROGRESS SO FAR:\n{self.summary}"
             f"\n\nRECENT HISTORY:{body}\n\nYour next single tool call:"},
        ]

    def refresh_summary(self):
        full = "".join(f"\n[{r}]\n{t}\n" for r, t in self.history)
        text, _ = self.api([
            {"role": "system", "content": "Summarize agent progress."},
            {"role": "user", "content":
             "Summarize what the agent has accomplished so far (files done, "
             "current position, any blockers). Be concise, under 400 words.\n\n"
             + full[:60000]}],
            max_tokens=500, temperature=0.0)
        self.summary = text
        # keep only recent verbatim for context; trace keeps everything
        self.history = self.history[-RECENT_STEPS:]

    def parse_tool(self, text):
        start = text.find("```json")
        if start == -1:
            start = text.find("{")
            if start == -1:
                return None
            end = text.rfind("}") + 1
        else:
            start = text.find("{", start)
            end = text.find("```", start)
            end = len(text) if end == -1 else end
        try:
            obj = json.loads(text[start:end])
            if isinstance(obj, dict) and "tool" in obj:
                return obj["tool"], obj.get("args", {})
        except Exception:
            pass
        return None

    def run(self):
        if self.canary_tag:
            # Seed line: harness-written, system role, trace index 0
            # (canary-check spec v0.2 section 3c).
            self.log("system",
                     f"CANARY-SEED tag={self.canary_tag} anchor=start "
                     "counter=prose-replies")
        self.log("assistant", f"TASK START: {self.task}")
        steps = 0
        while True:
            msgs = self.context_messages()
            prompt_toks = sum(count_toks(m["content"]) for m in msgs)
            if self.input_tokens + prompt_toks > self.budget * HARD_CAP_MULT:
                self.log("assistant", "BUDGET CAP REACHED — stopping.")
                break
            reply, used = self.api(msgs)
            self.input_tokens += used
            self.output_tokens += count_toks(reply)
            self.log("assistant", reply)
            steps += 1
            if "TASK COMPLETE" in reply:
                break
            parsed = self.parse_tool(reply)
            if not parsed:
                self.log("tool", "no parseable tool call — reply with a JSON tool call or TASK COMPLETE")
                continue
            tool, args = parsed
            result = self.run_tool(tool, args)
            self.log("tool", f"[{tool}]\n{result}")
            if steps % SUMMARY_EVERY == 0:
                self.refresh_summary()
            if self.input_tokens >= self.budget:
                self.log("assistant", "TOKEN BUDGET REACHED — stopping.")
                break
        self.fh.close()
        return {
            "steps": steps, "trace_steps": self.step_no,
            "input_tokens_local": self.input_tokens,
            "billed_in": self.billed_in, "billed_out": self.billed_out,
            "canary_tag": self.canary_tag,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--task-file", required=True)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--budget", type=int, default=1000000)
    ap.add_argument("--trace-id", default=None)
    ap.add_argument("--canary", action="store_true",
                    help="seed this run with a canary (random 6-hex tag)")
    a = ap.parse_args()
    task = open(a.task_file).read()
    tag = secrets.token_hex(3) if a.canary else None
    h = Harness(a.workdir, task, a.trace, a.budget, trace_id=a.trace_id,
                canary_tag=tag)
    stats = h.run()
    print(json.dumps(stats, indent=1))
    # deepseek-chat off-peak $0.27/M in, $1.10/M out (standard sheet)
    cost = stats["billed_in"] / 1e6 * 0.27 + stats["billed_out"] / 1e6 * 1.10
    print(f"approx billed: ${cost:.4f}")


if __name__ == "__main__":
    main()
