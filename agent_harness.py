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

# Fixed-tag variant (harness-fix validation, stage 1b): the same
# canary line on every prose reply — nothing increments, so the
# seeding provides no counter template. Rest of the framing is
# identical to CANARY_RULE.
CANARY_RULE_FIXED = (
    "\n\nCanary rule: begin every reply that contains prose with a "
    "line containing only `CANARY {tag}` — the same line every "
    "time; it never changes and nothing increments. A reply that "
    "is only tool calls, with no prose, carries no canary. Never "
    "put the canary line in files, code, or commands — only as "
    "the first line of your reply text.")


def first_call_end(text):
    """End index (exclusive) of the first complete tool call in a
    reply, or None. The call must parse as a tool call; prose that
    merely contains braces or a partial block does not count."""
    start = text.find("```json")
    if start != -1:
        brace = text.find("{", start)
        if brace == -1:
            return None
        fence = text.find("```", brace)
        if fence == -1:
            return None
        return fence + 3
    brace = text.find("{")
    if brace == -1:
        return None
    try:
        _, end = json.JSONDecoder().raw_decode(text[brace:])
        return brace + end
    except Exception:
        return None


def count_toks(text):
    n, _ = counting.count(text, "deepseek")
    return n


class Harness:
    def __init__(self, workdir, task, trace_path, budget, trace_id=None,
                 canary_tag=None, verify_cmd=None, verify_timeout=300,
                 canary_style="counter", truncate_first_call=False):
        self.workdir = os.path.abspath(workdir)
        self.task = task
        self.verify_cmd = verify_cmd
        self.verify_timeout = verify_timeout
        self.canary_tag = canary_tag
        self.canary_style = canary_style
        self.truncate_first_call = truncate_first_call
        self.truncations = 0
        if canary_tag:
            rule = (CANARY_RULE_FIXED if canary_style == "fixed"
                    else CANARY_RULE)
            self.task = task.rstrip() + rule.format(tag=canary_tag)
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

    def verify(self):
        """Harness-verified outcome (D2 fix): success is confirmed by
        re-running the task's test suite in the workdir, never by the
        agent's completion string. If verification cannot execute,
        the outcome is 'unverifiable' — never success."""
        if not self.verify_cmd:
            return {"outcome": "unverifiable", "exit_code": None,
                    "reason": "no verify command configured",
                    "cmd": None, "output_tail": ""}
        try:
            p = subprocess.run(self.verify_cmd, shell=True,
                               cwd=self.workdir, capture_output=True,
                               text=True, timeout=self.verify_timeout)
            tail = ((p.stdout or "") + (p.stderr or ""))[-500:]
            return {"outcome": "verified_pass" if p.returncode == 0
                    else "verified_fail",
                    "exit_code": p.returncode, "reason": None,
                    "cmd": self.verify_cmd, "output_tail": tail}
        except subprocess.TimeoutExpired:
            return {"outcome": "unverifiable", "exit_code": None,
                    "reason": f"verify command timed out after "
                              f"{self.verify_timeout}s",
                    "cmd": self.verify_cmd, "output_tail": ""}
        except Exception as e:
            return {"outcome": "unverifiable", "exit_code": None,
                    "reason": f"verify failed to execute: "
                              f"{type(e).__name__}: {e}",
                    "cmd": self.verify_cmd, "output_tail": ""}

    def run(self):
        if self.canary_tag:
            # Seed line: harness-written, system role, trace index 0
            # (canary-check spec v0.2 section 3c).
            mode = ("counter=prose-replies"
                    if self.canary_style == "counter"
                    else "counter=none-fixed-line")
            self.log("system",
                     f"CANARY-SEED tag={self.canary_tag} anchor=start "
                     f"{mode}")
        self.log("assistant", f"TASK START: {self.task}")
        steps = 0
        end_reason = None
        completion_claimed = False
        while True:
            msgs = self.context_messages()
            prompt_toks = sum(count_toks(m["content"]) for m in msgs)
            if self.input_tokens + prompt_toks > self.budget * HARD_CAP_MULT:
                self.log("assistant", "BUDGET CAP REACHED — stopping.")
                end_reason = "budget_cap"
                break
            reply, used = self.api(msgs)
            self.input_tokens += used
            self.output_tokens += count_toks(reply)
            if self.truncate_first_call:
                # Prevention fix: a generation may not continue past
                # its first complete tool call — anything after it
                # (including fabricated tool output or a completion
                # string) never enters the trace or the history.
                end = first_call_end(reply)
                if (end is not None and end < len(reply)
                        and self.parse_tool(reply[:end])):
                    reply = reply[:end]
                    self.truncations += 1
            self.log("assistant", reply)
            steps += 1
            if "TASK COMPLETE" in reply:
                # The completion string is an EVENT, not an outcome:
                # the run ends (end-and-score), and verify() decides
                # what gets recorded.
                completion_claimed = True
                end_reason = "completion_claimed"
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
                end_reason = "token_budget"
                break
        self.fh.close()
        verification = self.verify()
        return {
            "steps": steps, "trace_steps": self.step_no,
            "input_tokens_local": self.input_tokens,
            "billed_in": self.billed_in, "billed_out": self.billed_out,
            "canary_tag": self.canary_tag,
            "canary_style": self.canary_style if self.canary_tag
            else None,
            "truncation": {"enabled": self.truncate_first_call,
                           "applied": self.truncations},
            "end_reason": end_reason,
            "completion_claimed": completion_claimed,
            "verification": verification,
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
    ap.add_argument("--canary-fixed", default=None, metavar="TAG",
                    help="seed with a fixed-tag canary: the same "
                         "canary line on every prose reply, no "
                         "counter (stage-1b variant)")
    ap.add_argument("--truncate-first-call", action="store_true",
                    help="prevention fix: cut each reply at its "
                         "first complete tool call (default OFF; "
                         "comparison runs keep it off)")
    ap.add_argument("--verify-cmd", default=None,
                    help="shell command re-run in the workdir when the "
                         "run ends; its exit code decides the recorded "
                         "outcome (0 = verified_pass). Without it the "
                         "outcome is 'unverifiable' — a completion "
                         "string alone never records success.")
    ap.add_argument("--verify-timeout", type=int, default=300)
    a = ap.parse_args()
    task = open(a.task_file).read()
    tag = secrets.token_hex(3) if a.canary else None
    style = "counter"
    if a.canary_fixed:
        tag = a.canary_fixed
        style = "fixed"
    h = Harness(a.workdir, task, a.trace, a.budget, trace_id=a.trace_id,
                canary_tag=tag, canary_style=style,
                truncate_first_call=a.truncate_first_call,
                verify_cmd=a.verify_cmd,
                verify_timeout=a.verify_timeout)
    stats = h.run()
    print(json.dumps(stats, indent=1))
    print(f"VERIFIED OUTCOME: {stats['verification']['outcome']} "
          f"(end_reason={stats['end_reason']}, "
          f"completion_claimed={stats['completion_claimed']})")
    # deepseek-chat off-peak $0.27/M in, $1.10/M out (standard sheet)
    cost = stats["billed_in"] / 1e6 * 0.27 + stats["billed_out"] / 1e6 * 1.10
    print(f"approx billed: ${cost:.4f}")


if __name__ == "__main__":
    main()
