"""Tests for cross-trace duplication detection."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import cross_trace as xt
from chewme_audit import counting as counting_mod
from chewme_audit.model import Step, Trace

_basis = counting_mod.PRICEABLE.copy().pop()
counting_mod.count = lambda text, provider="deepseek": (len(text) // 4, _basis)


def _trace(tid, texts):
    return Trace(tid, [Step(tid, i, t, role="tool") for i, t in enumerate(texts)])


def test_identical_obs_across_traces_flagged():
    shared = "file list: a.py b.py c.py " * 20
    t1 = _trace("a", [shared, "unique one here"])
    t2 = _trace("b", [shared, "something else entirely"])
    groups, total = xt.find_cross_trace_duplicates([t1, t2])
    assert len(groups) == 1
    assert groups[0]["n_traces"] == 2
    assert total == groups[0]["waste_tokens"] > 0


def test_unique_obs_not_flagged():
    t1 = _trace("a", ["alpha beta gamma"])
    t2 = _trace("b", ["delta epsilon zeta"])
    groups, total = xt.find_cross_trace_duplicates([t1, t2])
    assert groups == [] and total == 0


def test_three_way_counts_two_copies_wasted():
    shared = "same observation " * 30
    ts = [_trace(tid, [shared]) for tid in ("a", "b", "c")]
    groups, total = xt.find_cross_trace_duplicates(ts)
    assert len(groups) == 1
    assert groups[0]["n_traces"] == 3
    each = len(shared) // 4
    assert total == 2 * each


def test_assistant_messages_ignored():
    t1 = Trace("a", [Step("a", 0, "same text", role="assistant")])
    t2 = Trace("b", [Step("b", 0, "same text", role="assistant")])
    groups, total = xt.find_cross_trace_duplicates([t1, t2])
    assert groups == [] and total == 0
