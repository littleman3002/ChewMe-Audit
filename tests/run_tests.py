#!/usr/bin/env python3
"""Minimal stdlib test runner (no pytest dependency)."""
import sys
import traceback

import test_api_log
import test_cli
import test_pricing
import test_diff
import test_detectors

passed = failed = 0
for mod in (test_detectors, test_api_log, test_pricing, test_diff, test_cli):
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
