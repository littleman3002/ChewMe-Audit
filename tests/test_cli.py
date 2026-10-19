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


def _fixture(name):
    return os.path.join(os.path.dirname(__file__), "fixtures", name)


def test_cost_meter_in_markdown():
    """The report must carry the audit's own cost meter: $0.00 API spend
    plus measured wall time, printed beside the waste it found."""
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        rc = cli.main([_fixture("error_loop.jsonl"), "--provider", "deepseek"])
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    assert rc == 0
    assert "- Audit cost: **$0.00** API spend (local-only run, no API calls)" in out
    assert "wall time" in out


def test_cost_meter_in_json():
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        rc = cli.main([_fixture("error_loop.jsonl"), "--provider", "deepseek",
                       "--output", "json"])
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    assert rc == 0
    import json as _json
    rep = _json.loads(out)
    assert rep["audit_api_spend_dollars"] == 0.0
    assert isinstance(rep["audit_wall_seconds"], float)
    assert rep["audit_wall_seconds"] >= 0.0
