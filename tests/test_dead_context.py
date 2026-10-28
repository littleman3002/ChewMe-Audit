"""Dead-context detector tests: evidence rules E1-E4, exclusions,
result mapping, and the fix entry."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import fixes
from chewme_audit.detectors import dead_context as dc
from chewme_audit.model import Step, Trace


def _call(name, args, tid="t", idx=0):
    flat = {"name": name}
    flat.update(args)
    return Step(tid, idx, json.dumps(flat), role="assistant",
                tool_name=name)


def _trace(steps, tid="t"):
    t = Trace(trace_id=tid)
    t.steps = []
    for i, s in enumerate(steps):
        t.steps.append(Step(tid, i, s.text, role=s.role,
                            tool_name=s.tool_name))
    return t


def _view_trace(view_path, result, later):
    """Trace: view view_path (result=result), then `later` steps.

    later: list of Step (tool calls / prose / tool results) already
    built with placeholder idx; re-indexed by _trace."""
    steps = [_call("str_replace_editor",
                   {"command": "view", "path": view_path}),
             Step("t", 0, result, role="tool")]
    steps.extend(later)
    return _trace(steps)


CAT = ("Here's the result of running `cat -n` on /repo/a.py:\n"
       "   1\tdef foo():\n   2\t    return 1\n   3\t\n"
       "   4\tclass Bar:\n   5\t    pass\n")
CAT_B = ("Here's the result of running `cat -n` on /repo/b.py:\n"
         "   1\timport a\n   2\tfoo()\n")


def test_dead_flagged():
    t = _view_trace("/repo/a.py", CAT, [
        _call("execute_bash", {"command": "pytest -q"}),
    ])
    findings, info = dc.assess_and_flag(t)
    assert len(findings) == 1, info
    f = findings[0]
    assert f.detector == "dead_context"
    assert f.fix_key == "dead_context"
    assert f.measurable is True
    assert f.detail["path"] == "/repo/a.py"
    assert f.detail["evidence"] == {"E1_path_arg": False,
                                    "E2_edit_later": False,
                                    "E3_patch": False,
                                    "E4_symbol_arg": False}
    assert f.detail["symbols"] == ["foo", "Bar"]
    assert f.waste_tokens > 0
    assert info["coverage"]["dead_files"] == 1
    assert info["coverage"]["live_files"] == 0


def test_live_via_e1_full_path():
    t = _view_trace("/repo/a.py", CAT, [
        _call("execute_bash",
              {"command": "grep -rn foo /repo/a.py"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []


def test_live_via_e1_basename_boundary():
    # v2: basename leg needs a matching parent directory downstream.
    # (A bare 'a.py' token would fire the token leg instead, so the
    # basename leg is exercised with a 'path=' form, where the
    # basename is not a clean token.)
    t = _view_trace("/repo/django_bird/a.py", CAT, [
        _call("execute_bash",
              {"command": "path=django_bird/a.py"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
    a = dc.assess_trace(t)
    assert a["live"][0]["e1_kind"] == "basename"
    # ... but the basename alone (parent never mentioned) is dead.
    t = _view_trace("/repo/django_bird/a.py", CAT, [
        _call("execute_bash", {"command": "path=a.py"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1


def test_basename_inside_other_name_is_not_e1():
    # "core.py" must not match inside "test_core.py".
    t = _view_trace("/repo/core.py", CAT, [
        _call("execute_bash",
              {"command": "pytest test_core.py -q"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1


def test_live_via_e2_edit_later():
    t = _view_trace("/repo/a.py", CAT, [
        _call("str_replace_editor",
              {"command": "str_replace", "path": "/repo/a.py",
               "old_str": "x", "new_str": "y"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []


def test_live_via_e3_patch_supplied():
    t = _view_trace("/repo/a.py", CAT, [
        _call("execute_bash", {"command": "pytest -q"}),
    ])
    findings, _ = dc.assess_and_flag(t, patch_files={"a.py"})
    assert findings == []
    # ... but without the patch it is dead.
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1


def test_e3_fallback_edited_anywhere():
    # No patch supplied: an edit BEFORE the view still counts
    # (conservative fallback, recorded in detail).
    steps = [_call("str_replace_editor",
                   {"command": "str_replace", "path": "/repo/a.py",
                    "old_str": "x", "new_str": "y"}),
             _call("str_replace_editor",
                   {"command": "view", "path": "/repo/a.py"}),
             Step("t", 0, CAT, role="tool"),
             _call("execute_bash", {"command": "pytest -q"})]
    t = _trace(steps)
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
    # With a patch supplied that does NOT contain the file, the
    # earlier edit does not save it.
    findings, _ = dc.assess_and_flag(t, patch_files={"other.py"})
    assert len(findings) == 1
    assert findings[0].detail["patch_mode"] == "supplied"


def test_live_via_e4_symbol_in_later_args():
    t = _view_trace("/repo/a.py", CAT, [
        _call("execute_bash",
              {"command": "python -c 'from a import foo; foo()'"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []


def test_prose_mention_is_not_evidence():
    steps = [_call("str_replace_editor",
                   {"command": "view", "path": "/repo/a.py"}),
             Step("t", 0, CAT, role="tool"),
             Step("t", 0, "The file /repo/a.py defines foo, which "
                         "looks correct.", role="assistant",
                  tool_name="message"),
             _call("execute_bash", {"command": "pytest -q"})]
    t = _trace(steps)
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1


def test_later_view_result_is_not_evidence():
    # Strict design: file B's view RESULT importing A does not make
    # A live (the loose first test counted it; this module does not).
    steps = [_call("str_replace_editor",
                   {"command": "view", "path": "/repo/a.py"}),
             Step("t", 0, CAT, role="tool"),
             _call("str_replace_editor",
                   {"command": "view", "path": "/repo/b.py"}),
             Step("t", 0, CAT_B, role="tool"),
             _call("execute_bash", {"command": "pytest -q"})]
    t = _trace(steps)
    findings, info = dc.assess_and_flag(t)
    assert [f.detail["path"] for f in findings] == ["/repo/a.py",
                                                    "/repo/b.py"]
    assert info["coverage"]["dead_files"] == 2
    assert info["coverage"]["live_files"] == 0


def test_repeated_view_is_live():
    steps = [_call("str_replace_editor",
                   {"command": "view", "path": "/repo/a.py"}),
             Step("t", 0, CAT, role="tool"),
             _call("str_replace_editor",
                   {"command": "view", "path": "/repo/a.py"}),
             Step("t", 0, CAT, role="tool"),
             _call("execute_bash", {"command": "pytest -q"})]
    t = _trace(steps)
    findings, info = dc.assess_and_flag(t)
    assert findings == []
    assert info["coverage"]["unique_files"] == 1


def test_dir_listing_excluded():
    t = _view_trace("/workspace", "Here's the files and directories "
                    "up to 2 levels deep in /workspace:\n/workspace/\n",
                    [_call("execute_bash", {"command": "pytest -q"})])
    findings, info = dc.assess_and_flag(t)
    assert findings == []
    assert info["coverage"]["dir_listings"] == 1
    assert info["coverage"]["unique_files"] == 0


def test_error_result_excluded():
    t = _view_trace("/repo/nope.py", "ERROR:\nFile not found: "
                    "/repo/nope.py\n",
                    [_call("execute_bash", {"command": "pytest -q"})])
    findings, info = dc.assess_and_flag(t)
    assert findings == []
    assert info["coverage"]["error_views"] == 1


def test_multi_call_block_result_mapping():
    # One assistant message, two view calls; results in order.
    steps = [_call("str_replace_editor",
                   {"command": "view", "path": "/repo/a.py"}),
             _call("str_replace_editor",
                   {"command": "view", "path": "/repo/b.py"}),
             Step("t", 0, CAT, role="tool"),
             Step("t", 0, CAT_B, role="tool"),
             _call("execute_bash", {"command": "pytest -q"})]
    t = _trace(steps)
    a = dc.assess_trace(t)
    by_path = {f["path"]: f for f in a["files"]}
    assert by_path["/repo/a.py"]["symbols"] == ["foo", "Bar"]
    # v2: the module-level import binding is now an E4 symbol.
    assert by_path["/repo/b.py"]["symbols"] == ["a"]
    # b.py's result imports a and calls foo — but view RESULT content
    # is not evidence, so both are dead. (v2: b.py's symbols are now
    # ["a"] — the module-level import binding — but nothing downstream
    # uses it, so the file is still dead.)
    assert a["coverage"]["dead_files"] == 2


def test_view_at_end_is_dead_with_flag():
    t = _view_trace("/repo/a.py", CAT, [])
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1
    assert findings[0].detail["at_end"] is True


def test_aggregate():
    t1 = _view_trace("/repo/a.py", CAT, [
        _call("execute_bash", {"command": "pytest -q"})])
    t2 = _view_trace("/repo/b.py", CAT_B, [
        _call("execute_bash", {"command": "grep b.py ."}),
    ])
    _, i1 = dc.assess_and_flag(t1)
    _, i2 = dc.assess_and_flag(t2)
    agg = dc.aggregate([i1, i2])
    assert agg["coverage"]["traces"] == 2
    assert agg["coverage"]["dead_files"] == 1
    assert agg["coverage"]["live_files"] == 1
    assert 0.0 < agg["dead_char_share"] < 1.0


def test_fix_entry_exists():
    fix = fixes.get("dead_context")
    assert fix is not None
    assert "stub" in fix["title"].lower()
    assert "NOT replay-tested" in fix["safety"]
    assert "dead_context_stub" in fix["snippet"]


def test_run_entry_and_run_all_wiring():
    from chewme_audit.detectors import run_all
    t = _view_trace("/repo/a.py", CAT, [
        _call("execute_bash", {"command": "pytest -q"}),
    ])
    assert len(dc.run(t)) == 1
    found = [f for f in run_all(t) if f.detector == "dead_context"]
    assert len(found) == 1


# ---- v2 rule fixes (dead-context-v2-report.md) ----

CAT_CONFIG = ("Here's the result of running `cat -n` on "
              "/repo/reana_client/config.py:\n"
              "   1\tREANA_YAML_VALID_FILE_NAMES = ['reana.yaml']\n"
              "   2\t\n"
              "   3\tdef load_config():\n   4\t    pass\n")

CAT_INIT = ("Here's the result of running `cat -n` on "
            "/repo/tcgdexsdk/__init__.py:\n"
            "   1\tfrom .enums import Language\n"
            "   2\t\n"
            "   3\t__all__ = ['Language']\n")


def test_v2_e1_dotted_module_path():
    # v1 false flag 2: 'from reana_client.config import X' names
    # reana_client/config.py. The dotted leg fires (and E4 sees the
    # constant too); check the leg attribution via assess_trace.
    t = _view_trace("/repo/reana_client/config.py", CAT_CONFIG, [
        _call("execute_bash",
              {"command": "python -c 'from reana_client.config "
                          "import REANA_YAML_VALID_FILE_NAMES'"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
    a = dc.assess_trace(t)
    live = a["live"][0]
    assert live["e1_kind"] == "dotted"
    assert live["evidence_symbol_kind"] == "assign"
    # ... a different module's dotted path does not save it.
    t = _view_trace("/repo/reana_client/config.py", CAT_CONFIG, [
        _call("execute_bash",
              {"command": "python -c 'from other.config import X'"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1


def test_v2_e1_dotted_package_init():
    # __init__.py denotes the package: 'from tcgdexsdk.enums import
    # Language' is a reference to tcgdexsdk/__init__.py (v1 false
    # flag 3, also fixed by the E4 import binding below).
    t = _view_trace("/repo/tcgdexsdk/__init__.py", CAT_INIT, [
        _call("execute_bash",
              {"command": "from tcgdexsdk.enums import Language"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
    a = dc.assess_trace(t)
    assert a["live"][0]["e1_kind"] == "dotted"


def test_v2_e4_module_level_constant():
    # E4 alone (no module path downstream): the constant used by
    # name is genuine use.
    t = _view_trace("/repo/reana_client/config.py", CAT_CONFIG, [
        _call("execute_bash",
              {"command": "python -c "
                          "'print(REANA_YAML_VALID_FILE_NAMES)'"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
    a = dc.assess_trace(t)
    assert a["live"][0]["evidence_symbol"] == \
        "REANA_YAML_VALID_FILE_NAMES"
    assert a["live"][0]["evidence_symbol_kind"] == "assign"


def test_v2_e4_import_binding_and_reexport():
    # E4 alone: 'Language' bound by 'from .enums import Language'
    # (and re-exported via __all__) and used by name downstream.
    t = _view_trace("/repo/tcgdexsdk/__init__.py", CAT_INIT, [
        _call("execute_bash",
              {"command": "python -c 'print(Language)'"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
    a = dc.assess_trace(t)
    assert a["live"][0]["evidence_symbol"] == "Language"
    assert a["live"][0]["evidence_symbol_kind"] == "import"


def test_v2_e4_stdlib_import_binding_skipped():
    # 'import os' binds nothing usable: the viewed file merely also
    # imports os. Downstream os use does not save it.
    cat = ("Here's the result of running `cat -n` on /repo/x.py:\n"
           "   1\timport os\n   2\timport sys\n   3\t\n"
           "   4\tdef foo():\n   5\t    return 1\n")
    t = _view_trace("/repo/x.py", cat, [
        _call("execute_bash",
              {"command": "python -c 'os.path.join(\"a\")'"}),
    ])
    findings, info = dc.assess_and_flag(t)
    assert len(findings) == 1
    a = dc.assess_trace(t)
    assert a["dead"][0]["symbols"] == ["foo"]


def test_v2_e1_basename_same_name_different_file():
    # v1 bias gauge: 18/21 basename-only live files were
    # same-name-different-file. Viewed a/__init__.py, downstream
    # names b/__init__.py — parent 'a' never mentioned, so dead.
    t = _view_trace("/repo/a/__init__.py", CAT, [
        _call("execute_bash",
              {"command": "python b/__init__.py"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1


def test_v2_e1_basename_generic_parent_dropped():
    # Parent 'src' is too generic to discriminate: basename alone
    # under a generic parent gets no basename leg.
    t = _view_trace("/repo/src/__init__.py", CAT, [
        _call("execute_bash",
              {"command": "path=src/__init__.py"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1
    # ... but the adjacent 'src/__init__.py' token still saves it.
    t = _view_trace("/repo/src/__init__.py", CAT, [
        _call("execute_bash",
              {"command": "python src/__init__.py"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []


def test_v2_e4_future_import_binding_skipped():
    # 'from __future__ import annotations' binds nothing usable:
    # __future__ is stdlib. Downstream 'annotations' (e.g. another
    # file's identical future-import in an edit) does not save it.
    # (Found by the v1 false-flag retest: views.py went live on a
    # bogus 'annotations' binding because __future__ was missing
    # from the skip list.)
    cat = ("Here's the result of running `cat -n` on /repo/x.py:\n"
           "   1\tfrom __future__ import annotations\n"
           "   2\t\n"
           "   3\tdef foo():\n   4\t    return 1\n")
    t = _view_trace("/repo/x.py", cat, [
        _call("execute_bash",
              {"command": "python -c 'from __future__ import "
                          "annotations'"}),
    ])
    findings, info = dc.assess_and_flag(t)
    assert len(findings) == 1
    a = dc.assess_trace(t)
    assert a["dead"][0]["symbols"] == ["foo"]


def test_v2_e4_common_word_needs_code_context():
    # 'formatter' is a common word: a bare word match in args is
    # prose, not use.
    cat = ("Here's the result of running `cat -n` on /repo/f.py:\n"
           "   1\tdef formatter(x):\n   2\t    return str(x)\n")
    t = _view_trace("/repo/f.py", cat, [
        _call("execute_bash", {"command": "echo formatter"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert len(findings) == 1
    # ... called, it is genuine use.
    t = _view_trace("/repo/f.py", cat, [
        _call("execute_bash",
              {"command": "python -c 'formatter(1)'"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
    # ... and an import clause is code context too.
    t = _view_trace("/repo/f.py", cat, [
        _call("execute_bash",
              {"command": "python -c 'from f import formatter'"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
    # ... while a non-common symbol still matches on a bare word.
    t = _view_trace("/repo/a.py", CAT, [
        _call("execute_bash", {"command": "echo foo"}),
    ])
    findings, _ = dc.assess_and_flag(t)
    assert findings == []
