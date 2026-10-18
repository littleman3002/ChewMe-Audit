# Provenance — live agent runs (2026-10-17)

Real agent runs, billed against the DeepSeek API. Not assembled, not
simulated.

## Task (identical for all five runs)

`task.txt`: add a 1–3 sentence module docstring to every Python module under
`django/db`, `django/utils`, `django/core` lacking one (283 files in scope,
210 missing). Rules: accurate summaries only, skip files with docstrings,
no other code changes, batch via scripts, verify with `git diff --stat`.

## Harness

`agent_harness.py` (repo root): minimal ReAct loop, deepseek-chat,
temperature 0.2, tools `run_bash` / `read_file` / `write_file`, rolling
summary every 20 steps, budget on input tokens with hard cap at 1.2×.

## Runs

| Trace | Agent | Billed (approx) | Outcome |
|---|---|---|---|
| `trace.jsonl` | solo | $0.15 | TASK COMPLETE, 210 files, clean |
| `trace_4agent_1.jsonl` | 1 of 4 | $0.36 | budget cap, 117 doc lines deleted |
| `trace_4agent_2.jsonl` | 2 of 4 | $0.15 | TASK COMPLETE, 210 files, clean |
| `trace_4agent_3.jsonl` | 3 of 4 | $0.30 | TASK COMPLETE, 210 files, clean |
| `trace_4agent_4.jsonl` | 4 of 4 | $0.29 | TASK COMPLETE, 210 files, clean |

All five ran in isolated pristine workdirs (`git checkout -- .`, 0 modified
/ 0 untracked verified before launch). The 4-agent run used the
unpartitioned design: same full task, no coordinator.

Trace IDs: `live__django-docstrings::deepseek-chat::solo` and
`live__django-docstrings::deepseek-chat::4agent-{1..4}`.

## Reproduce the audits

```
python -m chewme_audit.cli traces/live_runs/trace.jsonl --provider deepseek
```

Cross-trace duplication: `chewme_audit/cross_trace.py`
(`find_cross_trace_duplicates`), 4 tests in `tests/test_cross_trace.py`.

Total API spend across all five runs: ~$1.24.
