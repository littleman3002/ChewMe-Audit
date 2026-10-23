"""Unverified-final-state detector tests: spec section 8.3 verdict
fixtures, section 4 predicates with amendment A3, the F4 split,
end types, and the section 7 report surface."""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import cli, report
from chewme_audit.detectors import unverified_final_state as ufs
from chewme_audit.model import Step, Trace


def _trace(pairs, tid="t"):
    t = Trace(trace_id=tid)
    t.steps = [Step(tid, i, text, role=role)
               for i, (role, text) in enumerate(pairs)]
    return t


def _cmd(c):
    return f"```\n{c}\n```"


def _assess(pairs, tid="t"):
    return ufs.assess_trace(_trace(pairs, tid))


ISSUE = ("user", "fix the bug (Open file: /repo/src/app.py)")


# ---- section 8.3 verdict fixtures ----

def test_verdict_pytest_green():
    assert ufs.verdict_of("5 passed in 0.31s") == "PASS"


def test_verdict_pytest_partial_is_fail():
    assert ufs.verdict_of("2 failed, 3 passed in 0.31s") == "FAIL"


def test_verdict_unittest_ok_and_failed():
    assert ufs.verdict_of("Ran 3 tests in 0.1s\n\nOK") == "PASS"
    assert ufs.verdict_of("Ran 3 tests\nFAILED (failures=1)") == "FAIL"
    assert ufs.verdict_of("Ran 3 tests\nFAILED") == "FAIL"


def test_verdict_plain_language_reports():
    assert ufs.verdict_of("All tests passed successfully") == "PASS"
    assert ufs.verdict_of("Test script completed successfully, "
                          "no errors.") == "PASS"
    assert ufs.verdict_of("Returning error code 1") == "FAIL"


def test_verdict_expected_error_inside_pass_is_pass():
    obs = ("Traceback (most recent call last):\n"
           "ValueError: expected boom\n3 passed in 0.2s")
    assert ufs.verdict_of(obs) == "PASS"


def test_verdict_empty_suite_is_unknown():
    assert ufs.verdict_of("no tests ran in 0.01s") == "UNKNOWN"
    assert ufs.verdict_of("") == "UNKNOWN"


def test_verdict_exit_code_beats_text():
    assert ufs.verdict_of("exit code: 0\nFAILED nonsense") == "PASS"
    assert ufs.verdict_of("exit code: 2\n5 passed") == "FAIL"


# ---- test-run recognition: execution, not mention ----

def test_mentions_are_not_test_runs():
    a = _assess([
        ISSUE,
        ("ai", _cmd("grep -rn pytest tests/")),
        ("user", "tests/test_app.py:3:import pytest"),
        ("ai", _cmd('find reframe -name "rfm_client.py"')),
        ("user", "no matches"),
        ("ai", _cmd("open reframe/frontend/statistics.py")),
        ("user", "[File: statistics.py]"),
    ])
    assert a["coverage"]["test_runs"] == 0


def test_reframe_checks_execution_is_a_run():
    a = _assess([
        ISSUE,
        ("ai", _cmd("./bin/reframe -c "
                    "unittests/resources/checks/hellocheck.py -r")),
        ("user", "[ReFrame Setup] version 4.0.0"),
    ])
    assert a["coverage"]["test_runs"] == 1


def test_direct_test_script_is_verification_not_a_run():
    # direct_test_*.py matches no test-file pattern in the spec's
    # table: executing it is a verification event, not a test run.
    a = _assess([
        ISSUE,
        ("ai", _cmd("edit 1:2")),
        ("user", "edited"),
        ("ai", _cmd("python direct_test_get_services.py")),
        ("user", "all good"),
        ("ai", _cmd("submit")),
    ])
    assert a["coverage"]["test_runs"] == 0
    assert "F3" not in a["flags"]  # the script execution verifies


def test_nose_module_run_is_a_run():
    # Stage C hand-check: 'python -m nose <test file>' is the
    # nosetests runner in module form; missing it manufactured
    # false F2/F3 flags.
    a = _assess([
        ISSUE,
        ("ai", _cmd("edit 1:2")),
        ("user", "edited"),
        ("ai", _cmd("python -m nose tests/test_app.py -q")),
        ("user", "OK"),
        ("ai", _cmd("submit")),
    ])
    assert a["coverage"]["test_runs"] == 1
    assert a["flags"] == {}


def test_test_file_execution_is_a_run():
    a = _assess([
        ISSUE,
        ("ai", _cmd("python test_get_services.py")),
        ("user", "1 passed"),
    ])
    assert a["coverage"]["test_runs"] == 1


def test_quoted_greater_than_is_not_a_shell_write():
    # Stage C hand-check phantom: a python -c analysis script
    # whose quoted code contains '>' (regex named groups) was
    # read as a shell edit to a nonsense target.
    a = _assess([
        ISSUE,
        ("ai", _cmd('python3 -c "import re; '
                    'p = re.compile(r\'(?P<name>[^:]+)\')"')),
        ("user", "pattern ok"),
    ])
    assert a["coverage"]["edits"] == 0


def test_stderr_dup_is_not_a_shell_write():
    a = _assess([
        ISSUE,
        ("ai", _cmd("python reproduce_issue.py 2>&1 | head -5")),
        ("user", "output"),
    ])
    assert a["coverage"]["edits"] == 0


def test_dev_null_redirection_is_not_an_edit():
    # Stage C hand-check: 'cmd > /dev/null' mutates no file; an
    # F1 resting on it was a false flag.
    a = _assess([
        ISSUE,
        ("ai", _cmd("edit 10:12")),
        ("user", "edited"),
        ("ai", _cmd("python -m pytest tests/ -q")),
        ("user", "5 passed in 0.3s"),
        ("ai", _cmd("mytool input.xml > /dev/null && echo ok")),
        ("user", "ok"),
        ("ai", _cmd("submit")),
    ])
    assert a["coverage"]["edits"] == 1
    assert a["flags"] == {}


def test_truncate_redirection_creates_its_target():
    # Stage C hand-check: 'echo ... > /tmp/a.py' after a pass is
    # the agent creating scratch, not editing a pre-existing
    # file — it must not qualify F1 under A3.
    a = _assess(_f1_trace([
        ("ai", _cmd("cd /tmp && echo 'print(1)' >a.py && python3 a.py")),
        ("user", "1"),
    ]))
    assert "F1" not in a["flags"]
    # ...while a truncating write to a file the trace has
    # already seen (pre-existing) still counts as its edit.
    a2 = _assess(_f1_trace([
        ("ai", _cmd("echo 'x = 1' > src/app.py")),
        ("user", "done"),
    ]))
    assert a2["flags"].get("F1") is True


def test_typed_step_fenced_block_is_not_a_command():
    # An adapter-typed step (tool_name set) carries structured
    # calls; a fenced snippet inside prose is not a command.
    t = Trace(trace_id="t")
    t.steps = [
        Step("t", 0, "issue (Open file: /repo/src/app.py)",
             role="user"),
        Step("t", 1, "summary\n```\nsed -i s/a/b/ src/app.py\n```",
             role="assistant", tool_name="message"),
    ]
    a = ufs.assess_trace(t)
    assert a["coverage"]["edits"] == 0


# ---- section 4 predicates + amendment A3 ----

def _f1_trace(post_pass_pairs):
    return [
        ISSUE,
        ("ai", _cmd("edit 10:12")),
        ("user", "edited"),
        ("ai", _cmd("python -m pytest tests/ -q")),
        ("user", "5 passed in 0.3s"),
    ] + post_pass_pairs + [("ai", _cmd("submit"))]


def test_f1_fires_on_preexisting_edit_after_pass():
    a = _assess(_f1_trace([
        ("ai", _cmd("edit 20:21")),
        ("user", "edited"),
    ]))
    assert a["flags"].get("F1") is True
    assert a["flags"].get("F3") is True
    assert a["end_type"] == "submitted"
    d = a["flag_details"]["F1"]
    assert d["post_edit_classes"] == ["source"]
    assert d["only_non_code"] is False
    assert d["post_edits"][0]["agent_created"] is False


def test_f1_a3_created_files_only_do_not_fire():
    a = _assess(_f1_trace([
        ("ai", _cmd("create verify_fix.py")),
        ("user", "created (Open file: /repo/verify_fix.py)"),
        ("ai", _cmd("edit 1:1")),
        ("user", "edited"),
    ]))
    assert "F1" not in a["flags"]


def test_f1_a3_mixed_created_and_preexisting_fires():
    a = _assess(_f1_trace([
        ("ai", _cmd("create verify_fix.py")),
        ("user", "created (Open file: /repo/src/app.py)"),
        ("ai", _cmd("edit 20:21")),
        ("user", "edited"),
    ]))
    assert a["flags"].get("F1") is True


def test_f2_fires_after_last_run_without_pass():
    a = _assess([
        ISSUE,
        ("ai", _cmd("edit 10:12")),
        ("user", "edited"),
        ("ai", _cmd("python -m pytest tests/ -q")),
        ("user", "2 failed, 3 passed in 0.3s"),
        ("ai", _cmd("edit 20:21")),
        ("user", "edited"),
        ("ai", _cmd("submit")),
    ])
    assert "F1" not in a["flags"]
    assert a["flags"].get("F2") is True


def test_clean_trace_no_flags():
    a = _assess([
        ISSUE,
        ("ai", _cmd("edit 10:12")),
        ("user", "edited"),
        ("ai", _cmd("python -m pytest tests/ -q")),
        ("user", "5 passed in 0.3s"),
        ("ai", _cmd("submit")),
    ])
    assert a["flags"] == {}


def test_f3_and_f3a_when_never_verified():
    a = _assess([
        ISSUE,
        ("ai", _cmd("edit 10:12")),
        ("user", "edited"),
        ("ai", _cmd("submit")),
    ])
    assert a["flags"].get("F3") is True
    assert a["flags"].get("F3a") is True


def test_reproduce_script_after_edit_clears_f3():
    a = _assess([
        ISSUE,
        ("ai", _cmd("edit 10:12")),
        ("user", "edited"),
        ("ai", _cmd("python reproduce_issue.py")),
        ("user", "bug reproduced before, gone now"),
        ("ai", _cmd("submit")),
    ])
    assert "F3" not in a["flags"]
    assert "F3a" not in a["flags"]


# ---- F4 split: pre-existing test files flag, created ones inform ----

def test_f4_preexisting_test_edit_flags():
    a = _assess([
        ("user", "fix it (Open file: /repo/tests/test_app.py)"),
        ("ai", _cmd("edit 5:6")),
        ("user", "edited"),
    ])
    assert a["flags"].get("F4") == 1
    assert a["info_test_edits"] == 0


def test_f4_created_test_file_is_informational():
    a = _assess([
        ISSUE,
        ("ai", _cmd("create tests/test_new.py")),
        ("user", "created (Open file: /repo/tests/test_new.py)"),
        ("ai", _cmd("edit 1:2")),
        ("user", "edited"),
    ])
    assert "F4" not in a["flags"]
    assert a["info_test_edits"] == 2  # the create + the later edit


def test_f4_rename_of_created_file_stays_created():
    # Stage C hand-check: 'mv assert_test.py verify_issue_test.py'
    # then editing the renamed file is editing the agent's own
    # file — provenance follows the file across the rename.
    def call(obj):
        return json.dumps(obj)
    t = _trace([
        ("user", "fix it"),
        ("assistant", call({"name": "str_replace_editor",
                            "command": "create",
                            "path": "/repo/assert_test.py"})),
        ("tool", "created"),
        ("assistant", call({"name": "execute_bash",
                            "command": "mv assert_test.py "
                                       "verify_issue_test.py"})),
        ("tool", "done"),
        ("assistant", call({"name": "str_replace_editor",
                            "command": "str_replace",
                            "path": "/repo/verify_issue_test.py"})),
        ("tool", "edited"),
    ])
    a = ufs.assess_trace(t)
    assert "F4" not in a["flags"]
    assert a["info_test_edits"] == 2


# ---- end types ----

def test_end_type_claimed_complete():
    a = _assess([
        ISSUE,
        ("ai", _cmd("edit 10:12")),
        ("user", "edited"),
        ("ai", "The task is complete — everything works."),
    ])
    assert a["flags"].get("F3") is True
    assert a["end_type"] == "claimed-complete"


# ---- section 7 report surface ----

def test_report_carries_flag_line_coverage_and_breakdown():
    t = _trace(_f1_trace([
        ("ai", _cmd("edit 20:21")),
        ("user", "edited"),
    ]), tid="t1")
    findings, info = ufs.assess_and_flag(t)
    assert findings and all(f.measurable is False for f in findings)
    rep = report.build([t], {"t1": findings}, "deepseek",
                       ufs=ufs.aggregate([info]))
    md = report.to_markdown(rep)
    assert "- Risk flags: **1 traces checked; F1 1, F2 0, F3 1 " \
           "(F3a 0), F4 0**" in md
    assert "- Coverage: 1 traces" in md
    assert "test runs (PASS 1, FAIL 0, UNKNOWN 0)" in md
    assert "- Informational: 0 edit(s) to agent-created test files" in md
    assert "- F1 by end type: submitted 1, claimed-complete 0, " \
           "exhausted 0" in md


def test_cli_report_includes_ufs_block():
    rows = []
    pairs = _f1_trace([
        ("ai", _cmd("edit 20:21")),
        ("user", "edited"),
    ])
    for i, (role, text) in enumerate(pairs):
        rows.append({"trace_id": "cli-t", "step": i, "role": role,
                     "text": text})
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        rc = cli.main([path, "--provider", "deepseek"])
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
        os.unlink(path)
    assert rc == 0
    assert "F1 1" in out and "### Unverified final state" in out
    assert "- Coverage:" in out
