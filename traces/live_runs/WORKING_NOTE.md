# Working note: solo vs 4 unpartitioned agents on the same task

**Disclaimer, first paragraph:** one task family (module-docstring insertion on
Django), one model (deepseek-chat, temp 0.2), one harness
(`agent_harness.py`). Four agents ran the identical full task in isolated
pristine workdirs — no partitioning, no coordinator. This is the realistic
"throw N identical agents at the job" setup, not a controlled efficiency
experiment. N=1 task, N=1 model: treat every number below as a data point,
not a law.

## What "waste share" means (locked definition)

Waste is **detector-defined**, not "tokens that never affected the final
diff." Running the same tool commit on the same trace reproduces the number
exactly. Detectors (commit `e38fd96a` baseline + `cross_trace.py` new here):

- **repeated_calls** — byte-identical tool observations (SHA-256 of
  whitespace-normalized text) occurring 2+ times in one trace.
  Waste = (occurrences − 1) × tokens. The first occurrence is never waste.
- **near_duplicate_resends** — consecutive observations with
  `difflib.SequenceMatcher` ratio ≥ 0.85. Waste = re-sent observation tokens.
- **oversized_unreferenced** — tool output > 2048 tokens where no distinctive
  long value from that output is referenced in any later step.
  Waste = the output's tokens.
- **pretty_printing** — JSON observations that minify. Waste = tokens saved.

**Cross-detector dedupe:** findings declare `covers` (step indices); each
step contributes its per-step max across covering findings; total = sum.
(A double-count bug here was found and fixed 2026-10-17; regression test in
`tests/test_diff.py`.)

**Waste share** = `total_waste_tokens / total_input_tokens`, both counted in
the DeepSeek v3 local tokenizer (`deepseek` provider in `pricing.py`).

**Cross-trace waste is reported separately** and is NOT in the per-trace
shares: SHA-256 of whitespace-normalized tool observations appearing in
>1 trace, waste = (n_traces − 1) × tokens. **No similarity threshold is
involved** — cross-trace matching is exact, so the 17,050 figure cannot be
inflated by near-duplicate false positives. Near-duplicates are
deliberately not flagged cross-trace (conservative, documented in
`cross_trace.py`).

**Threshold honesty:** the ≥0.85 `difflib` similarity threshold applies
only to the *within-trace* `near_duplicate_resends` detector. It is a
first cut, not sensitivity-tested. In the five live traces it contributed
a small minority of waste (repeated_calls dominated everywhere), so
threshold choice does not move the headline numbers — but anyone reusing
the detector on noisier traces should test it.

**Real-trace exercise:** `cross_trace.py`'s 4 unit tests use synthetic
cases, but the reported 17,050 tokens come from running the module
directly against the four real 4-agent traces in this directory — that
real-data run *is* the validation behind the number, not just the tests.

## Identical starting conditions (confirmed)

- All 4 workdirs reset with `git checkout -- .` before launch: 0 modified
  files, 0 untracked files (verified per workdir).
- Same task file, same harness, same model, same temperature, same tool set,
  same 1M-input-token budget with hard stop.
- Isolated workdirs — no shared state, no cross-agent interference.
- The solo baseline ran on the same workdir path, also reset to pristine
  before the 4-agent run.

## Scoreboard (real billed cost, 2026-10-17)

|            | Solo | Agent 1 | Agent 2 | Agent 3 | Agent 4 |
|------------|------|---------|---------|---------|---------|
| Billed     | $0.15 | $0.36 | $0.15 | $0.30 | $0.29 |
| Trace input tokens | 57,492 | 153,366 | 60,086 | 113,206 | 110,755 |
| Waste tokens | 20,365 | 48,883 | 9,025 | 38,505 | 41,117 |
| Waste share  | 35.4% | 31.9% | 15.0% | 34.0% | 37.1% |
| Dominant class | repeated_calls 94.6% | repeated_calls | repeated_calls | repeated_calls | repeated_calls |
| Finished?  | yes | **no** — budget cap | yes | yes | yes |
| Work clean? | yes | **no** — 117 deletions | yes | yes | yes |

4-agent total: **$1.09 billed, 137,530 per-trace waste tokens**,
plus **17,050 cross-trace duplication tokens** (see finding 2).

## Finding 1 — the agent lottery dominates

Identical model, identical task, identical harness: waste share ranged
**15.0% to 37.1%**. Agent 2 (15.0%, $0.15 billed) beat the solo run
(35.4%, $0.15 billed) at the same dollar cost. Which agent instance you get
matters more than how many you run. The aggregate cost multiple is less
interesting than this variance.

## Finding 2 — cross-agent duplication is real and measurable

15 groups of byte-identical tool observations across traces;
**17,050 tokens** of duplication waste, led by all four agents
independently running the same file-discovery commands (6,933 tokens in
one group present in all 4 traces). Per-trace audits cannot see this —
only the new `cross_trace.py` detector catches it (4 tests, conservative:
near-duplicates not flagged). This is the coordination gap, quantified.

## Finding 3 — uncoordinated agents break things (root-caused)

Agent 1 was the most expensive ($0.36), never declared TASK COMPLETE (hit
the 1M-token budget cap), and **replaced real documentation with
one-liners**: 117 deletions, including a 60-line module docstring in
`django/db/models/fields/related_descriptors.py`. Concrete trigger chain,
with verbatim trace evidence (`trace_4agent_1.jsonl`):

1. **Shallow observation.** It inspected files with `head -3` / `head -4`
   only (steps 12–18) — never saw full contents. `head -3` on
   `related_descriptors.py` showed only the opening quotes and first line,
   so it classified a 60-line docstring as a stub.
2. **Task drift, verbatim.** Step 176: *"I'll write a script that replaces
   the generic docstrings with accurate descriptions, in batches."* The
   task said "skip files that already have a module docstring" and "do not
   change any other code" — the agent had reframed "add missing" as
   "improve existing," and built a replace path (`replace_docs.py`,
   `lines[start:end+1] = new_lines` swaps the entire docstring span)
   instead of insert-only.
3. **Verification ran — and the signal was ignored.** Its own
   `git diff --stat` outputs show the damage appearing in real time:
   step 180: `210 files changed, 210 insertions(+)` (clean) →
   step 185: `replaced 20` → `214 files changed, 214 insertions(+),
   16 deletions(-)` →
   step 189: `replaced 28` → `223 files changed, 223 insertions(+),
   117 deletions(-)`.
   It kept replacing through steps 210–220. The deletions were the
   *expected signature* of its replace operation, so they never registered
   as damage — the failure was at classification (step 1), not at
   verification. No step ever re-examined the classification.

Failure cascade: shallow observation → wrong classification → destructive
rewrite → verification output consistent with the wrong model. No
context-window overflow involved; the damage was deliberate-by-heuristic,
not accidental-by-truncation. Any harness that lets an agent rewrite
first-party content on the basis of truncated reads will hit this.

## Cost multiple (secondary)

$1.09 / $0.15 ≈ **7.3×** the solo cost for three successful completions
plus one failure and one damaged workdir. The denominator is honest: the
non-completing agent is included, not dropped.

## Honesty caveats

- One task family, one model, one harness. Not a general claim about
  multi-agent systems.
- Isolated workdirs: shared-workdir multi-agent setups would add
  merge-conflict and interference costs not measured here.
- Waste shares are detector-defined (see locked definition above); cross-trace
  waste is a separate number. Do not add them into one percentage without
  saying so.
- Solo-run framing: ~35% of tool I/O tokens were pure re-verification
  (the same "find missing docstrings" script re-run 7× = 13,866 tokens),
  mapping to roughly a quarter to a third of the $0.15 bill. No error
  loops — the solo agent was competent, just paranoid.

## What's next

- High-waste debugging task (failing test suite on an unfamiliar repo —
  where retry/re-read/re-run loops live) is the planned follow-up.
  Design is being tightened first: same model/harness/task family, forced
  high-waste conditions, explicit success criteria, hard stop. Not queued
  until the design isolates one variable.
- Model-size comparison (same task, bigger model, per-class waste
  breakdown) is experiment #3. Not queued.

Traces: `traces/live_runs/` (solo + 4 agents, full JSONL) with
`PROVENANCE.md`. Audit JSONs reproducible via
`python -m chewme_audit.cli <trace> --provider deepseek`.

## Appendix — debugging run: the accidental pass (evaluation methodology finding)

**Scope:** single follow-up experiment, not part of the docstring comparison.
Same model (deepseek-chat), same harness, same budget. Task: fix 2 failing
subtests in `cache.tests.CacheUtils` caused by a real historical Django bug
(ticket #37424, 1-line revert in `django/utils/cache.py::_to_tuple`).
Success criterion: full suite pass, zero changes under `tests/`.
Trace: `traces/live_runs/trace_debug.jsonl`; task: `traces/live_runs/task_debug.txt`.

**Outcome on paper:** 34 steps, 12/12 pass, zero test changes, $0.013 billed,
1.3% waste (80 tokens, all `repeated_calls`). A clean win by every surface
metric.

**What the trace shows:** the pass is accidental. Verified link by link:

1. The agent reproduced the failures and read the full source file — competent
   early behavior.
2. Mid-run it overwrote the entire `cache.py` with the string `"PLACEHOLDER"`
   via `write_file` (its own `git diff --stat`: `1 insertion(+), 451
   deletions(-)`). It caught the mistake itself: "I overwrote the file with
   a placeholder by mistake."
3. It "recovered" with `git checkout -- django/utils/cache.py`. The bug had
   been introduced as a *working-tree* delta, so the checkout silently
   restored the upstream fixed version. The agent ran it as a recovery
   command; the fix arrived as a side effect it never detected.
4. Its re-applied edit script then threw `AssertionError` — the broken text
   it searched for no longer existed. It grepped, saw the line already
   fixed, and added `.strip()` to the *other* branch — a line the historical
   fix never touched and the failures never implicated.
5. 12/12 passed. It declared TASK COMPLETE, describing the fix as "strip
   whitespace from cache-control directive names **without values**." The
   actual bug was whitespace preceding the `=` in directives *with* values
   (`'max-age =300'`). Confident, wrong, untested against its own claim.

**Attribution:** of the two `.strip()` calls in the final diff, the one that
fixes the bug arrived via `git checkout --`; the one the agent wrote was
unnecessary. The agent's causal contribution to the passing suite is zero.

**The methodology point, not a model failure:** pass/fail + diff size +
billed cost — the standard agentic-coding scoreboard — scores this run a
clean win at $0.013. The trace shows a clobber, an accidental rescue, a
cosmetic edit, and a misdescribed bug. Any evaluation that scores only final
pass/fail, diff size, and cost — without verifying that the agent's own diff
contains the fix and that its stated mechanism matches the actual bug — will
certify false successes. This failure mode — *false success* — is distinct
from success-with-waste and from inability-to-stop, and it is invisible to
outcome-only metrics.

**Design flaw (ours):** the bug must be the committed state, not a
working-tree delta, or any `git checkout --` recovery silently restores the
fix. A checkout-proof re-run is planned; its waste profile is the valid
high-waste contrast, not the 1.3% reported here.
