"""Tests for --pricing overrides and --total-bill opt-in."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import detectors, pricing, report
from chewme_audit import counting as counting_mod
from chewme_audit.model import Step, Trace


def _trace():
    return Trace("t", [Step("t", 0, "same error here"),
                       Step("t", 1, "same error here")])


# Tests run without the lab's provider tokenizers, so force a priceable
# basis; the pricing logic under test is independent of the counter.
_basis = counting_mod.PRICEABLE.copy().pop()
counting_mod.count = lambda text, provider="deepseek": (len(text) // 4, _basis)


def _rep(**kw):
    t = _trace()
    findings = {"t": detectors.run_all(t, "deepseek")}
    return report.build([t], findings, "deepseek", **kw)


def test_pricing_override_changes_dollars():
    base = _rep()
    assert base["total_waste_dollars"] > 0
    sheets = pricing.apply_overrides(
        {"deepseek": {"miss_per_mtok": 0.30}})
    over = _rep(sheets=sheets)
    assert over["total_waste_dollars"] == base["total_waste_dollars"] * 2
    # recorded sheets untouched
    assert pricing.SHEETS["deepseek"]["miss_per_mtok"] == 0.15


def test_pricing_override_can_add_provider():
    sheets = pricing.apply_overrides(
        {"mycloud": {"model": "m1", "miss_per_mtok": 1.0,
                     "hit_per_mtok": 0.1, "out_per_mtok": 2.0}})
    assert pricing.waste_dollars(1_000_000, "mycloud", sheets) == 1.0
    assert pricing.waste_dollars(1_000_000, "mycloud") is None


def test_total_bill_off_by_default():
    rep = _rep()
    assert rep["waste_share_of_total_bill_illustrative"] is None
    assert rep["total_bill_included"] is False
    md = report.to_markdown(rep)
    assert "total bill" not in md.lower()
    assert "omitted by default" in " ".join(rep["labels"])


def test_total_bill_opt_in():
    rep = _rep(include_total_bill=True)
    assert rep["waste_share_of_total_bill_illustrative"] is not None
    assert rep["total_bill_included"] is True
    md = report.to_markdown(rep)
    assert "do not quote without this label" in md
