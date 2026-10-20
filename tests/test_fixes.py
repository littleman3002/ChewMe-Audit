"""Fix-library behavior: dedup stubs (not drops) with a sha anchor.

Thread feedback (Oct 2026 launch): dropping a repeat hides the fact of
repetition (a byte-identical re-read after an edit means the edit
didn't land), and a bare "see first occurrence" pointer dangles once
compaction removes that occurrence. The snippets therefore replace
repeats past the threshold with a stub carrying the count and a short
hash of the repeated result.
"""
import hashlib

from chewme_audit.fixes import FIXES


def test_all_dedup_snippets_compile():
    for name, snippet in FIXES["error_loop_dedup"].items():
        if name in ("title", "safety"):
            continue
        compile(snippet, f"<{name}>", "exec")


def test_generic_snippet_stubs_fourth_repeat_with_sha_anchor():
    ns = {}
    exec(FIXES["error_loop_dedup"]["generic"], ns)
    dedup = ns["dedup_tool_result"]
    text = "SyntaxError: invalid syntax (line 42)"
    for _ in range(3):
        assert dedup(text, []) == text  # first 3 pass through untouched
    stub = dedup(text, [])
    expected_sha = hashlib.sha256(
        " ".join(text.split()).encode()).hexdigest()[:8]
    assert stub is not None  # stubbed, not dropped
    assert "repeated 4x" in stub
    assert f"sha {expected_sha}" in stub


def test_no_dedup_snippet_drops_silently():
    for name, snippet in FIXES["error_loop_dedup"].items():
        if name in ("title", "safety"):
            continue
        assert "first occurrence kept" in snippet, name
        assert "sha {h[:8]}" in snippet or "sha {h" in snippet, name
