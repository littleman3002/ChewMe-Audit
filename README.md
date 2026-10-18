# chewme-audit

A CLI that reads your agent traces and tells you where the money went —
every fixable waste pattern, its measured dollar cost, and a concrete
copy-paste fix. MIT licensed. Not a money play; a working tool.

## Worked example: the 283-repeat loop

A public SWE-agent trajectory (`iterative__dvc-7734`, nebius set —
chosen as the clearest loop case in the 73-trajectory set, not claimed
representative) fell into an error loop: a malformed `edit` command,
repeated **283 times** until the step limit. The audit flagged it; the
recommended fix (error-loop dedup) was applied; the agent was re-run
from the fixed context with a real model call (deepseek-chat,
2026-10-17, $0.0015).

**Before → after** (`--diff`, deepseek):

- Waste: **23,309 tokens ($0.0035)** → **3,041 tokens ($0.0005)** —
  **−20,268 tokens (−$0.0030)**
- The loop is gone: `error_loop_dedup` (−10,152 tokens) and
  `diff_read` (−10,116 tokens) both resolved — the 283 identical
  repeats tripped both the exact-repeat and near-duplicate detectors,
  so one fix cleared both
- Same waste on other providers' rates: Claude Sonnet 5
  $0.0466 → $0.0061, GPT-5/6 class $0.0932 → $0.0122, Grok
  $0.0291 → $0.0038, Gemini Flash $0.0175 → $0.0023
  (recorded sheets; override with `--pricing`)
- The agent broke the loop on the very next call: instead of a 284th
  malformed edit, it reasoned about the actual bug (pickle protocol 5
  on Python 3.7) and issued `bash grep -rn "pickle" dvc/ | head -50`
- What this proves: the fix lets the agent **progress**. It does NOT
  prove the agent solves the underlying issue — the re-run was one
  step. (See `traces/worked_example/PROVENANCE.md`.)
- Residual waste ($0.0005, oversized outputs the fix didn't touch) is
  listed, not hidden — the report's "fixes not fully applied" section
  re-surfaces those snippets

The headline finding carries a tamper-evident receipt
(`--receipt`): `error_loop_dedup`, 10,152 tokens, $0.0015,
SHA-256 `6269f6eb…e816`.

Reproduce it:

```bash
python -m chewme_audit.cli traces/worked_example/before.jsonl \
    traces/worked_example/after.jsonl --diff --provider deepseek
```

Full report, traces, and provenance: `traces/worked_example/`.

## The honest scope, first

- **What it finds:** repeated identical tool calls (usually agents stuck
  in error loops), near-duplicate re-sends (full file re-views after
  one-line edits), oversized tool outputs nothing later references, and
  pretty-printed JSON. Each finding names the exact call.
- **What it can't see from trace exports:** real cache hit/miss behavior
  and reasoning-token overspend need your provider API logs. The report
  says so explicitly instead of guessing.
- **Estimates out of the box from trace exports; hand it your API logs
  if you want exacts.** Without `--api-log`, every dollar figure is
  labeled **estimated**. With it, cache accounting is **exact** and the
  report says **measured**.
- **The numbers behind it:** on public benchmark trajectories, 74%
  carried measurable waste ≥10% of input spend, ~6–16% of the total bill
  after honest shrinking. Those figures are labeled "measured on public
  benchmark trajectories" everywhere — benchmark agents loop more than
  production agents, so treat your own traces as the true test.
- **Fix safety:** the two headline fixes (error-loop dedup, diff-reads)
  were replay-tested on 13 trajectory pairs — 13/13 preserve or improve
  agent comprehension, no breakage. An audit that recommends fixes which
  break agents loses trust fast; these don't.

## Why this gets more useful over time

Two trends both point the same way:

- **Cache discounts keep getting steeper on newer models.** DeepSeek
  discounts cache hits 50×, Claude's newest models 20–40×, OpenAI's
  GPT-5/6 class 10×. A cache break on a 40×-discount model costs four
  times what the same break costs at 10× — and providers are competing
  on these discounts, so the gap widens.
- **Agents keep getting more ambitious.** Bigger contexts, longer
  trajectories, more tool calls per task. Every step of that multiplies
  the raw material: more re-reads, more retries, more repeated calls.

The more your agents do, and the newer the models they run on, the more
each unit of waste costs you. This tool measures that waste — so its
value grows with the market, not against it.

## Quickstart

No API keys needed — token counting is local.

```bash
# Estimates out of the box:
python -m chewme_audit.cli traces/sample.jsonl --provider deepseek

# Exact cache accounting from your API logs:
python -m chewme_audit.cli my_traces.jsonl --provider deepseek \
    --api-log my_api_log.jsonl

# JSON output, framework-specific fixes, tamper-evident receipts:
python -m chewme_audit.cli my_traces.jsonl --provider grok \
    --output json --framework langchain --receipt --out audit.json

# Override pricing (file or inline JSON, merged over recorded sheets):
python -m chewme_audit.cli my_traces.jsonl --provider deepseek \
    --pricing '{"deepseek": {"miss_per_mtok": 0.20}}'

# OPT-IN: illustrative total-bill share (assumes outputs ~50% of bill).
# Off by default so nobody quotes it without the label:
python -m chewme_audit.cli my_traces.jsonl --provider deepseek --total-bill
```

## Diff mode: prove the delta

The complete loop — find → recommend fix → apply → prove it:

```bash
python -m chewme_audit.cli before.jsonl after.jsonl --diff --provider deepseek
```

All flags (`--provider`, `--format`, `--framework`, `--pricing`,
`--api-log`, `--output`, `--out`) apply to both sides; `--api-log`
applies the same log to both. Traces are matched by `trace_id` when
both sides carry them, otherwise by order — unmatched traces are listed,
never silently dropped.

The Diff section answers three questions:

1. **Net change** — waste and input spend, before → after, in tokens
   and dollars, plus residual waste left.
2. **What disappeared / shrank** — resolved and reduced classes with
   the original detector and fix key.
3. **What remains or got worse** — new and unchanged findings, so a
   partial win never gets shipped as done.

Fix keys surviving on both sides are re-surfaced with their snippet and
a note that the fix wasn't fully applied (or the agent found a new way
to loop).

For provider-token counts (billed-token basis instead of the chars/4
estimate), point `CHEWME_LAB` at the tokenizer lab and run under its
venv:

```bash
CHEWME_LAB=~/workspace/tokenizer-lab \
  ~/workspace/.venv-chewme/bin/python -m chewme_audit.cli traces/sample.jsonl \
  --provider deepseek
```

## Inputs

| Flag | Format |
|---|---|
| (default) | JSONL, one observation per line — schema auto-detected (generic, nebius/SWE-agent style, or bare observations) |
| `--format langfuse` | Langfuse trace export (JSON array or JSONL) |
| `--format langsmith` | LangSmith run export (JSON array or JSONL) |
| `--api-log FILE` | Provider API log: JSONL, one record per request with `prompt_tokens`, `cached_tokens`, `completion_tokens` (OpenAI-style `usage` objects accepted). Joined to steps by `(trace_id, step)`. |

## What the report contains

- **Headline:** measurable waste in tokens and dollars, share of input
  spend — each labeled estimated or measured. The total-bill share is
  **opt-in only** (`--total-bill`): it's illustrative (assumes outputs
  ~50% of bill), so it's off by default rather than quoted without its
  label.
- **Prioritized findings:** every waste instance by dollar impact, with
  the evidence (repetition counts, similarity scores, diff hints).
- **Recommended fixes:** copy-paste snippets for your framework
  (`--framework generic|langchain|llamaindex|openai_agents`), each with
  its safety evidence.
- **Needs your API logs:** the classes trace exports can't measure,
  stated plainly, never priced.
- **`--receipt`:** tamper-evident per-finding receipts (SHA-256 over
  canonical fields; hashes of text, never the text — no PII).

## Pricing

Recorded sheets (re-verify before quoting): `deepseek-flash` —
miss $0.15/M, hit $0.003/M, out $0.60/M (peak windows 01:00–04:00 and
06:00–10:00 UTC Mon–Fri ×2); `grok-4.20-0309` — in $1.25/M, cached
$0.20/M, out $2.50/M; `claude-sonnet-5` — miss $2.00/M, hit $0.20/M,
out $10.00/M; `gpt-5.6-sol` — miss $4.00/M, hit $0.40/M, out $20.00/M
(promo through 2026-11-21); `gemini-3.8-flash` — miss $0.75/M,
hit $0.075/M, out $3.75/M. Waste is priced at the cache-**miss** rate:
measured on benchmark trajectories, waste spans are 100% cache misses
(duplicates at new positions can't hit under prefix caching).

Sheets are hardcoded and will drift — override any rate with
`--pricing` (JSON file or inline), which merges over the recorded
sheets without touching the repo.

## Tests

```bash
cd tests && python3 run_tests.py
```

The regression suite runs the detectors against real excerpts from the
public SWE-agent trajectories behind the premise measurements — a
detector that stops firing on them is a regression.

## Sample data

`traces/sample.jsonl` — 5 trajectories (683 steps) from the public
nebius SWE-agent set, deliberately the heaviest-waste tail (that's why
the sample report shows a high waste share; it is not representative).
`traces/sample_api_log.jsonl` — synthetic demo API log for the sample
traces (labeled `_synthetic` per record).

`traces/sample_typical.jsonl` — 5 trajectories from the **middle
quintile** of the same set (median waste share), for calibrating
expectations: 27,947 waste tokens, 39.6% of input on deepseek. Still
benchmark-trajectory waste — production agents loop less — but a fairer
picture of what "a normal run" looks like than the heavy tail.

## The `rust/` folder

The deterministic Rust core from the earlier wrapper work, kept as a
library: fidelity gate, collision handling, lexical rules. The CLI is
pure Python and doesn't need it — it's the future performance path
(byte-exact minify with real guarantees) and the home of the
`pretty_printing` detector's "here's what minify would save you" line.
See `rust/README.md`.
