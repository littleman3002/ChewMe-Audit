"""Tests for --api-log exact cache accounting and estimated/measured labeling."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import api_log as api_log_mod
from chewme_audit import detectors, report
from chewme_audit.model import Step, Trace


def _trace():
    return Trace("t", [Step("t", 0, "same error here"),
                       Step("t", 1, "same error here")])


def test_api_log_parses_generic_shape():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"request_id": "r1", "trace_id": "t", "step": 0,
                            "prompt_tokens": 1000, "cached_tokens": 800,
                            "completion_tokens": 50}) + "\n")
        path = f.name
    recs = api_log_mod.load_api_log(path)
    assert len(recs) == 1
    r = recs[0]
    assert (r.prompt_tokens, r.cached_tokens, r.completion_tokens) == (1000, 800, 50)
    assert api_log_mod.index_by_step(recs)[("t", 0)] is r
    os.unlink(path)


def test_api_log_parses_openai_shape():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({
            "id": "req-9",
            "usage": {"prompt_tokens": 500, "completion_tokens": 20,
                      "prompt_tokens_details": {"cached_tokens": 400}},
            "metadata": {"trace_id": "t", "step": 1}}) + "\n")
        path = f.name
    recs = api_log_mod.load_api_log(path)
    assert recs[0].cached_tokens == 400
    assert recs[0].trace_id == "t" and recs[0].step_idx == 1
    os.unlink(path)


def test_report_without_api_log_is_estimated():
    trace = _trace()
    findings = {"t": detectors.run_all(trace, "deepseek")}
    rep = report.build([trace], findings, "deepseek")
    assert rep["cache_accounting"] == "estimated"
    md = report.to_markdown(rep)
    assert "ESTIMATED" in md
    assert any("ESTIMATED" in lab for lab in rep["labels"])


def test_report_with_api_log_is_measured():
    trace = _trace()
    findings = {"t": detectors.run_all(trace, "deepseek")}
    recs = [api_log_mod.RequestUsage("r0", "t", 0, 1000, 800, 50),
            api_log_mod.RequestUsage("r1", "t", 1, 1100, 900, 50)]
    rep = report.build([trace], findings, "deepseek", api_log_records=recs)
    assert rep["cache_accounting"] == "measured"
    assert rep["api_log_requests_matched"] == 2
    md = report.to_markdown(rep)
    assert "EXACT" in md
    # exact denominator: billed input = cached@hit + missed@miss
    sheet_hit, sheet_miss = 0.003, 0.15
    expected = ((800 + 900) / 1e6 * sheet_hit
                + (200 + 200) / 1e6 * sheet_miss)
    assert abs(rep["total_input_dollars"] - expected) < 1e-9
