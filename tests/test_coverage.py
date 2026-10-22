"""Unit tests for the read-coverage engine."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chewme_audit import coverage as C
from chewme_audit.model import Step, Trace


def _trace(pairs):
    """pairs: list of (role, text) -> Trace with sequential steps."""
    t = Trace(trace_id="t")
    t.steps = [Step("t", i, text, role=role) for i, (role, text)
               in enumerate(pairs)]
    return t


def _call(tool, args):
    import json
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


def _res(text):
    return "[run_bash]\n[exit 0]\n" + text


def test_heredoc_body_is_not_parsed_as_commands():
    cmd = ("cat > /tmp/insert_docs.py <<'PYEOF'\n"
           "import ast, os\n"
           "src = open(p).read(); print(src)\n"
           "cat = 3; head = 4\n"
           "PYEOF")
    evs = C.parse_bash(cmd)
    kinds = [e["kind"] for e in evs]
    assert kinds == ["full_replace"], kinds
    assert evs[0]["path"] == "/tmp/insert_docs.py"


def test_head_spans_multi_file():
    evs = C.parse_bash("head -5 a.py b.py && tail -3 c.py")
    spans = {(e["path"], e["kind"]) for e in evs}
    assert ("a.py", "read_span") in spans
    assert ("b.py", "read_span") in spans
    assert ("c.py", "read_tail") in spans
    assert all(e.get("n") == 5 for e in evs if e["kind"] == "read_span")


def test_grep_is_sampled_not_coverage():
    evs = C.parse_bash('grep -n "max-age" django/utils/cache.py')
    assert evs and all(e["kind"] == "sampled" for e in evs)


def test_sed_i_is_pattern_edit():
    evs = C.parse_bash("sed -i 's/foo/bar/g' big.py")
    assert evs == [{"kind": "pattern_edit", "path": "big.py"}]


def test_hunk_lower_bound_takes_max():
    diff = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n+++ b/f.py\n"
        "@@ -10,5 +10,5 @@\n ctx\n-old\n+new\n"
        "@@ -90,30 +90,30 @@\n ctx\n-old2\n+new2\n")
    g = C.parse_git_output(diff)
    assert g["f.py"]["old_lb"] == 119  # 90 + 30 - 1


def test_changed_vs_pure_deletion_split():
    diff = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n+++ b/f.py\n"
        "@@ -1,4 +1,2 @@\n"
        "-gone1\n-gone2\n-renamed\n+renamed2\n ctx\n")
    g = C.parse_git_output(diff)
    assert len(g["f.py"]["changed"]) == 1      # renamed -> renamed2
    assert len(g["f.py"]["pure_del"]) == 2     # gone1, gone2


def test_new_content_length_is_not_size_evidence():
    # Tracy's counterexample: read 5 lines of a small file, write 200
    # new lines. The write's length says nothing about the old file,
    # so evidenced must stay 5 and nothing may flag.
    body = "\n".join(f"line {i}" for i in range(200))
    t = _trace([
        ("assistant", _call("run_bash", {"cmd": "head -5 small.py"})),
        ("tool", _res("l1\nl2\nl3\nl4\nl5")),
        ("assistant", _call("write_file",
                            {"path": "small.py", "content": body})),
        ("tool", "[write_file] wrote small.py"),
    ])
    A = C.assess(t)
    entry = [e for e in A.entries if e["file"] == "small.py"][0]
    assert entry["lines_evidenced"] == 5, entry
    assert entry["coverage"] == 1.0


def test_diff_summary_parsing():
    txt = " 223 files changed, 223 insertions(+), 117 deletions(-)"
    assert C.parse_diff_summaries(txt) == [(223, 223, 117)]
    txt2 = " 210 files changed, 210 insertions(+)"
    assert C.parse_diff_summaries(txt2) == [(210, 210, 0)]
