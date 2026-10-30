"""Tests for dead_context_v4_successor2: the enlarged name set.

Covers: the §2b conditional-chain recursion (If/Try/With, all
binding types, function/class bodies excluded), the fallback
block-stack parity, S_trace H1/H2/H3 (including the
non-circularity gate, cross-file pins, Ruling 2, and failure
defeat), provenance tags, the carried-over arms (exact / 1b /
ratified Arm 2 / pandera / package-level silence / star split),
MEASURABLE non-registration.

This is the successor2-only subset; the frozen-successor sanity
tests live in the local, unshipped companion file.

Mirrors the test_dead_context_v4_successor.py helpers.
Successor2 is NOT in MEASURABLE (implementation + gate only).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chewme_audit.detectors import dead_context_v4_successor2 as s2
from chewme_audit.detectors import MEASURABLE
from chewme_audit.model import Step, Trace


def _call(name, args, tid="t", idx=0):
    flat = {"name": name}
    flat.update(args)
    return Step(tid, idx, json.dumps(flat), role="assistant",
                tool_name=name)


def _result(text, tid="t", idx=0):
    return Step(tid, idx, text, role="tool")


def _cat_result(path, lines):
    out = ["Here's the result of running `cat -n` on %s:" % path]
    for i, ln in enumerate(lines, start=1):
        out.append("%5d\t%s" % (i, ln))
    return "\n".join(out)


def _view(path, idx=0, view_range=None):
    args = {"command": "view", "path": path}
    if view_range is not None:
        args["view_range"] = view_range
    return _call("str_replace_editor", args, idx=idx)


def _edit(path, content, idx=2, cmd="create"):
    if cmd == "create":
        args = {"command": "create", "path": path, "file_text": content}
    else:
        args = {"command": "str_replace", "path": path,
                "old_str": "", "new_str": content}
    return _call("str_replace_editor", args, idx=idx)


def _bash(cmd, idx=3):
    return _call("execute_bash", {"command": cmd}, idx=idx)


def _trace(view_path, view_lines, downstream, view_range=None):
    steps = [_view(view_path, idx=0, view_range=view_range),
             _result(_cat_result(view_path, view_lines), idx=1)]
    steps.extend(downstream)
    return Trace(trace_id="t", steps=steps)


def _fired(trace):
    a = s2.assess_trace(trace)
    assert len(a["files"]) == 1, a["files"]
    return a["files"][0]


def _assert_fire(trace, arms=None, prov=None):
    f = _fired(trace)
    assert f["fired"], (f["path"], f["matches"])
    if arms is not None:
        got = {m["arm"] for m in f["matches"]}
        assert arms <= got, (arms, got, f["matches"])
    if prov is not None:
        got = {m["provenance"] for m in f["matches"]}
        assert prov <= got, (prov, got, f["matches"])
    return f


def _assert_silent(trace):
    f = _fired(trace)
    assert not f["fired"], (f["path"], f["matches"])
    return f


def _file_for(trace, suffix):
    a = s2.assess_trace(trace)
    for f in a["files"]:
        if f["norm"].endswith(suffix):
            return f
    raise AssertionError("no file %s in %s" % (
        suffix, [f["norm"] for f in a["files"]]))


# ---------------------------------------------------------------- §2

def test_derive_plain():
    assert s2.derive_module_paths(
        "/workspace/inst/pkg/sub.py") == frozenset({"pkg.sub"})


def test_derive_init():
    assert s2.derive_module_paths(
        "/workspace/inst/pkg/__init__.py") == frozenset({"pkg"})


def test_derive_src_candidates():
    assert s2.derive_module_paths(
        "/workspace/inst/src/pkg/mod.py") == frozenset(
        {"src.pkg.mod", "pkg.mod"})


# ---------------------------------------------------------------- §2b AST

def test_cond_if_import_win32():
    # guard-11 shape: trio register_with_iocp.
    res = _cat_result("/workspace/inst/trio/lowlevel.py", [
        "import sys",
        "if sys.platform == \"win32\":",
        "    from ._core import register_with_iocp",
    ])
    a = s2.analyze_viewed(res)
    assert not a["fallback"]
    assert "register_with_iocp" in a["defined"]
    assert "register_with_iocp" in a["reexport"]
    assert a["prov"]["register_with_iocp"] == "cond"


def test_cond_type_checking_imports():
    # guard-13/14 shapes: narwhals DaskLazyFrame + Self.
    res = _cat_result("/workspace/inst/narwhals/_expression_parsing.py", [
        "if TYPE_CHECKING:",
        "    from narwhals._dask.dataframe import DaskLazyFrame",
        "    from typing_extensions import Self",
    ])
    a = s2.analyze_viewed(res)
    assert a["prov"]["DaskLazyFrame"] == "cond"
    assert a["prov"]["Self"] == "cond"
    assert "DaskLazyFrame" in a["reexport"]
    assert "Self" in a["reexport"]


def test_cond_nested_chains():
    res = _cat_result("/workspace/inst/pkg/mod.py", [
        "import sys",
        "if sys.platform == \"win32\":",
        "    if True:",
        "        from .deep import DeepName",
        "    else:",
        "        from .other import ElseName",
        "try:",
        "    from .t import TryName",
        "except ImportError:",
        "    from .e import ExceptName",
        "finally:",
        "    from .f import FinallyName",
        "with open(\"x\") as fh:",
        "    from .w import WithName",
    ])
    a = s2.analyze_viewed(res)
    for nm in ("DeepName", "ElseName", "TryName", "ExceptName",
               "FinallyName", "WithName"):
        assert nm in a["defined"], nm
        assert a["prov"][nm] == "cond", nm


def test_cond_definition_class():
    res = _cat_result("/workspace/inst/pkg/mod.py", [
        "import sys",
        "if sys.platform == \"win32\":",
        "    class Win32Foo:",
        "        pass",
    ])
    a = s2.analyze_viewed(res)
    assert "Win32Foo" in a["defined"]
    assert a["prov"]["Win32Foo"] == "cond"


def test_func_body_import_excluded():
    res = _cat_result("/workspace/inst/pkg/mod.py", [
        "def top():",
        "    import localmod",
        "    return localmod",
        "class C:",
        "    import classmod",
    ])
    a = s2.analyze_viewed(res)
    assert "localmod" not in a["defined"]
    assert "classmod" not in a["defined"]
    assert "top" in a["defined"] and a["prov"]["top"] == "plain"


def test_all_only_excluded_ruling2():
    # Ruling 2: __all__ alone never confers membership.
    res = _cat_result("/workspace/inst/pkg/mod.py", [
        "__all__ = [\"Ghost\"]",
        "def Real():",
        "    pass",
    ])
    a = s2.analyze_viewed(res)
    assert "Ghost" not in a["defined"]
    assert "Ghost" not in a["reexport"]
    assert "Real" in a["defined"]


def test_all_present_promoted():
    res = _cat_result("/workspace/inst/pkg/mod.py", [
        "def Name():",
        "    pass",
        "__all__ = [\"Name\", \"Missing\"]",
    ])
    a = s2.analyze_viewed(res)
    assert "Name" in a["reexport"]
    assert "Missing" not in a["reexport"]


# ---------------------------------------------------------------- fallback

def test_fallback_cond_import():
    src = ("def Broken(:\n    pass\n"
           "if sys.platform == \"win32\":\n"
           "    from ._core import register_with_iocp\n")
    d, r, p, deg = s2._names_from_fallback(src)
    assert "register_with_iocp" in d
    assert p["register_with_iocp"] == "cond"
    assert "register_with_iocp" in r


def test_fallback_func_body_import_excluded():
    src = ("def Broken(:\n    pass\n"
           "def outer():\n"
           "    import localmod\n"
           "    from .x import funcmod\n")
    d, r, p, deg = s2._names_from_fallback(src)
    assert "localmod" not in d
    assert "funcmod" not in d


def test_fallback_col0_plain():
    src = ("def Broken(:\n    pass\n"
           "import os\n"
           "from .dep import Dep\n")
    d, r, p, deg = s2._names_from_fallback(src)
    assert p["os"] == "plain" and p["Dep"] == "plain"


# ---------------------------------------------------------------- H1

def _chalice_trace():
    v1 = ["import os"] + ["# filler"] * 99
    v2 = ["# filler"] * 926 + ["class Chalice:", "    pass"]
    steps = [
        _view("/workspace/inst/chalice/app.py", idx=0,
              view_range=[1, 100]),
        _result(_cat_result("/workspace/inst/chalice/app.py", v1),
                idx=1),
        _view("/workspace/inst/chalice/app.py", idx=2,
              view_range=[900, 950]),
        _result(_cat_result("/workspace/inst/chalice/app.py", v2),
                idx=3),
        _edit("/workspace/inst/repro.py",
              "from chalice.app import Chalice\napp = Chalice()\n",
              idx=4),
    ]
    return Trace(trace_id="t", steps=steps)


def test_h1_cross_view_union():
    f = _assert_fire(_chalice_trace(), arms={"exact"},
                      prov={"trace-harvested"})
    assert "Chalice" in f["matched_symbols"]


def test_h1_other_file_no_contamination():
    # A view of a DIFFERENT file must never enter V's S.
    steps = [
        _view("/workspace/inst/pkg/sub.py", idx=0),
        _result(_cat_result("/workspace/inst/pkg/sub.py",
                            ["def Other():", "    pass"]), idx=1),
        _view("/workspace/inst/other/util.py", idx=2),
        _result(_cat_result("/workspace/inst/other/util.py",
                            ["def Name():", "    pass"]), idx=3),
        _edit("/workspace/inst/repro.py",
              "from pkg.sub import Name\n", idx=4),
    ]
    t = Trace(trace_id="t", steps=steps)
    f = _file_for(t, "pkg/sub.py")
    assert not f["fired"], f["matches"]


# ---------------------------------------------------------------- H2

def _dwave_trace(grep_line):
    steps = [
        _view("/workspace/inst/dwave/cloud/solver.py", idx=0,
              view_range=[1, 50]),
        _result(_cat_result("/workspace/inst/dwave/cloud/solver.py",
                            ["# partial"] * 50), idx=1),
        _bash("grep -rn UnstructuredSolver dwave/cloud/solver.py",
              idx=2),
        _result(grep_line, idx=3),
        _edit("/workspace/inst/repro.py",
              "from dwave.cloud.solver import UnstructuredSolver\n"
              "s = UnstructuredSolver()\n", idx=4),
    ]
    return Trace(trace_id="t", steps=steps)


def test_h2_grep_harvest():
    t = _dwave_trace(
        "dwave/cloud/solver.py:312:class UnstructuredSolver(BaseSolver):")
    _assert_fire(t, arms={"exact"}, prov={"trace-harvested"})


def test_h2_wrong_path_no_harvest():
    t = _dwave_trace(
        "other/cloud/solver.py:312:class UnstructuredSolver(BaseSolver):")
    _assert_silent(t)


def test_h2_assign_shape():
    t = _dwave_trace("dwave/cloud/solver.py:40:UnstructuredSolver = 5")
    _assert_fire(t, arms={"exact"}, prov={"trace-harvested"})


# ---------------------------------------------------------------- H3

def _kafka_trace(extra_steps=()):
    steps = [
        _view("/workspace/inst/kafka/structs.py", idx=0,
              view_range=[1, 40]),
        _result(_cat_result("/workspace/inst/kafka/structs.py",
                            ["# partial"] * 40), idx=1),
        _edit("/workspace/inst/kafka/cluster.py",
              "from .structs import BrokerMetadata\n", idx=2),
    ]
    steps.extend(extra_steps)
    nxt = max(s.step_idx for s in steps) + 1
    steps.append(_edit(
        "/workspace/inst/repro.py",
        "from kafka.structs import BrokerMetadata\nb = BrokerMetadata()\n",
        idx=nxt))
    return Trace(trace_id="t", steps=steps)


def test_h3_sibling_import():
    _assert_fire(_kafka_trace(), arms={"exact"},
                  prov={"trace-harvested"})


def test_h3_self_proof_silent():
    # Candidate unit alone: the import must not prove its own name.
    steps = [
        _view("/workspace/inst/kafka/structs.py", idx=0,
              view_range=[1, 40]),
        _result(_cat_result("/workspace/inst/kafka/structs.py",
                            ["# partial"] * 40), idx=1),
        _edit("/workspace/inst/repro.py",
              "from kafka.structs import BrokerMetadata\n"
              "b = BrokerMetadata()\n", idx=2),
    ]
    _assert_silent(Trace(trace_id="t", steps=steps))


def test_h3_cross_module_silent():
    # Sibling import resolving to a DIFFERENT module proves nothing.
    steps = [
        _view("/workspace/inst/kafka/structs.py", idx=0,
              view_range=[1, 40]),
        _result(_cat_result("/workspace/inst/kafka/structs.py",
                            ["# partial"] * 40), idx=1),
        _edit("/workspace/inst/kafka/other.py",
              "from other.structs import BrokerMetadata\n", idx=2),
        _edit("/workspace/inst/repro.py",
              "from kafka.structs import BrokerMetadata\n"
              "b = BrokerMetadata()\n", idx=3),
    ]
    _assert_silent(Trace(trace_id="t", steps=steps))


def test_h3_star_proves_nothing():
    # A star import proves the MODULE was imported (so the file
    # still fires via the star itself), but proves no NAME: the
    # candidate's BrokerMetadata import must not fire via H3.
    steps = [
        _view("/workspace/inst/kafka/structs.py", idx=0,
              view_range=[1, 40]),
        _result(_cat_result("/workspace/inst/kafka/structs.py",
                            ["# partial"] * 40), idx=1),
        _edit("/workspace/inst/kafka/cluster.py",
              "from .structs import *\n", idx=2),
        _edit("/workspace/inst/repro.py",
              "from kafka.structs import BrokerMetadata\n"
              "b = BrokerMetadata()\n", idx=3),
    ]
    a = s2.assess_trace(Trace(trace_id="t", steps=steps))
    f = a["files"][0]
    assert f["fired"], "star import itself is genuine evidence"
    assert all(m["name"] != "BrokerMetadata" for m in f["matches"]), \
        f["matches"]


def test_h3_failure_defeat():
    # H3(c): an ImportError proving the import wrong defeats the
    # harvest — the sibling proof no longer counts.
    defeat = _result(
        "Traceback (most recent call last):\n"
        "ImportError: cannot import name 'BrokerMetadata' "
        "from 'kafka.structs'", idx=3)
    t = _kafka_trace(extra_steps=[defeat])
    _assert_silent(t)


# ---------------------------------------------------------------- arms

def test_arm1_exact_fire():
    t = _trace("/workspace/inst/pkg/sub.py",
               ["def Name():", "    pass"],
               [_edit("/workspace/inst/repro.py",
                       "from pkg.sub import Name\n", idx=2)])
    f = _assert_fire(t, arms={"exact"})
    assert f["matches"][0]["provenance"] is None


def test_arm1b_fire():
    t = _trace("/workspace/inst/pkg/sub.py",
               ["def Name():", "    pass"],
               [_edit("/workspace/inst/repro.py",
                       "from pkg import sub\n", idx=2)])
    _assert_fire(t, arms={"submodule-attribute"})


def test_arm2_draft_shape_fire():
    t = _trace("/workspace/inst/pennylane/embeddings/__init__.py",
               ["from .basis import BasisEmbedding"],
               [_edit("/workspace/inst/repro.py",
                       "import pennylane as qml\n"
                       "qml.BasisEmbedding(4, wires=range(4))\n", idx=2)])
    _assert_fire(t, arms={"re-export-ancestor"})


def test_arm2_idx242_silent():
    t = _trace("/workspace/inst/pandas/io/excel/__init__.py",
               ["from pandas.io.excel._base import (",
                "    ExcelFile, ExcelWriter, read_excel,)",
                "__all__ = [\"ExcelFile\", \"ExcelWriter\", "
                "\"read_excel\"]"],
               [_edit("/workspace/inst/repro.py",
                       "import pandas as pd\n"
                       "df = pd.read_excel('f.xlsx')\n", idx=2)])
    _assert_silent(t)


def test_pandera_stem_silent():
    t = _trace("/workspace/inst/pandera/polars.py",
               ["def polars_func():", "    pass"],
               [_edit("/workspace/inst/repro.py",
                       "import polars as pl\ndf = pl.DataFrame()\n",
                       idx=2)])
    _assert_silent(t)


def test_package_level_silent():
    t = _trace("/workspace/inst/attune/_arrangement.py",
               ["__all__ = [\"Arrangement\"]",
                "class Arrangement:", "    pass"],
               [_edit("/workspace/inst/repro.py",
                       "import attune\na = attune.Arrangement()\n",
                       idx=2)])
    _assert_silent(t)


def test_star_exact_tagged():
    t = _trace("/workspace/inst/pkg/sub.py",
               ["def Name():", "    pass"],
               [_edit("/workspace/inst/repro.py",
                       "from pkg.sub import *\n", idx=2)])
    f = _assert_fire(t, arms={"exact"})
    assert any(m["tag"] == "star-import" for m in f["matches"])


def test_cond_import_tag():
    t = _trace("/workspace/inst/trio/lowlevel.py",
               ["import sys",
                "if sys.platform == \"win32\":",
                "    from ._core import register_with_iocp"],
               [_edit("/workspace/inst/repro.py",
                       "from trio.lowlevel import register_with_iocp\n",
                       idx=2)])
    _assert_fire(t, arms={"exact"}, prov={"cond-import"})


# ---------------------------------------------------------------- misc

def test_not_in_measurable():
    if isinstance(MEASURABLE, dict):
        assert s2.DETECTOR not in MEASURABLE
    else:
        names = set()
        for v in MEASURABLE:
            names.add(getattr(v, "detector", v))
        assert s2.DETECTOR not in names
