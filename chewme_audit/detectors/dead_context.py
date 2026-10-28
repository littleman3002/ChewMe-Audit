"""Dead-context detector — read once, never referenced downstream.

A viewed file is DEAD when nothing after the view ever uses it:
no later tool-call argument names the file, no later edit touches
it, it is not in the final patch, and no symbol defined in it is
used in a later tool call. Assistant free prose is NOT evidence
(mentioning is not using), and neither is the content of later
view results (more context shown is not use of the earlier file).

The test is downstream *use*, not repetition and not size: it is
disjoint by construction from every shipped detector (error loops,
re-views, near-duplicates, cross-trace dups flag repetition; UFS
flags unverified endings; blind-edit flags blind writes) and from
boxdawn's ``redundant_read`` (2nd+ read of the same content —
repetition; this flags the 1st read that went nowhere).

Design note (ETH-paper new-direction note, section 2): the
discovery first test measured read-once-never-referenced files at
15.9-22.1% of viewed-file characters on 3 instances with a LOOSE
implementation (any later message text counted, prose and view
results included). This module implements the STRICT design the
note states: only later tool-call arguments, later edits, the
final patch, and symbol use count. The strict rule flags a
superset of the loose rule's dead set, so 16-22% is a LOWER BOUND
on this detector's share; the validation report states the
detector's own measured share separately.

v2 (dead-context-v2-report.md): E1 gains dotted module references
and the basename leg now requires a matching parent directory;
E4 gains module-level assignments, import bindings, and __all__
re-exports, and common-word symbols need a code-shaped context.
These fix v1 hand-check false flags 2 and 3; flags 1 (pattern
application) and 4 (quoted-line diagnosis in prose) remain named
known blind spots.

The detector reports a lower bound ("at least this much was
demonstrably unused"): absence of a surface reference does not
prove non-use (the model may use a doc without naming it), so
findings are lower-bound waste in the audit's existing framing.
Directory listings and error results are excluded before any
flag — a listing shows no file content, and an error result shows
no file content either; there is no dead *file content* to flag.

Scope: coding-agent traces with native tool calls (the OpenHands
flattened shape: each tool call is a step whose text is the call
as JSON, each tool result the following tool step). One finding
per dead file (first view); re-views of the same file are a
different detector's waste (the re-view itself references the
path, so a re-viewed file is live by E1).
"""

import ast
import bisect
import json
import re

from .. import counting
from .base import Finding
from .unverified_final_state import (
    _norm_path, _same_path, CMD_IN_ARGS, PATH_IN_ARGS, events_for,
)

DETECTOR = "dead_context"

# ---- result classification ----
LISTING_PREFIX = "Here's the files and directories"
FILE_VIEW_PREFIX = "Here's the result of running `cat -n`"
ERROR_PREFIXES = ("error:", "error ", "file not found", "not found:")

DEF_RE = re.compile(r"^\s*(?:\d+\t)?\s*(def|class)\s+"
                    r"([A-Za-z_][A-Za-z0-9_]*)\b")
LINE_RE = re.compile(r"^\s*(\d+)\t(.*)$", re.M)

# v2: module-level names a v1 def/class-only E4 could not see.
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*"
                        r"(?::\s*[^=\n]+)?=\s*[^=]")
_IMPORT_RE = re.compile(r"^import\s+([A-Za-z_][A-Za-z0-9_\.]*)"
                        r"(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?")
_FROM_RE = re.compile(r"^from\s+(\.+[A-Za-z_][A-Za-z0-9_\.]*|"
                      r"[A-Za-z_][A-Za-z0-9_\.]*)\s+import\s+(.+)$")
_ALL_RE = re.compile(r"""__all__\s*=\s*[\[(]([^\]\)]*)[\])]""")

# v2: import bindings from these sources are not evidence — the
# viewed file merely also imports them (stdlib + ubiquitous
# third-party). Relative imports always count (project-local by
# construction); unknown top-levels count (project-local until
# shown otherwise). Judgment list, stated here, not derived.
SKIP_IMPORT_SOURCES = frozenset("""
os sys re json math time datetime pathlib collections typing itertools
functools io shutil subprocess logging argparse unittest string random
hashlib base64 urllib http socket threading queue copy pickle csv
configparser dataclasses enum abc contextlib inspect textwrap warnings
traceback glob fnmatch tempfile statistics decimal fractions uuid
secrets hmac html xml email sqlite3 asyncio concurrent multiprocessing
signal gettext locale codecs struct array bisect heapq weakref gc
operator pprint dis ast token keyword builtins types numbers zoneinfo
tomllib importlib pkgutil platform getpass calendar ssl ftplib smtplib
poplib imaplib xmlrpc wsgiref __future__ typing_extensions attr attrs
pytest numpy pandas requests click flask
django pydantic sqlalchemy tornado aiohttp httpx yaml toml dotenv mock
six dateutil pytz PIL cv2 torch tensorflow sklearn scipy matplotlib
selenium bs4 lxml cryptography paramiko boto3 botocore google azure
celery redis pymongo psycopg2 mysql
""".split())

# v2: parent directory names too generic to discriminate a file
# (v1 bias gauge: same-basename-different-file). A basename leg
# whose parent is in this set is dropped; the token leg already
# covers the adjacent 'parent/basename' form.
GENERIC_DIRS = frozenset("""
src lib libs tests test testing utils util core app apps pkg pkgs
package packages module modules code scripts script bin docs doc data
config configs common shared internal api web cli tools helpers helper
base main include inc dist build out target vendor third_party extern
deps static assets public private local global system sys os home root
tmp var etc usr opt workspace repo repos project projects example
examples sample samples demo tutorial notebook notebooks experimental
legacy old new v1 v2 alpha beta
""".split())

# v2: generic identifiers that collide with ordinary English/shell
# words in tool-call args. A bare word-boundary match of one of
# these is prose, not use — it needs a code-shaped context (called,
# attribute, import clause, assignment target). Selection rule:
# lowercase single words that are both ordinary English and
# plausible generic identifiers. CamelCase/UPPER names are never
# common (project-specific by case).
COMMON_WORD_SYMBOLS = frozenset("""
add get set run main test data value values name names type types
format formatter open read write save load parse parser config utils
util helper helpers handler handlers manager process request requests
response responses result results error errors item items list dict
string strings path paths file files index count total size length key
keys id code message messages text content body title description
version status state mode level group user users client server service
services task tasks job jobs event events log logger debug info warning
date time day year first last next prev previous current default
standard base core simple basic common general public private local
global system empty all any some other same new old create update
delete remove find search check validate build make show print send
fetch store call do go head tail top bottom left right start end begin
finish input output source target parent child node tree root leaf page
row column cell field fields record records entry entries element
elements object objects number numbers integer float boolean char byte
bytes word words line lines filter map sorted len str int
""".split())


def _is_listing(result_text):
    return (result_text or "").strip().startswith(LISTING_PREFIX)


def _is_error(result_text):
    t = (result_text or "").strip().lower()
    return any(t.startswith(p) for p in ERROR_PREFIXES)


def _strip_cat_numbers(result_text):
    """`cat -n` output -> plain source, one line per line (line
    order/count preserved, so AST line numbers stay meaningful)."""
    out = []
    for line in (result_text or "").splitlines():
        m = LINE_RE.match(line)
        out.append(m.group(2) if m else line)
    return "\n".join(out)


def _ast_symbols(source):
    """Module-level names from an AST parse: def/class, assignments,
    import bindings, __all__ re-exports. Returns [{name, kind, line}]
    or None if the source does not parse (partial view range)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append({"name": node.name, "kind": "def",
                        "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            out.append({"name": node.name, "kind": "class",
                        "line": node.lineno})
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id != "__all__":
                    out.append({"name": tgt.id, "kind": "assign",
                                "line": node.lineno})
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and \
                                    isinstance(elt.value, str):
                                out.append({"name": elt.value,
                                            "kind": "re-export",
                                            "line": node.lineno})
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                out.append({"name": node.target.id, "kind": "assign",
                            "line": node.lineno})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in SKIP_IMPORT_SOURCES:
                    continue
                out.append({"name": alias.asname or top,
                            "kind": "import", "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                project_local = True
            else:
                top = (node.module or "").split(".")[0]
                project_local = top not in SKIP_IMPORT_SOURCES
            if not project_local:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                out.append({"name": alias.asname or alias.name,
                            "kind": "import", "line": node.lineno})
    return out


def _regex_symbols(source):
    """Fallback for fragments that do not parse: line regexes,
    module-level only (no leading whitespace) except def/class,
    which keep the v1 any-indent behavior."""
    out = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        if not line.strip():
            continue
        d = DEF_RE.match(line)
        if d:
            out.append({"name": d.group(2), "kind": d.group(1),
                        "line": lineno})
            continue
        if line[:1].isspace():
            continue
        m = _ASSIGN_RE.match(line)
        if m and m.group(1) != "__all__":
            out.append({"name": m.group(1), "kind": "assign",
                        "line": lineno})
            continue
        m = _IMPORT_RE.match(line)
        if m:
            top = m.group(1).split(".")[0]
            if top not in SKIP_IMPORT_SOURCES:
                out.append({"name": m.group(2) or top,
                            "kind": "import", "line": lineno})
            continue
        m = _FROM_RE.match(line)
        if m:
            src = m.group(1)
            if src.startswith("."):
                project_local = True
            else:
                project_local = src.split(".")[0] not in \
                    SKIP_IMPORT_SOURCES
            if project_local:
                for part in m.group(2).split(","):
                    part = part.strip().strip("()")
                    if not part or part == "*":
                        continue
                    bits = part.split()
                    nm = (bits[2] if len(bits) >= 3 and bits[1] == "as"
                          else bits[0])
                    out.append({"name": nm, "kind": "import",
                                "line": lineno})
    for m in _ALL_RE.finditer(source):
        for q in re.findall(r"""["']([A-Za-z_][A-Za-z0-9_]*)["']""",
                            m.group(1)):
            out.append({"name": q, "kind": "re-export", "line": None})
    return out


def _symbols_of(result_text):
    """Names defined in a `cat -n` view result: [{name, kind, line}].

    v1: def/class only. v2: + module-level assignments, import
    bindings, and __all__ re-exports (the v1 hand-check's false
    flags 2 and 3 — a runtime-imported module constant, an
    import-line quotation — were invisible to def/class-only E4).
    AST first (precise); regex fallback for fragments that do not
    parse. Deduplicated by name, first occurrence kept."""
    got = _ast_symbols(_strip_cat_numbers(result_text))
    if got is None:
        got = _regex_symbols(_strip_cat_numbers(result_text))
    seen = set()
    out = []
    for s in got:
        if s["name"] not in seen:
            seen.add(s["name"])
            out.append(s)
    return out


def _dotted_module_forms(norm):
    """Candidate dotted module forms of a viewed .py path.

    The trace path carries a corpus prefix
    (/workspace/<instance>/...) that is not part of the module name,
    so every suffix is a candidate: 'workspace/repo/reana_client/
    config.py' yields 'reana_client.config' (longer junk forms
    never match). '__init__.py' denotes the package itself."""
    if not norm.endswith(".py"):
        return []
    stem = norm[:-3]
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    parts = stem.split("/")
    return [".".join(parts[k:]) for k in range(len(parts))
            if ".".join(parts[k:])]


def _dotted_match(norm, down):
    """v2 E1 leg: a dotted module reference downstream, e.g.
    'from reana_client.config import X' naming
    'reana_client/config.py' (v1 false flag 2). Multi-component
    forms match at identifier boundaries (a preceding '.' is
    allowed — suffix semantics, as in _same_path); a
    single-component stem matches only in an import statement."""
    for form in _dotted_module_forms(norm):
        if "." in form:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(form) +
                         r"(?![A-Za-z0-9_])", down):
                return True
        elif re.search(r"\b(?:import|from)\s+" + re.escape(form) +
                       r"\b", down):
            return True
    return False


def _ident_boundary_re(name):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) +
                      r"(?![A-Za-z0-9_])")


def _parent_dir(norm):
    parts = norm.rsplit("/", 1)
    if len(parts) < 2:
        return ""
    return parts[0].rsplit("/", 1)[-1]


def _basename_with_parent(base, norm, down):
    """v2 basename leg: the basename matches at a path boundary AND
    the immediate parent directory name is also present downstream
    (v1: 18/21 basename-only live files were same-name-different-
    file). Parentless paths and generic parents ('src', 'tests',
    ...) get no basename leg — the token leg already covers the
    adjacent 'parent/basename' form. Residual: a parent-name
    collision across different grandparents still false-lives."""
    if len(base) < 4:
        return False
    parent = _parent_dir(norm)
    if not parent or len(parent) < 2 or \
            parent.lower() in GENERIC_DIRS:
        return False
    if not _basename_boundary_re(base).search(down):
        return False
    return bool(_ident_boundary_re(parent).search(down))


def _is_common_word(name):
    """Generic identifier colliding with ordinary English/shell
    words in args. CamelCase/UPPER names are never common."""
    return name == name.lower() and name in COMMON_WORD_SYMBOLS


def _code_context_match(name, text):
    """Code-shaped use of a generic symbol: called (name(), an
    attribute (.name), an import clause, or an assignment target
    (name =). A bare word-boundary match of a common word in args
    is prose, not use."""
    pats = (r"\b" + re.escape(name) + r"\s*\(",
            r"\." + re.escape(name) + r"\b",
            r"\b(?:import|from)\b[^\n;]*\b" + re.escape(name) + r"\b",
            r"\b" + re.escape(name) + r"\s*=")
    return any(re.search(p, text) for p in pats)


def _basename(path):
    return _norm_path(path).rsplit("/", 1)[-1] if path else ""


def _basename_boundary_re(basename):
    """Basename matched at a path boundary only: ``core.py`` must
    not match inside ``test_core.py`` (the loose first test's
    substring match did exactly that)."""
    return re.compile(r"(^|[/\"'\s=])" + re.escape(basename) +
                      r"($|[/\"'\s:;,\)\]])")


def _arg_tokens(text):
    """Path-like tokens in a tool-call argument string, with
    pytest node ids (``path::test``) and trailing punctuation
    stripped, for suffix matching against viewed paths."""
    toks = []
    for raw in re.split(r"[\s\"']+", text or ""):
        t = raw.strip("`,;:)]}")
        if "::" in t:
            t = t.split("::", 1)[0]
        if t:
            toks.append(t)
    return toks


def _call_args(step):
    """Argument text of one assistant tool-call step.

    Flattened steps carry the call as JSON ({"name": ..., **args});
    json.loads is the primary parse, the UFS regexes the fallback
    for adapter shapes that are not JSON."""
    text = step.text or ""
    try:
        args = json.loads(text)
        if isinstance(args, dict):
            return text
    except Exception:
        pass
    parts = []
    cm = CMD_IN_ARGS.search(text)
    if cm:
        parts.append(cm.group(1))
    pm = PATH_IN_ARGS.search(text)
    if pm:
        parts.append(pm.group(1))
    return " ".join(parts) if parts else text


def _is_tool_call_step(step):
    return (step.role in ("assistant", "ai") and
            getattr(step, "tool_name", "") not in ("", "message"))


def _view_results(trace):
    """Map view-call step index -> result text.

    Calls arrive in blocks (one assistant message, possibly
    several calls); the tool steps following a block are its
    results in call order. A view with no result before the next
    assistant step maps to None (recorded in coverage)."""
    results = {}
    steps = trace.steps
    i = 0
    while i < len(steps):
        if _is_tool_call_step(steps[i]):
            j = i
            block = []
            while j < len(steps) and _is_tool_call_step(steps[j]):
                block.append(j)
                j += 1
            res = []
            k = j
            while k < len(steps) and steps[k].role == "tool":
                res.append(steps[k])
                k += 1
            for pos, sidx in enumerate(block):
                results[sidx] = (res[pos].text if pos < len(res)
                                 else None)
                if pos < len(res):
                    results[(sidx, "result_step")] = res[pos].step_idx
            i = j
        else:
            i += 1
    return results


def _view_calls(trace):
    """(step_idx, path) for str_replace_editor view calls, in order."""
    out = []
    for s in trace.steps:
        if not _is_tool_call_step(s):
            continue
        if getattr(s, "tool_name", "") != "str_replace_editor":
            continue
        try:
            args = json.loads(s.text or "")
            cmd = args.get("command") if isinstance(args, dict) else None
            path = args.get("path") if isinstance(args, dict) else None
        except Exception:
            cmd = path = None
            cm = CMD_IN_ARGS.search(s.text or "")
            pm = PATH_IN_ARGS.search(s.text or "")
            if cm:
                cmd = cm.group(1)
            if pm:
                path = pm.group(1)
        if cmd == "view" and path:
            out.append((s.step_idx, path))
    return out


def _edit_targets(trace):
    """(step_idx, target) for EDIT events, via the UFS event pass
    (single source of truth for view/edit recognition)."""
    events, _created, _end = events_for(trace)
    return [(idx, d.get("target")) for idx, kind, d in events
            if kind == "EDIT" and isinstance(d, dict) and d.get("target")]


def assess_trace(trace, patch_files=None):
    """Dead-context assessment for one trace.

    patch_files: set of paths in the final patch (row-level data,
    e.g. OpenHands model_patch). When supplied, E3 is patch
    membership. When None, E3 falls back to "edited anywhere in
    the trace" — conservative (fewer flags), recorded per finding
    as patch_mode='trace-edits'. Returns (assessment dict)."""
    views = _view_calls(trace)
    results = _view_results(trace)
    edits = _edit_targets(trace)
    # Later tool-call argument text, indexed by step.
    arg_text = {}
    for s in trace.steps:
        if _is_tool_call_step(s):
            arg_text[s.step_idx] = _call_args(s)
    patch_set = set(patch_files or [])
    patch_bases = {_basename(p) for p in patch_set}
    patch_mode = "supplied" if patch_files is not None else "trace-edits"

    cov = {"views": len(views), "unique_files": 0, "dead_files": 0,
           "live_files": 0, "dir_listings": 0, "error_views": 0,
           "no_result": 0, "viewed_chars": 0, "dead_chars": 0,
           "arg_steps": len(arg_text), "edits": len(edits),
           "unclassified_results": 0}
    seen = set()
    files = []
    for step_idx, path in views:
        norm = _norm_path(path)
        if norm in seen:
            continue
        seen.add(norm)
        result = results.get(step_idx)
        if result is None:
            cov["no_result"] += 1
            result = ""
        if _is_listing(result):
            cov["dir_listings"] += 1
            continue
        if _is_error(result):
            cov["error_views"] += 1
            continue
        if result and not result.strip().startswith(FILE_VIEW_PREFIX):
            cov["unclassified_results"] += 1
        result_step = results.get((step_idx, "result_step"))
        files.append({"path": path, "norm": norm, "view_step": step_idx,
                      "result_step": result_step, "result": result,
                      "chars": len(result or "")})
    cov["unique_files"] = len(files)
    cov["viewed_chars"] = sum(f["chars"] for f in files)

    # Downstream argument text per view: joined args of later calls.
    # Built incrementally from the end so each view's downstream is
    # the suffix after it (views are in step order).
    arg_steps = sorted(arg_text)
    downstream = {}
    # suffix_text[i] = joined arg text of arg_steps[i:]; walk backwards.
    suffix_text = [""] * (len(arg_steps) + 1)
    for i in range(len(arg_steps) - 1, -1, -1):
        suffix_text[i] = arg_text[arg_steps[i]] + "\n" + suffix_text[i + 1]
    for f in files:
        pos = bisect.bisect_right(arg_steps, f["view_step"])
        downstream[f["view_step"]] = suffix_text[pos]

    dead = []
    live = []
    for f in files:
        path, norm = f["path"], f["norm"]
        base = _basename(path)
        down = downstream[f["view_step"]]
        evidence = {"E1_path_arg": False, "E2_edit_later": False,
                    "E3_patch": False, "E4_symbol_arg": False}
        # E1: path in a later tool-call argument — multi-component
        # path substring, path-token suffix match, dotted module
        # reference (v2), or basename at a path boundary with a
        # matching parent directory (v2; the v1 bare-basename leg
        # false-lived on same-name-different-file). The substring
        # leg needs a "/" in the path: a bare "core.py" would
        # substring-match "test_core.py" (the loose first test's
        # flaw); single-component paths rely on the token and
        # dotted legs instead.
        e1_kind = None
        if "/" in norm and norm in down:
            evidence["E1_path_arg"] = True
            e1_kind = "full_path"
        elif any(_same_path(tok, norm)
                 for tok in _arg_tokens(down)):
            evidence["E1_path_arg"] = True
            e1_kind = "token"
        elif _dotted_match(norm, down):
            evidence["E1_path_arg"] = True
            e1_kind = "dotted"
        elif _basename_with_parent(base, norm, down):
            evidence["E1_path_arg"] = True
            e1_kind = "basename"
        f["e1_kind"] = e1_kind
        # E2: edited later in the trace.
        if any(idx > f["view_step"] and _same_path(t, norm)
               for idx, t in edits):
            evidence["E2_edit_later"] = True
        # E3: in the final patch (supplied), else edited anywhere.
        if patch_files is not None:
            if norm in patch_set or base in patch_bases:
                evidence["E3_patch"] = True
            elif any(_same_path(p, norm) for p in patch_set):
                evidence["E3_patch"] = True
        else:
            if any(_same_path(t, norm) for _, t in edits):
                evidence["E3_patch"] = True
        # E4: a symbol defined in the viewed file used in a later
        # tool-call argument. v2: symbols are def/class (v1) plus
        # module-level assignments, import bindings, and __all__
        # re-exports; a common-word symbol needs a code-shaped
        # context (called, attribute, import clause, assignment
        # target), not a bare word match.
        syms = _symbols_of(f["result"])
        f["symbols"] = [s["name"] for s in syms]
        for s in syms:
            name = s["name"]
            if len(name) < 2:
                continue
            if _is_common_word(name):
                matched = _code_context_match(name, down)
            else:
                matched = bool(re.search(
                    r"\b" + re.escape(name) + r"\b", down))
            if matched:
                evidence["E4_symbol_arg"] = True
                f.setdefault("evidence_symbol", name)
                f["evidence_symbol_kind"] = s["kind"]
                break
        f["evidence"] = evidence
        f["patch_mode"] = patch_mode
        f["at_end"] = not any(idx > f["view_step"] for idx in arg_steps)
        if any(evidence.values()):
            live.append(f)
        else:
            dead.append(f)
    cov["dead_files"] = len(dead)
    cov["live_files"] = len(live)
    cov["dead_chars"] = sum(f["chars"] for f in dead)
    return {"files": files, "dead": dead, "live": live,
            "coverage": cov, "patch_mode": patch_mode}


def run(trace, provider="deepseek"):
    """MEASURABLE entry point (same shape as the other waste
    detectors): findings only, no patch data, so E3 falls back to
    'edited anywhere in the trace' (conservative, recorded per
    finding as patch_mode='trace-edits')."""
    findings, _info = assess_and_flag(trace, provider=provider)
    return findings


def assess_and_flag(trace, patch_files=None, provider="deepseek"):
    """Mirror unverified_final_state.assess_and_flag's shape:
    (findings, info). One measurable finding per dead file; waste
    is the first view's result tokens (counted under provider,
    basis labeled — shares are basis-independent)."""
    a = assess_trace(trace, patch_files=patch_files)
    findings = []
    for f in a["dead"]:
        n_tokens, basis = counting.count(f["result"] or "", provider)
        findings.append(Finding(
            detector=DETECTOR,
            trace_id=trace.trace_id,
            step_idx=f["view_step"],
            waste_tokens=n_tokens,
            token_basis=basis,
            summary=(f"dead context: {f['path']} viewed once, never "
                     f"referenced downstream — {f['chars']:,} chars "
                     f"({n_tokens:,} tokens, {basis}) shown and unused"),
            detail={"path": f["path"], "view_step": f["view_step"],
                    "result_step": f.get("result_step"),
                    "view_chars": f["chars"], "symbols": f["symbols"],
                    "evidence": f["evidence"],
                    "e1_kind": f.get("e1_kind"),
                    "patch_mode": f["patch_mode"],
                    "at_end": f["at_end"],
                    "coverage": a["coverage"]},
            fix_key="dead_context",
            covers=frozenset(x for x in (f["view_step"],
                                         f.get("result_step"))
                             if x is not None),
        ))
    info = {"assessed": True, "trace_id": trace.trace_id,
            "dead_files": [f["path"] for f in a["dead"]],
            "live_files": [f["path"] for f in a["live"]],
            "coverage": a["coverage"], "patch_mode": a["patch_mode"]}
    return findings, info


def aggregate(infos):
    """Fold per-trace info dicts into the report-level block:
    flag counts plus the mandatory coverage block (Tracy's
    parse-coverage rule: no count without coverage beside it)."""
    cov = {"traces": len(infos), "views": 0, "unique_files": 0,
           "dead_files": 0, "live_files": 0, "dir_listings": 0,
           "error_views": 0, "no_result": 0, "viewed_chars": 0,
           "dead_chars": 0, "arg_steps": 0, "edits": 0,
           "unclassified_results": 0}
    for info in infos:
        c = info["coverage"]
        for k in cov:
            if k in c:
                cov[k] += c[k]
    dead_share = (cov["dead_chars"] / cov["viewed_chars"]
                  if cov["viewed_chars"] else 0.0)
    return {"traces_checked": len(infos), "coverage": cov,
            "dead_char_share": dead_share}
