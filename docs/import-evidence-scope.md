# Import-evidence module — scope

Import-evidence module. Reports whether a viewed file has import evidence from agent-authored code (module-path equality, trace-harvested names, conditional imports). It does NOT classify files as dead or live and is NOT used by the dead-context detector. Validation: HOLDS on import evidence only, 600 traces; meta-audit 132 PASS / 1 FAIL, disclosed.

## What this module is

`chewme_audit/detectors/dead_context_v4_successor2.py` (module SHA-256
`e33f0d9bbce5c6e27778abeeb4f8cce5c799e409f9b5baa6c3acf2c8bc4fd993`)
determines import evidence only: whether a viewed file has import
evidence from agent-authored code, by module-path equality between
resolved imports and the viewed file's canonical path, plus
trace-harvested name supplements (tagged `trace-harvested`) and
conditional-import bindings (tagged `cond-import`).

## What it is not

- It does NOT classify files as dead or live. Dead/live verdicts come
  from the dead-context detector (`dead_context.py`, shipped v2),
  which does not use this module.
- It is NOT registered in `MEASURABLE` and is NOT called by
  `chewme_audit/detectors/__init__.py::run_all`.
- It is NOT a successor to the dead-context detector. It is a
  standalone import-evidence component.

## Validation standing (import evidence only)

- Validation: HOLDS on import evidence only, 600 traces, seed
  20261215, $0, no model calls. Report:
  `docs/dead-context-v4-successor2-report.md`.
- Bars: precision 98/100, misses 0/50, blind-spot 2, import-leg
  146/150, guard-exclusion 30/30 (uniform companion 30/30),
  guard new classes 1 (bar ≤2).
- Meta-audit: 132 PASS / 1 FAIL, disclosed. The lone FAIL is an
  M1-new-classes heuristic flag on an already-closed class, not a
  new class; the auditor's recomputation derives HOLDS. Quote as
  HOLDS with FAIL disclosed, never as meta-audit-validated.

## Wiring rule

Do NOT wire this module into the shipped detector without a separate
integration validation (fresh slice, bars (a)–(c) on the combined
detector). Until such a validation holds, the detector must not
import this module; see `tests/test_push_measurable_guard.py`.
