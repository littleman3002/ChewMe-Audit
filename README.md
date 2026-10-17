# chewme-audit

A CLI that reads your agent traces and tells you where the money went —
every fixable waste pattern, its measured dollar cost, and a concrete
copy-paste fix. MIT licensed. Not a money play; a working tool.

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
```

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
  spend, illustrative share of total bill — each labeled estimated or
  measured.
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
$0.20/M, out $2.50/M. Waste is priced at the cache-**miss** rate:
measured on benchmark trajectories, waste spans are 100% cache misses
(duplicates at new positions can't hit under prefix caching).

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
