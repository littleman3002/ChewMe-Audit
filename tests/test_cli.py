"""CLI smoke tests: basic invocations must never crash.

Regression: a bare % in the --total-bill help string made
`chewme-audit --help` raise TypeError inside argparse's format_help
instead of printing (caught 2026-10-18, fixed by escaping to %%).
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import cli


def test_help_exits_zero():
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        try:
            cli.main(["--help"])
        except SystemExit as e:
            assert e.code == 0, f"--help exited with {e.code}"
        else:
            raise AssertionError("--help did not raise SystemExit")
    finally:
        sys.stdout = old
