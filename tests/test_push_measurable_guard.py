"""Push guard: the successor2 push set must not change MEASURABLE and
must not wire successor2 into the shipped detector.

Standalone runner: `python tests/test_push_measurable_guard.py` from
the repo root. (Not wired into tests/run_tests.py by design: wiring
that file would itself be an out-of-allowlist change to the push set.)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chewme_audit.detectors import MEASURABLE  # noqa: E402

EXPECTED_MEASURABLE = [
    "chewme_audit.detectors.repeated_calls",
    "chewme_audit.detectors.near_duplicates",
    "chewme_audit.detectors.oversized_outputs",
    "chewme_audit.detectors.pretty_print",
    "chewme_audit.detectors.dead_context",
]


def test_measurable_contents_exact():
    names = [m.__name__ for m in MEASURABLE]
    assert names == EXPECTED_MEASURABLE, names


def test_no_measurable_module_imports_successor2():
    import chewme_audit.detectors as det_pkg

    assert "dead_context_v4_successor2" not in sys.modules, (
        "importing the detectors package loaded successor2"
    )
    pkg_dir = os.path.dirname(det_pkg.__file__)
    for mod in MEASURABLE:
        src = open(mod.__file__, encoding="utf-8").read()
        assert "successor2" not in src, mod.__name__
    init_src = open(os.path.join(pkg_dir, "__init__.py"), encoding="utf-8").read()
    assert "successor2" not in init_src


def test_run_all_path_does_not_reference_successor2():
    import chewme_audit.detectors as det_pkg

    init_src = open(
        os.path.join(os.path.dirname(det_pkg.__file__), "__init__.py"),
        encoding="utf-8",
    ).read()
    assert "successor2" not in init_src
    assert "dead_context_v4_successor2" not in sys.modules


if __name__ == "__main__":
    test_measurable_contents_exact()
    print("PASS test_measurable_contents_exact")
    test_no_measurable_module_imports_successor2()
    print("PASS test_no_measurable_module_imports_successor2")
    test_run_all_path_does_not_reference_successor2()
    print("PASS test_run_all_path_does_not_reference_successor2")
    print("3 passed, 0 failed")
