"""Regression suite: detectors must fire on known waste instances.

The public-trace premise data is the regression suite. Fixtures use
REAL excerpts from the nebius SWE-agent trajectories (the same data
behind reports/audit-premise.md), so a detector that stops firing on
them is a regression, not a test artifact.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import detectors
from chewme_audit.model import Step, Trace

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    steps = []
    with open(os.path.join(FIXDIR, name), encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if line:
                steps.append(Step("fixture", i, json.loads(line)["text"]))
    return Trace("fixture", steps)


def test_repeated_calls_fires_on_error_loop():
    trace = _load_fixture("error_loop.jsonl")
    findings = detectors.repeated_calls.run(trace)
    assert findings, "must fire on the 9x error loop"
    f = findings[0]
    assert f.detail["occurrences"] == 9, f.detail
    # waste = (occurrences-1) x tokens of one occurrence
    from chewme_audit import counting
    n, _ = counting.count(trace.steps[0].text, "deepseek")
    assert f.waste_tokens == 8 * n
    assert f.fix_key == "error_loop_dedup"


def test_repeated_calls_ignores_unique():
    trace = Trace("t", [Step("t", i, f"unique observation number {i} with padding x"*5)
                        for i in range(5)])
    assert detectors.repeated_calls.run(trace) == []


def test_near_duplicates_fires_on_reread():
    trace = _load_fixture("file_reread.jsonl")
    findings = detectors.near_duplicates.run(trace)
    assert findings, "must fire on the near-duplicate file re-read"
    assert findings[0].detail["similarity"] >= 0.85
    assert findings[0].fix_key in ("diff_read", "review_resend")


def test_near_duplicates_ignores_different():
    trace = Trace("t", [Step("t", 0, "the quick brown fox jumps over"),
                        Step("t", 1, "completely unrelated zzz qqq www")])
    assert detectors.near_duplicates.run(trace) == []


def test_oversized_unreferenced_fires():
    big = "RESULT " + ("abcdefghij012345 " * 300)  # >2KB, distinctive tokens
    trace = Trace("t", [Step("t", 0, big),
                        Step("t", 1, "short follow-up with no distinctive tokens")])
    findings = detectors.oversized_outputs.run(trace)
    assert findings, "must fire on large unreferenced output"
    assert findings[0].fix_key == "truncate_tool_output"


def test_oversized_ignores_referenced():
    token = "abcdefghij012345"
    big = "RESULT " + (token + " ") * 300
    trace = Trace("t", [Step("t", 0, big),
                        Step("t", 1, f"later we use {token} again")])
    assert detectors.oversized_outputs.run(trace) == []


def test_pretty_print_fires_on_indented_json():
    pretty = json.dumps({"a": 1, "b": [1, 2, 3], "c": {"d": "x" * 50}}, indent=2)
    trace = Trace("t", [Step("t", 0, pretty)])
    findings = detectors.pretty_print.run(trace)
    assert findings, "must fire on pretty-printed JSON"
    assert findings[0].waste_tokens > 0


def test_pretty_print_ignores_file_header():
    # Regression: the old is_json_shaped mangled "[File: ...]" headers.
    trace = Trace("t", [Step("t", 0, "[File: src/main.py] some content here")])
    assert detectors.pretty_print.run(trace) == []


def test_unmeasurable_never_priced():
    trace = Trace("t", [Step("t", i, f"step {i} text") for i in range(12)])
    notes = (detectors.unmeasurable.cache_layout_notes(trace)
             + detectors.unmeasurable.reasoning_notes(trace))
    assert notes
    assert all(not f.measurable and f.waste_tokens == 0 for f in notes)


def test_receipt_roundtrip():
    from chewme_audit import receipt as receipt_mod
    trace = Trace("t", [Step("t", 0, "same error"), Step("t", 1, "same error")])
    findings = detectors.repeated_calls.run(trace)
    r = receipt_mod.issue(findings[0], "deepseek")
    assert receipt_mod.verify(r)
    r["waste_tokens"] += 1
    assert not receipt_mod.verify(r), "tampered receipt must fail"
