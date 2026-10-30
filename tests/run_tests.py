#!/usr/bin/env python3
"""Minimal stdlib test runner (no pytest dependency)."""
import sys
import traceback

import test_api_log
import test_blind_edit
import test_claude_code
import test_cli
import test_coverage
import test_cross_trace
import test_dead_context
import test_dead_context_v4_successor2
import test_push_measurable_guard
try:
    import test_dead_context_v3
except ImportError:
    test_dead_context_v3 = None
import test_detectors
import test_diff
import test_fixes
import test_litellm
import test_pricing
import test_unverified_final_state

passed = failed = 0
_modules = [test_detectors, test_api_log, test_pricing, test_diff, test_cli,
            test_cross_trace, test_blind_edit, test_unverified_final_state,
            test_dead_context, test_litellm,
            test_coverage, test_claude_code,
            test_fixes, test_dead_context_v4_successor2,
            test_push_measurable_guard]
if test_dead_context_v3 is not None:
    _modules.insert(9, test_dead_context_v3)  # after test_dead_context
for mod in _modules:
    for name in sorted(dir(mod)):
        if not name.startswith("test_"):
            continue
        fn = getattr(mod, name)
        try:
            fn()
            print(f"PASS {mod.__name__}.{name}")
            passed += 1
        except Exception:
            print(f"FAIL {mod.__name__}.{name}")
            traceback.print_exc()
            failed += 1

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
