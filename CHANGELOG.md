# Changelog — chewme-audit

## 0.2.0 — 2026-10-28

### Added

- **Dead-context detector v2** (`chewme_audit/detectors/dead_context.py`,
  wired into `run_all` as a measurable waste detector). Flags files the
  agent viewed once and never referenced again downstream — no later
  tool-call argument names the file (path, dotted module reference,
  or basename with matching parent directory), no later edit touches
  it, it is not in the final patch, and no symbol defined in it is
  used in a later tool call. One finding per dead file; waste is the
  first view's result tokens. Assistant free prose is NOT evidence
  (mentioning is not using), and neither is the content of later view
  results.
- Tests: `tests/test_dead_context.py` — 27 tests covering evidence
  rules E1–E4, exclusions (directory listings, error results), block
  result mapping, patch modes, and the v2 rule fixes. Full suite
  123/123 green at validation time (2026-10-27); the local tree now
  also carries 46 v3 tests (169/169), not in this release.
- Fix guidance for the finding (`fixes/dead_context`): stub the
  unreferenced view result in history after a grace window, keeping a
  content hash plus the file's symbol index so it can be re-fetched on
  demand. **NOT replay-tested** — apply as a recoverable stub, not a
  drop.

### Validated (Stage C, 2026-10-27)

- Precision **90.0%** (90/100 hand-checked flags; Wilson 95% CI
  [82.6%, 94.5%]) — exactly at the pre-registered ≥90% bar, no
  margin. Misses **0/27** live files hand-checked (bar ≤1).
- Dead share **18.33%** of viewed-file chars on a frozen 499-trace
  fresh slice of OpenHands trajectories (697 dead files of 2,949;
  721,976 o200k tokens). The slice was disjoint from the development
  and v1-validation slices (0 overlap by trajectory_id).
- Scope: weakly held out — the slice shares corpus and harness family
  with the discovery work, not independent of the lab's development.
  Native tool-call traces only; the SWE-agent text-harness shape is
  out of scope.
- v2 supersedes v1 (96.0% precision on v1's own slice). Full report:
  `~/workspace/eth-paper/dead-context-v2-report.md` (kept out of this
  repo; the validation artifacts live in the eth-paper workspace).

### Known limitations

- **Blind spot (standing):** all 10 false flags were implicit content
  use the argument-only evidence rules cannot see — quoted-content
  diagnosis (5), pattern application (3), execution-as-use (1), fact
  reasoning from viewed content (1). The detector reports a lower
  bound ("at least this much was demonstrably unused"); absence of a
  surface reference does not prove non-use.
- **E4 identifier collisions:** ~28.6% (6/21 pooled, Wilson 95% CI
  [13.8%, 50.0%]) of E4-only live files rest on identifier collisions
  rather than genuine use — so the dead share is understated as well
  as being a lower bound.
- **Think steps:** evidence legs read `think`-step text as if it were
  tool-call arguments; 15/2,252 live files flip to dead with think
  steps excluded. Function-local imports are invisible to E4.
- **Later-slice misses (disclosed 2026-10-30):** Since release, a later validation slice confirmed four misses that v2 calls live but that weren't used: grep-only evidence, same-name symbol collision, reference-view without reuse, and agent-created temp files. The published 0-miss result stands for its own 499-trace sample. The true miss rate on new traces is likely above zero.
- These are the v3 design items (`dead-context-v3-design.md`); v3 was
  implemented 2026-10-28, is not validated, is not wired into
  `run_all`, and is not in this release.

## 0.1.1

- PyPI release. (Prior history before this changelog was kept — see
  git history.)
