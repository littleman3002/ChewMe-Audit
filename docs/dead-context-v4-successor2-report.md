# Dead-context v4 successor2 — validation report

**Verdict: SUCCESSOR2 HOLDS.**

Scope note (carried from the successor, binding on every number below):
successor2 determines IMPORT EVIDENCE ONLY, not dead/live. Precision,
misses, blind-spot, import-leg, and guard-exclusion figures are
import-evidence scoped, never dead-context scoped. This slice validates
successor2 only; tracks are never pooled.

**Sources:** manifest `dead-context-v4-successor2-validation-manifest.md`, SHA-256 `ac29bb1fd0da0ec21a157032de3458c87320eb7b4ccecc03c65af1634dea1a94`; design `dead-context-v4-successor2-design-DRAFT.md`, SHA-256 `72b8e6320ed734185e3328ea8f9a7f4523d6c96fc5331a69f9a12b72cdb547fa`.

- Module: `chewme_audit/detectors/dead_context_v4_successor2.py`,
  SHA-256 `e33f0d9bbce5c6e27778abeeb4f8cce5c799e409f9b5baa6c3acf2c8bc4fd993`
  (unchanged through the run; NOT in MEASURABLE).
- Manifest freeze-time hash (frozen-section bytes, before Appendix
  additions): `d67ca6478ea49576d6210bbfcc170da99f17342833e04851f4cc8c8d54816d42`.
- Slice: 600 traces, 600 distinct IDs, 568 distinct instances,
  275 resolved; retained hash
  `e1d60f40e009b3a2cd94baedd6ffbf5d58d8efc3dd9c11430d7836e68bc79ac1`.
- Sampling seed 20261215 (deck shuffle and clean re-search seeds are
  recorded in the manifest; import-leg subsample seed `d67ca647`,
  read from the manifest Appendix at runtime by the sampler).
- Cost: $0, no model calls. **No push was made** — a HOLDS verdict
  does not authorize a push; that stays Tracy's separate morning word.

600 traces, 10339 views, 3825 unique files, 807 fired (AST 524 /
fallback 283), 3018 non-fired. Partial views 1459. Unrootable files
1082 (G2 silence by design). Units scanned 26871. Parse reasons:
ast 1801 / syntax-error 894 / tokenize-degraded 1130. View→result
mapping 0 mismatches / 10339; full call→result mapping 0 mismatches /
39395. Fired chars 5233939; non-fired chars 12494663; viewed total
17728602.

## Evaluation

(a) Precision: 98/100 ✓ → PASS
(b) Misses: 0/50 ✓ → PASS
(c) Blind-spot: 2 ✓ → PASS
(d) Import-leg: import-leg ✓ (146/150 = 97.3%) → PASS
Guard (new false-flag classes ≤2): 1 ✓ → PASS

- **SUCCESSOR2 HOLDS**

## Bars (successor's structure kept exactly; no loosening)

Precision: **98/100 = 98.0%** (Wilson 95% CI [93.0%, 99.4%]).
Misses: **0/50**.
Blind-spot false flags: **2**.
New false-flag classes: **1**.
Dead-char share: **70.4774%** (12494663 / 17728602).
3018 dead / 807 live, 10339 views (successor scope: "live" =
successor2-FIRED files, "dead" = viewed files with no import-leg
fire — explicitly NOT dead-context dead files; the share above is
the non-fired-char share in successor scope, and the token number
below is NOT dead-content waste).
View→result mapping: **0 mismatches / 10339**.
Full call→result mapping: **0 mismatches / 39395**.
Waste: 3572855 o200k tokens (non-fired viewed text, NOT dead-content
waste — successor scope).
only-E1-dotted 0, only-E1-basename-parent 0, only-E1-full-path 0, only-E1-token 0, only-E4 807, only-E4-local-import 0, only-E5 0.
E1 kind counts (all live with E1): none.
E4 kind counts: defined 976, re-export 192.
E5 kind counts: none.

| Bar | Result | Bar | Verdict |
|-----|--------|-----|---------|
| (a) precision | 98/100 = 98.0%, Wilson [93.0%, 99.4%] | ≥90% | PASS |
| (b) misses | 0/50 | ≤1 | PASS |
| (c) blind-spot | 2 (global idxs 14, 53) | ≤5 | PASS |
| (d) import-leg | 146/150 = 97.3%, Wilson [93.3%, 99.0%], bootstrap [94.6%, 99.4%], n_eff 150.0 | ≥90% | PASS |
| (e) guard-exclusion | 30/30 = 100.0% | ≥95% | PASS |
| (e) uniform companion | 30/30 = 100.0% | reported | — |
| guard new classes in (a) | proxy 1 (idx 53), semantic 0 | ≤2 | PASS |
| unlisted in (d) | 0 | ≤1 | PASS |

## Blind-spot false flags

- **idx 14, blind-spot**
- **idx 53, blind-spot**

## Import-leg failures

- **idx 150**
- **idx 168**
- **idx 183**
- **idx 291**

**Tier outcome (fallback tier rule):** import-evidence AST share on the
fresh slice = 524/807 = 64.9% → 50–80% band → PROCEED with
per-substratum (d) reporting. AST substratum 98/100 = 98.0% PASS;
fallback substratum 48/50 = 96.0% PASS. Both substrata clear 90%, so
the tier reading is a PASS, not INCONCLUSIVE.

**Per-provenance (d):** cond-import 1/1 = 100%; trace-harvested
34/35 = 97.1%. **Per-arm (d):** exact 136/139 = 97.8%;
submodule-attribute 11/11 = 100%; re-export-ancestor 1/2 (thin —
the single miss is import_leg-0, a no-authored-unit item, not an arm
failure). **Per-stratum (d):** all six pages 91–100%.

**Standing FALSE anatomy (no matcher-path error among them):**
(a) 2, both observed-not-authored (no observable agent unit:
flag-14 header-only, flag-53 empty unit). (d) 4, all
observed-not-authored (no observable agent unit: import_leg-0/18/33/141;
18 is prose-only plus harvest metadata). The (d) failures are a
form-evidence gap class (statement recorded, unit not shown), not
wrong-module or wrong-name matches — the two mechanisms that killed
the successor are gone: fallback name-set incompleteness on partial
views produced 0 standing misses here (b = 0), and conditional
top-level imports are handled by the transitive If/Try/With recursion
(cond-import substratum 1/1; guard 30/30).

## Freeze rulings (recorded in the manifest before any labeling)

- **Ruling 1 — loop-body bindings for the (e) guard oracle: the
  BUILDER's treatment stands.** The frozen (e) oracle is the ALIGNED
  oracle (parent-chain-filtered walk: module top level + transitive
  If/Try/With chains, all binding types; function/class bodies never
  entered; For/While/AsyncFor bodies blocked) PLUS trace harvest
  (H1/H2/H3 with per-unit non-circularity). Loop-body bindings do NOT
  count as genuinely present for (e). Full-walk diagnostic
  (loop-body-only hits) on this slice: **0** (sampler stdout /
  Appendix record; the sampler does not persist this count — see
  gap below — so the analysis JSON carries `{}` for the field).
- **Ruling 2 — (a)-sampler H3 non-circularity: CONFIRMED.** An H3 name
  counts for the (a) flag only when some proof step differs from the
  importing unit's step; self-only proofs never flag (a). The frozen
  sampler implements the rule letter (the dry-run script's
  approximation is superseded).

## v3r8 disjointness (the brief's predicted hazard, found and fixed)

The candidate slice overlapped v3r8's frozen slice by **200, all
heavy** (identical heavy pool pages 57400–57900 in the same order;
v3r8 froze after the successor2 prep pull). The freeze re-drew the
heavy 200 continuing the pool forward from offset 58000 (pool
58000–58400), excluding v3r8's 600 + G0, the successor's 600 + G0,
and all prior sets. Re-verified disjointness: **ALL OVERLAPS ZERO**
vs every development input, prior validation set, and G0. The frozen
slice retains the candidate uniform 400 verbatim; the candidate draft
is NOT a prior set (never validated on), so the 400 overlap by
retention design is not a disjointness violation.

## Pre-gate format correction (disclosed, substance unchanged)

The first freeze record (hash `3bb04bae…`, seed `3bb04bae`) was
superseded BEFORE any gate run, run, or labeling by machine-parseable
format fixes (retained-header count, page-claims shape,
Pulled/Retained hash lines, composition/seed/exclusion/verdict-rule
lines, bars reworded to the successor's exact parseable shapes,
term-table inventory line). Slice rule, slice IDs, page files, page
SHAs, bars and their numbers, rulings, sampling plan, blinding plan,
tier rule, and kill condition are identical; the retained ID list was
verified byte-identical. The superseded seed was never used.

## Blinding, G4, overlap, G5

- **G4 (per worker, raw ≥80% + AC1 ≥0.70 + κ ≥0.60):** OV 0.96/0.917/
  0.923 GO; C 0.96/0.917/0.923 GO; B 0.96/0.915/0.924 GO; D 0.98/
  0.958/0.962 GO; E 0.98/0.958/0.962 GO; **A round 2 0.98/0.958/0.962
  GO** (round 1: 0.80/0.569/0.629 FAIL — discarded as uncalibrated,
  preserved on disk).
- **A re-instruction (rules only, no item identities, no key):**
  resolved field governs (ii) over statement text; statement name
  field governs (iii) over other fields; harvest counts even when
  the excerpt lacks the binding (excerpt rule applies only to
  window claims with no trace backing). Root causes: (a) PACKET
  AMBIGUITY — the brief's excerpt-binding rule conflicts with its
  harvest rule for H1/H2 harvests (bindings live in another
  view/grep output, not this excerpt); A resolved toward the
  excerpt rule, OV/C/B toward the harvest rule. (b) FLIP
  CONSTRUCTION WEAKNESS — flip-resolved changes resolved but not
  statement text; flip-name changes name but not matched_symbols/
  excerpt; forms contradict themselves. Round 2's pass (98%) shows
  the clarification worked; (d) is NOT inconclusive.
- **Overlap κ: 0.775** (18/20 agreement; above the 0.60 trigger, so
  no full-class re-search). Disagreements adjudicated for OV:
  flag-64 (H3 meshes proofs stand), guard-28 (encode_dict in no set).
- **Deck flaws (deck NOT changed mid-run; key labels stand):**
  deck-38 (flip-resolved) is BROKEN — the original was a
  submodule-attribute fire, so parent + name still equals the
  candidate; workers judging TRUE are correct. deck-35 (flip-name)
  is BROKEN — the flip garbled the statement to `import None`
  while matched_symbols/excerpt still show the genuine reference;
  no verdict on it is meaningful. G4 passes under keyed scoring
  (all workers ≥96%) and under valid-item scoring.
  deck-19 (natural, `nbformat.read` on the package `__init__`):
  coordinator TRUE stands — the viewed `__init__` defines `read`;
  workers' FALSE on it is a genuine labeling miss.
- **G5:** deck naturals 149/150 = 99.3% PASS; deck decoys 94/100 =
  94.0% PASS (valid-item 90/90 = 100%); flips 44/50 = 88.0% PASS
  (valid 40/40 = 100%). Stream catch keyed 44/50 = 88.0% (below
  the 90% bar AS KEYED); valid-item 44/48 = 91.7% PASS after
  excluding 2 provably-TRUE broken constructions (stream-06
  flip-resolved submodule-attribute no-op; stream-15 bare-import
  flip-name no-op), with stream-21 (stale-harvest flip-name)
  counted as a miss in that figure. G5 is judged PASS on valid
  items; the keyed shortfall is disclosed, not hidden.
  Successor2-specific stream shapes: self-proof 0/1,
  cross-file-harvest 0/2, all-only 2/2 — workers under-apply the
  excerpt rule on synthetic forms. This is a calibration signal
  only: validation items are real fires, and the clean sample
  (below) found no systematic over-calling on them.
- **Coordinator clean sample (seed recorded in the manifest, 30 items):** 29
  CONFIRM, 1 OVERTURN (import_leg-35, the bare-import case below).
  No systematic worker effect.

## Adjudication summary (12 overrides; worker files never modified)

- Overlap: flag-64 → TRUE, guard-28 → CORRECT (both for OV).
- Guard S-membership pattern (5): guard-17/19/29/3/28 → CORRECT.
  Workers over-called INCORRECT on exact-V imports without checking
  S membership; in every case the name was in no set and the excerpt
  was empty, so (iii) was unproven.
- **Bare-import ruling:** bare `import V` of viewed module V
  satisfies §1 — the module's AST arm and fallback arm fire on bare
  imports with name=None, and importing a module is referencing it
  (no member name is required when the statement IS the module
  import). Applies to flag-80, import_leg-23/35/37/39/95. This
  ruling was forced by the clean sample (import_leg-35) and applied
  consistently to every same-shape item in the sample; no barred
  guard item has a bare exact-V import, so (e) is unaffected.
  Without this ruling (d) would read 141/150 = 94.0% (still PASS);
  with it, 146/150 = 97.3%. The ruling is about the estimand, not
  about passing a bar.

## Tooling gaps disclosed (none changes a bar)

- **Sampler diagnostic-persist gap:** the sampler prints the
  full-walk diagnostic count (0 on this slice) but does not persist
  it in the guard sample file (no `full_walk_diagnostic` key); the
  count 0 is recorded in the manifest Appendix sampling record and
  here, never scored. The analysis JSON carries `{}` for the field.
- **Guard-sample adapter:** the sampler writes the barred (b)-pool
  sample with keys `b_population`/`b_sample` (no `population`
  key), while the analysis (adapted from the successor, whose guard
  sample was the uniform pool) reads `["population"]`. Adapter
  file `dead_context_v4_successor2_guard_sample_adapter.json`
  maps population := b_population (42); sampler and analysis files
  untouched, bar inputs (from `--guard-labels`) unaffected.
- **Runner `--manifest` assertion in `--g0` mode:** the G0 run was
  done without `--manifest` (same as the successor's runner
  structure); G0-vs-slice disjointness is covered by the
  disjointness script.
- **Deck correction (deck files only, builder untouched):** 3 flip
  forms (deck-31/33/37) carried stale provenance='trace-harvested'
  + harvest fields from the original match; cleared to None on
  those 3 forms only (key labels unchanged, all FALSE).

## What this does and does not establish

HOLDS means: on a fresh, disjoint 600-trace slice, the successor2
rule's import-evidence judgments match adjudicated §1 judgments at
98% precision, 0 misses in 50, blind-spot 2, import-leg 97.3% with
both substrata above 90%, and guard-exclusion 100%. It does NOT
mean the rule determines dead/live (import evidence only), and it
does NOT authorize a push, a release, or any outward step. The
successor line's verdict (DOES NOT HOLD) stands for the successor
module; successor2 is a new module on a new slice, and the two are
never pooled.

## Meta-audit

Post-run meta-audit (`meta_audit_v2.py`, SHA
`dc77d4ee18c173b6da661243350da9affbca2b5488c8080bdc41ef575bb325d5`):
**META-AUDIT FAIL — 133 checks, 1 FAIL, disclosed (not clean).**
The auditor's own recomputation derives HOLDS from the raw files
(precision 98/100, misses 0/50, blind-spot 2, import-leg 146/150,
new classes 1), matching this report's verdict line. The single FAIL
is M1-new-classes, a heuristic flag: flag-53's worker-verbatim reason
("no observable agent unit") matches no keyword in the auditor's
known-class list, although the worker's failure_class for that row is
observed-not-authored, a closed class — so it is NOT a new class,
and the guard bar (≤2, proxy count 1) passes regardless. The reason
is worker-verbatim and is not edited to satisfy the heuristic. All
other checks pass, including M6 derived-verdict agreement, M7
traceability of every headline number, and M8 manifest format. Full
audit report: `meta-audit-v4-successor2-post-run-report.md`
(+ `.json`). Per standing procedure, this verdict is reported with
the FAIL disclosed and is never quoted as meta-audit-validated.
