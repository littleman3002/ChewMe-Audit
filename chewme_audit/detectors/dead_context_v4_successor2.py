"""Dead-context v4 SUCCESSOR2 — module-path-constrained import-leg
matcher with an enlarged name set.

Implements dead-context-v4-successor2-design-DRAFT.md (2026-10-29).
Thesis: the successor matched modules exactly but built its name
set from too little of the file; successor2 keeps module-path
equality, arms, derivation, and authorship UNTOUCHED and enlarges
the name set's construction two ways: (1) S_trace — names proven
present by other trace evidence (H1 cross-view union, H2
grep-output definition lines, H3 sibling imports resolving to V
exactly), tagged `trace-harvested`; (2) transitive If/Try/With
recursion for all binding types at module top level, tagged
`cond-import`. Ruling 2's `__all__`-alone bar stays intact
(`__all__` is a claim, not a binding). The G2 list stays CLOSED:
definitions appearing nowhere in the trace stay misses, never
redefined silences. Successor2 determines import evidence ONLY,
not dead/live.

DESIGN-AFTER-VALIDATION DISCLOSURE: this module is informed by
successor validation data (3 misses on partial views, 3 guard
errors on conditional top-level imports; report verdict NEW RULE
DOES NOT HOLD, 2026-10-29 17:38 EDT). Any future validation
needs a FRESH slice disjoint from the successor's 600 IDs (seed
20261211), v4's 600 IDs, v3r7's 600 IDs, and every prior set.

DETECTOR = "dead_context_v4_successor2". NOT registered in
MEASURABLE (implementation + gate only; no freeze, no validation).
Stdlib only; does NOT import dead_context_v4_successor or
dead_context_v4 (the successor's matching code is copied here
and then modified, so the frozen successor file is never
edited).

ARM 2 (CARRIED OVER, RATIFIED): the successor draft's §4 Arm 2
said R may be ANY proper ancestor of V; applied literally that
fires on adjudicated idx242 (viewed pandas/io/excel/__init__.py
re-exporting read_excel, downstream pd.read_excel resolving to
pandas), ruled FALSE, while the real LIVE-039 depth-2 shape is
ruled TRUE — no ancestor-depth rule reproduces both. The
successor therefore narrowed Arm 2 to R == IMMEDIATE PARENT of
V, and the successor freeze RATIFIED the narrowing (Ruling 1).
Successor2 carries the ratified rule unchanged: the draft's
stated LIVE-039 shape (V = pennylane.embeddings, R =
pennylane) fires, idx242 stays silent, and the real-LIVE-039
depth-2 shape stays a pinned, disclosed silence.

Public API (mirrors the successor's check-runner shape):
  derive_module_paths(norm) -> frozenset | None
  analyze_viewed(result_text) -> dict (defined, reexport, prov,
      fallback, parse_reason, partial_view)
  extract_code_units(trace, view_step, viewed_norm) -> units
  match_file(viewed, units, trace_sets) -> matches (each with
      "provenance": None | "cond-import" | "trace-harvested")
  assess_trace(trace) -> {"files", "live", "coverage"}
  import_evidence_items(assessment) -> population items
One S-builder serves the module and any future guard oracle:
  _names_from_ast(tree) / _names_from_fallback(src) are the
  single construction for S_window (design §2c); the guard
  oracle must import them, not reimplement the iteration.
"""

import ast
import io
import json
import re
import tokenize

DETECTOR = "dead_context_v4_successor2"

LISTING_PREFIX = "Here's the files and directories"
FILE_VIEW_PREFIX = "Here's the result of running `cat -n`"
ERROR_PREFIXES = ("error:", "error ", "file not found", "not found:")
LINE_RE = re.compile(r"^\s*(\d+)\t(.*)$", re.M)

# ---------------------------------------------------------------- §2
# Canonical module-path derivation — the shared function.


def derive_module_paths(norm):
    """Candidate module paths for a viewed-file norm, or None if
    the path cannot be rooted (G2 silence, never a guess).

    norm is the view path as recorded in the trace, e.g.
    "/workspace/<instance>/pkg/sub.py" (the spent-trace shape) or
    a repo-relative path. Rules (draft §2):
      - strip quotes/backslashes, collapse slashes, strip leading /
      - a leading "workspace/<instance>/" prefix is dropped
      - the file must end with ".py" (else None)
      - trailing "__init__" is stripped (package identity)
      - a leading "src/" yields TWO candidates (with/without it)
      - NO test-root stripping, NO case folding, NO hyphen/
        underscore conflation.
    """
    if not norm:
        return None
    p = str(norm).strip().strip("'\"").replace("\\", "/")
    p = re.sub(r"/+", "/", p).strip("/")
    parts = [c for c in p.split("/") if c]
    if len(parts) >= 2 and parts[0] == "workspace":
        parts = parts[2:]
    if not parts:
        return None
    last = parts[-1]
    if not last.endswith(".py"):
        return None
    parts = parts[:-1] + [last[:-3]]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    base = ".".join(parts)
    cands = {base}
    if parts[0] == "src" and len(parts) > 1:
        cands.add(".".join(parts[1:]))
    return frozenset(cands)


def _norm_path(path):
    """Path cleanup (mirrors the UFS _norm_path used by v4)."""
    if not path:
        return ""
    p = str(path).strip().strip("'\"").replace("\\", "/")
    p = re.sub(r"/+", "/", p)
    if p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def _same_norm(a, b):
    """Path identity across trace forms: equal, or one a
    path-boundary suffix of the other (v4's _same_path rule)."""
    na, nb = _norm_path(a), _norm_path(b)
    if not na or not nb:
        return False
    return na == nb or na.endswith("/" + nb) or nb.endswith("/" + na)


# ---------------------------------------------------------------- §5
# Viewed-file name set — AST positions, not regex blobs.


def _strip_view_source(result_text):
    """View result -> plain source: drop `cat -n` header lines,
    strip line numbers. Line numbers do not matter for the name
    set, so dropping (not blanking) the header is safe here."""
    out = []
    for ln in (result_text or "").splitlines():
        if ln.startswith("Here's the result"):
            continue
        m = LINE_RE.match(ln)
        out.append(m.group(2) if m else ln)
    return "\n".join(out)


# Provenance tiers for name-set membership. "plain" (a direct
# tree.body binding) beats "cond" (found only via If/Try/With
# recursion); "trace" (S_trace harvest, applied by the caller)
# is weaker still. A name's tier is the best tier at which it
# was found.
_TIER = {"plain": 0, "cond": 1, "trace": 2}


def _mark(name, tier, s, prov):
    s.add(name)
    if name not in prov or _TIER[tier] < _TIER[prov[name]]:
        prov[name] = tier


_TRY_TYPES = (ast.Try,) + ((ast.TryStar,)
                           if hasattr(ast, "TryStar") else ())


def _walk_top_bindings(nodes, cond, defined, reexport, all_entries,
                       prov):
    """Collect module-level bindings from a statement list.

    Successor2 §2b: recurse transitively into If/Try/With bodies
    (elif/else branches, except/finally bodies, nested chains),
    collecting ALL binding node types. Function/class bodies are
    NOT recursed (their bindings are local, not module API), and
    no other statement type recurses. Bindings found only via
    recursion carry "cond" provenance; direct tree.body bindings
    carry "plain".
    """
    tier = "cond" if cond else "plain"
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _mark(node.name, tier, defined, prov)
        elif isinstance(node, ast.ClassDef):
            _mark(node.name, tier, defined, prov)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    if tgt.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and \
                                        isinstance(elt.value, str):
                                    all_entries.append(elt.value)
                    else:
                        _mark(tgt.id, tier, defined, prov)
                elif isinstance(tgt, (ast.Tuple, ast.List)):
                    for elt in tgt.elts:
                        if isinstance(elt, ast.Name):
                            _mark(elt.id, tier, defined, prov)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                _mark(node.target.id, tier, defined, prov)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                nm = alias.asname or alias.name.split(".")[0]
                _mark(nm, tier, defined, prov)
                _mark(nm, tier, reexport, prov)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                nm = alias.asname or alias.name
                _mark(nm, tier, defined, prov)
                _mark(nm, tier, reexport, prov)
        elif isinstance(node, ast.If):
            _walk_top_bindings(node.body, True, defined, reexport,
                               all_entries, prov)
            _walk_top_bindings(node.orelse, True, defined, reexport,
                               all_entries, prov)
        elif isinstance(node, _TRY_TYPES):
            _walk_top_bindings(node.body, True, defined, reexport,
                               all_entries, prov)
            for h in node.handlers:
                _walk_top_bindings(h.body, True, defined, reexport,
                                   all_entries, prov)
            _walk_top_bindings(node.orelse, True, defined, reexport,
                               all_entries, prov)
            _walk_top_bindings(node.finalbody, True, defined,
                               reexport, all_entries, prov)
        elif isinstance(node, ast.With):
            _walk_top_bindings(node.body, True, defined, reexport,
                               all_entries, prov)
        # Anything else (loops, comprehensions, function/class
        # bodies) is skipped: only If/Try/With recurse.


def _names_from_ast(tree):
    """(defined, reexport, prov) from a parsed viewed file.

    prov maps each name to "plain" or "cond" (see
    _walk_top_bindings). __all__ entries count only when they
    name a genuinely present symbol (Ruling 2: __all__ alone
    never confers membership).
    """
    defined, reexport, prov = set(), set(), {}
    all_entries = []
    _walk_top_bindings(tree.body, False, defined, reexport,
                       all_entries, prov)
    for nm in all_entries:
        if nm in defined:
            reexport.add(nm)
    return defined, reexport, prov


_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)")
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)")
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*"
                        r"(?::\s*[^=\n]+)?=\s*[^=]")
_IMPORT_RE = re.compile(r"^import\s+([A-Za-z_][A-Za-z0-9_\.]*)"
                        r"(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?")
_FROM_RE = re.compile(r"^from\s+(\.+[A-Za-z_][A-Za-z0-9_\.]*|"
                      r"[A-Za-z_][A-Za-z0-9_\.]*)\s+import\s+(.+)$")
_ALL_RE = re.compile(r"""__all__\s*=\s*[\[(]([^\]\)]*)[\])]""")


def _mask_tokenize(src):
    """Blank STRING and COMMENT token spans; returns masked source
    or None if tokenize fails (caller records degradation)."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    lines = src.splitlines(keepends=True)
    # Work on a mutable char grid: list of char lists per line.
    grid = [list(ln) for ln in lines]

    def blank(sline, scol, eline, ecol):
        for ln in range(sline, eline + 1):
            if ln - 1 >= len(grid):
                continue
            row = grid[ln - 1]
            start = scol if ln == sline else 0
            end = ecol if ln == eline else len(row)
            for ci in range(start, min(end, len(row))):
                if row[ci] != "\n":
                    row[ci] = " "

    for tok in toks:
        if tok.type in (tokenize.STRING, tokenize.COMMENT):
            (sline, scol), (eline, ecol) = tok.start, tok.end
            blank(sline, scol, eline, ecol)
    return "".join("".join(row) for row in grid)


def _strip_strings_comments_scan(text):
    """Regex-degradation fallback: scanner removing string literals
    and '#' comments (v4's _strip_strings_comments shape)."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in ("'", '"'):
            triple = text[i:i + 3] in ("'''", '"""')
            quote = text[i:i + 3] if triple else c
            j = i + len(quote)
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j:j + len(quote)] == quote:
                    j += len(quote)
                    break
                j += 1
            out.append(" ")
            i = j
            continue
        if c == "#":
            j = text.find("\n", i)
            out.append(" ")
            i = n if j == -1 else j
            continue
        out.append(c)
        i += 1
    return "".join(out)


# Fallback block-header shapes, for the indent-stack that decides
# whether an indented import/from line sits inside a conditional
# chain (If/Try/With) rather than a function/class body.
_BLOCK_HDR_RE = re.compile(
    r"^(\s*)(if\b|elif\b|else:|try:|except\b|finally:|with\b|"
    r"async\s+def\b|def\b|class\b|for\b|while\b)")


def _indent_of(line):
    exp = line.expandtabs(8)
    return len(exp) - len(exp.lstrip())


def _names_from_fallback(src):
    """(defined, reexport, prov, degraded) from tokenize-masked
    regex extraction.

    Successor2 §2b fallback parity: the successor's fallback
    skipped ALL indented import/from lines, so an if-block import
    on the fallback path never entered S (the same hole as the
    AST path's tree.body bug, on the degraded path). This version
    tracks an indent stack over block headers: an indented
    import/from line enters S with "cond" provenance iff its
    innermost enclosing block is If/Try/With (elif/else/except/
    finally inherit the block they continue); indented imports
    inside function/class/other bodies stay excluded, exactly as
    the AST path excludes function/class bodies. Def/class keep
    the v1 any-indent behavior (provenance "cond" only when
    inside a conditional block, else "plain"). Assigns stay
    column-0-only (unchanged): an indented assign inside a
    multi-line call would be a kwarg, not a binding, and the
    degraded path cannot tell them apart.
    """
    masked = _mask_tokenize(src)
    degraded = False
    if masked is None:
        masked = _strip_strings_comments_scan(src)
        degraded = True
    defined, reexport, prov = set(), set(), {}
    all_entries = []
    stack = []  # (indent, kind): kind in {"cond", "defclass", "other"}
    for line in masked.splitlines():
        if not line.strip():
            continue
        ind = _indent_of(line)
        popped = []
        while stack and stack[-1][0] >= ind:
            popped.append(stack.pop())
        # Enclosing block BEFORE pushing this line's own header:
        # a def inside an if block must read "cond", not its own
        # "defclass" entry.
        enclosing = stack[-1][1] if stack else None
        hm = _BLOCK_HDR_RE.match(line)
        if hm:
            kw = hm.group(2)
            if kw in ("elif", "else:", "except", "finally:"):
                kind = "cond"
                for pind, pkind in reversed(popped):
                    if pind == ind:
                        kind = pkind
                        break
            elif kw in ("if", "try:", "with"):
                kind = "cond"
            elif kw in ("def", "async def", "class"):
                kind = "defclass"
            else:
                kind = "other"
            stack.append((ind, kind))
        d = _DEF_RE.match(line)
        if d:
            _mark(d.group(1), "cond" if enclosing == "cond"
                  else "plain", defined, prov)
            continue
        c = _CLASS_RE.match(line)
        if c:
            _mark(c.group(1), "cond" if enclosing == "cond"
                  else "plain", defined, prov)
            continue
        stripped = line.strip()
        if line[:1].isspace():
            # Indented import/from: only inside a conditional
            # block (see docstring). Indented assigns stay out.
            if enclosing != "cond":
                continue
            m = _IMPORT_RE.match(stripped)
            if m:
                nm = m.group(2) or m.group(1).split(".")[0]
                _mark(nm, "cond", defined, prov)
                _mark(nm, "cond", reexport, prov)
                continue
            m = _FROM_RE.match(stripped)
            if m:
                for part in m.group(2).split(","):
                    part = part.strip().strip("()")
                    if not part or part == "*":
                        continue
                    bits = part.split()
                    nm = (bits[2] if len(bits) >= 3 and bits[1] == "as"
                          else bits[0])
                    _mark(nm, "cond", defined, prov)
                    _mark(nm, "cond", reexport, prov)
            continue
        m = _ASSIGN_RE.match(line)
        if m and m.group(1) != "__all__":
            _mark(m.group(1), "plain", defined, prov)
            continue
        m = _IMPORT_RE.match(line)
        if m:
            nm = m.group(2) or m.group(1).split(".")[0]
            _mark(nm, "plain", defined, prov)
            _mark(nm, "plain", reexport, prov)
            continue
        m = _FROM_RE.match(line)
        if m:
            for part in m.group(2).split(","):
                part = part.strip().strip("()")
                if not part or part == "*":
                    continue
                bits = part.split()
                nm = (bits[2] if len(bits) >= 3 and bits[1] == "as"
                      else bits[0])
                _mark(nm, "plain", defined, prov)
                _mark(nm, "plain", reexport, prov)
    for m in _ALL_RE.finditer(masked):
        for q in re.findall(r"""["']([A-Za-z_][A-Za-z0-9_]*)["']""",
                            m.group(1)):
            all_entries.append(q)
    for nm in all_entries:
        if nm in defined:
            reexport.add(nm)
    return defined, reexport, prov, degraded


def analyze_viewed(result_text, view_range=None):
    """Name-set analysis for one viewed file result.

    Returns dict: defined (set), reexport (set), prov (dict
    name -> "plain" | "cond"), fallback (bool), parse_reason
    (str), partial_view (bool)."""
    src = _strip_view_source(result_text)
    partial = view_range is not None
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        defined, reexport, prov, degraded = _names_from_fallback(src)
        reason = "tokenize-degraded" if degraded else "syntax-error"
        return {"defined": defined, "reexport": reexport,
                "prov": prov, "fallback": True,
                "parse_reason": reason, "partial_view": partial}
    defined, reexport, prov = _names_from_ast(tree)
    return {"defined": defined, "reexport": reexport,
            "prov": prov, "fallback": False, "parse_reason": "ast",
            "partial_view": partial}


# ---------------------------------------------------------------- §2a
# S_trace — names proven present by other trace evidence.


def _view_key(norm):
    """Same-file key for H1/H2 anchoring: _norm_path plus the
    successor's workspace/<instance>/ prefix strip. EXACT match
    only — no suffix fuzz, so a same-named file in another
    directory can never contaminate V's S (cross-file pin)."""
    p = _norm_path(norm)
    parts = [c for c in p.split("/") if c]
    if len(parts) >= 2 and parts[0] == "workspace":
        parts = parts[2:]
    return "/".join(parts)


# H2: grep-output definition lines. `path:lineno:` (with an
# optional second `:column:`) followed by a definition shape at
# content start. The path attribution must match V's key exactly;
# malformed attribution fails closed to silence.
_GREP_DEF_RE = re.compile(
    r"^(.+?):\d+(?::\d+)?:\s*"
    r"(?:(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"|class\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"|([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^=\n]+)?=\s*[^=])")


def _harvest_grep_names(trace, view_key):
    """H2: definition names quoted in tool results with V's exact
    path. Tool output NEVER proves authorship (conjunct (i)
    still requires an agent-authored unit) — it proves file
    membership (conjunct (iii) is about the file, not the agent).
    Returns a set of names."""
    out = set()
    for s in trace.steps:
        if s.role != "tool":
            continue
        for line in (s.text or "").splitlines():
            m = _GREP_DEF_RE.match(line)
            if not m:
                continue
            if _view_key(m.group(1)) != view_key:
                continue
            nm = m.group(2) or m.group(3) or m.group(4)
            if nm:
                out.add(nm)
    return out


def _harvest_sibling_imports(trace, viewed_cands, viewed_norm):
    """H3: {name -> set(proving step_idx)} from agent-authored
    units (other than the candidate unit — enforced at match
    time) containing a from-import that resolves to V exactly and
    names N. Plain `import V` proves no name and is ignored;
    star imports prove no name and are ignored. Units are the
    successor's own extraction (edits to V itself excluded, so a
    self-import can never be a proof).

    Returns (proofs, defeated): proofs maps name -> proving
    steps; defeated maps name -> defeat reason for H3(c)
    failure-defeat (an ImportError/AttributeError proving the
    import wrong defeats the harvest).
    """
    proofs = {}
    units = extract_code_units(trace, -1, viewed_norm)
    for step_idx, kind, code, containing in units:
        cc = None
        if containing:
            cc = derive_module_paths(_norm_path(containing))
        names = set()
        tree = None
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            un = _unescape_code(code)
            if un != code:
                try:
                    tree = ast.parse(un)
                except (SyntaxError, ValueError):
                    tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.level and node.level > 0:
                    mods = _resolve_relative(node.level, node.module,
                                             cc)
                    if not mods:
                        continue
                else:
                    mods = {node.module} if node.module else set()
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if mods & set(viewed_cands):
                        names.add(alias.name)
        else:
            masked = _mask_tokenize(code)
            if masked is None:
                masked = _strip_strings_comments_scan(code)
            for line in masked.splitlines():
                m = _FROM_RE.match(line.strip())
                if not m:
                    continue
                raw_mod, rhs = m.group(1), m.group(2)
                if raw_mod.startswith("."):
                    level = len(raw_mod) - len(raw_mod.lstrip("."))
                    mods = _resolve_relative(
                        level, raw_mod.lstrip(".") or None, cc)
                    if not mods:
                        continue
                else:
                    mods = {raw_mod}
                if not (mods & set(viewed_cands)):
                    continue
                rhs = rhs.split(";")[0].strip().strip("()").strip()
                for part in rhs.split(","):
                    part = part.strip()
                    if not part or part == "*":
                        continue
                    bits = part.split()
                    nm = (bits[2] if len(bits) >= 3 and bits[1] == "as"
                          else bits[0])
                    names.add(nm)
        for nm in names:
            proofs.setdefault(nm, set()).add(step_idx)
    # H3(c) failure defeat, conservative: an ImportError /
    # ModuleNotFoundError line mentioning V's module path defeats
    # ALL H3 proofs for V; one mentioning a harvested name
    # defeats that name; an AttributeError line mentioning both
    # V's path and a name defeats that name.
    defeated = {}
    for s in trace.steps:
        if s.role != "tool":
            continue
        for line in (s.text or "").splitlines():
            if "ImportError" in line or "ModuleNotFoundError" in line:
                if any(c in line for c in viewed_cands):
                    for nm in list(proofs):
                        defeated[nm] = "import-error-module"
                else:
                    for nm in list(proofs):
                        if re.search(r"\b" + re.escape(nm) + r"\b",
                                     line):
                            defeated[nm] = "import-error-name"
            elif "AttributeError" in line:
                if any(c in line for c in viewed_cands):
                    for nm in list(proofs):
                        if re.search(r"\b" + re.escape(nm) + r"\b",
                                     line):
                            defeated[nm] = "attribute-error"
    for nm in defeated:
        proofs.pop(nm, None)
    return proofs, defeated


# ---------------------------------------------------------------- §3
# Downstream code units — agent-authored code ONLY.

_PY_C_RE = re.compile(r"python[0-9.]*\s+-c\s*")
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def _parse_quoted(s, i):
    """Parse a quoted string starting at s[i] (quote char). Returns
    (value, end_index) with backslash escapes resolved to the
    escaped char, or (rest_of_line, len) if unclosed."""
    q = s[i]
    out = []
    j = i + 1
    while j < len(s):
        c = s[j]
        if c == "\\" and j + 1 < len(s):
            out.append(s[j + 1])
            j += 2
            continue
        if c == q:
            return "".join(out), j + 1
        if c == "\n":
            break
        out.append(c)
        j += 1
    return "".join(out), j


def _extract_python_c(cmd):
    """Code strings from `python -c "..."` / `'...'` invocations."""
    codes = []
    for m in _PY_C_RE.finditer(cmd or ""):
        i = m.end()
        while i < len(cmd) and cmd[i] in " \t":
            i += 1
        if i < len(cmd) and cmd[i] in ("'", '"'):
            val, _ = _parse_quoted(cmd, i)
            if val.strip():
                codes.append(val)
        elif i < len(cmd):
            # Unquoted -c argument: to end of line / command chain.
            tail = cmd[i:]
            tail = re.split(r"\s*(?:;|&&|\|\|)\s*", tail, maxsplit=1)[0]
            if tail.strip():
                codes.append(tail.strip())
    return codes


def _extract_heredocs(cmd):
    """Heredoc bodies: lines between <<DELIM and a line that is
    exactly DELIM (leading tab allowed for <<-)."""
    bodies = []
    lines = (cmd or "").splitlines()
    i = 0
    while i < len(lines):
        m = _HEREDOC_RE.search(lines[i])
        if not m:
            i += 1
            continue
        delim = m.group(1)
        buf = []
        j = i + 1
        while j < len(lines) and lines[j].strip() != delim:
            buf.append(lines[j])
            j += 1
        if buf:
            bodies.append("\n".join(buf))
        i = j + 1
    return bodies


def _unescape_code(code):
    """Literal backslash-n/tab sequences (python -c snippets with
    escaped newlines, the v3r5 finding) -> real newlines/tabs.
    Only applied as a second parse attempt / fallback input."""
    if "\\n" not in code and "\\t" not in code:
        return code
    return code.replace("\\n", "\n").replace("\\t", "\t")


def _view_calls(trace):
    """(step_idx, path, view_range) for str_replace_editor views."""
    out = []
    for s in trace.steps:
        if s.role not in ("assistant", "ai"):
            continue
        if getattr(s, "tool_name", "") != "str_replace_editor":
            continue
        try:
            args = json.loads(s.text or "")
            cmd = args.get("command") if isinstance(args, dict) else None
            path = args.get("path") if isinstance(args, dict) else None
            vr = args.get("view_range") if isinstance(args, dict) else None
        except Exception:
            cmd = path = vr = None
        if cmd == "view" and path:
            out.append((s.step_idx, path, vr))
    return out


def _call_results(trace):
    """Map tool-call step index -> result text (v4's block-order
    mapping: calls arrive in blocks; following tool steps are
    results in call order)."""
    results = {}
    steps = trace.steps
    i = 0
    while i < len(steps):
        if steps[i].role in ("assistant", "ai") and \
                getattr(steps[i], "tool_name", "") not in ("", "message"):
            j = i
            block = []
            while j < len(steps) and steps[j].role in ("assistant", "ai") \
                    and getattr(steps[j], "tool_name", "") not in \
                    ("", "message"):
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
            i = j
        else:
            i += 1
    return results


def _is_listing(result_text):
    return (result_text or "").strip().startswith(LISTING_PREFIX)


def _is_error(result_text):
    t = (result_text or "").strip().lower()
    return any(t.startswith(p) for p in ERROR_PREFIXES)


def extract_code_units(trace, view_step, viewed_norm):
    """Agent-authored code units after the view, in step order:
    [(step_idx, kind, code, containing_norm_or_None)].

    Kinds: "edit" (create file_text / str_replace+insert new_str;
    never old_str), "python_c", "heredoc". Excluded: messages,
    think text, tool results, view commands, re-views, edits TO
    the viewed file itself (self-match exclusion), non-Python
    edit targets (an edit to a non-.py file is not Python code).
    """
    units = []
    for s in trace.steps:
        if s.step_idx <= view_step:
            continue
        if s.role not in ("assistant", "ai"):
            continue
        tool = getattr(s, "tool_name", "")
        if tool in ("", "message", "think"):
            continue
        try:
            args = json.loads(s.text or "")
        except Exception:
            args = None
        if not isinstance(args, dict):
            continue
        if tool == "str_replace_editor":
            cmd = args.get("command")
            path = args.get("path")
            if cmd == "view":
                continue
            if cmd == "create":
                code = args.get("file_text") or ""
            elif cmd in ("str_replace", "insert"):
                code = args.get("new_str") or ""
            else:
                continue
            if not code.strip():
                continue
            if path and _same_norm(path, viewed_norm):
                continue
            if path and not str(path).strip().endswith(".py"):
                continue
            units.append((s.step_idx, "edit", code, path))
        elif tool == "execute_bash":
            cmd = args.get("command") or ""
            if not cmd.strip():
                continue
            for code in _extract_python_c(cmd):
                units.append((s.step_idx, "python_c", code, None))
            for code in _extract_heredocs(cmd):
                units.append((s.step_idx, "heredoc", code, None))
    return units


# ---------------------------------------------------------------- §4
# Match arms.

def _is_proper_ancestor(m, v):
    """m is a proper ancestor module of v (dotted prefix + dot)."""
    return v.startswith(m + ".") and m != v


def _parent_of(v):
    return v.rsplit(".", 1)[0] if "." in v else None


def _resolve_relative(level, module, containing_cands):
    """Resolve a relative import against containing-file candidates.
    Returns a set of resolved modules, or None if unresolvable
    (containing unknown, or level exceeds depth) -> silence."""
    if not containing_cands:
        return None
    out = set()
    for c in containing_cands:
        parts = c.split(".")
        # level 1 = current package (drop last component = the
        # containing module itself); level n drops n components.
        if level > len(parts):
            continue
        base = parts[:len(parts) - level]
        if module:
            base = base + module.split(".")
        if base:
            out.add(".".join(base))
    return out or None


def _import_stmt_arms(module, name, is_star, viewed_cands, defined,
                      reexport, is_init):
    """Arm evaluation for one import statement (module M, name N).
    Returns a list of (arm, tag) hits. Empty = no fire."""
    hits = []
    if is_star:
        # Star from exactly V only (ancestor-star is silence:
        # ambiguous, and ambiguity goes to silence).
        if module in viewed_cands:
            hits.append(("exact", "star-import"))
        return hits
    # Arm 1: exact module + name membership.
    if module in viewed_cands and name in defined:
        hits.append(("exact", None))
    # Arm 1b: from P import M with P.M == V (prefix required).
    for v in viewed_cands:
        if module == _parent_of(v) and name == v.rsplit(".", 1)[-1]:
            hits.append(("submodule-attribute", None))
            break
    # Arm 2 (narrowed, see module docstring): viewed __init__,
    # name in re-export set, module == IMMEDIATE PARENT of V.
    if is_init and name in reexport:
        for v in viewed_cands:
            if module == _parent_of(v):
                hits.append(("re-export-ancestor",
                             "re-export-pass-through"))
                break
    return hits


def _attribute_chain(node):
    """Dotted chain for an Attribute/Name expression, outermost
    first: [base, attr1, attr2, ...], or None if not a chain."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        parts.reverse()
        return parts
    return None


def _match_ast_unit(code, viewed_cands, defined, reexport, is_init,
                    containing_cands):
    """Matches from one parsed code unit. Returns list of match
    dicts (arm, tag, statement, resolved, name)."""
    matches = []
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        un = _unescape_code(code)
        if un != code:
            try:
                tree = ast.parse(un)
                code = un
            except (SyntaxError, ValueError):
                return None
        else:
            return None
    # Bindings within this unit only (draft §3).
    import_bindings = {}   # name -> module dotted
    from_bindings = set()  # names bound by from-imports (not modules)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                bound = alias.asname or alias.name.split(".")[0]
                import_bindings[bound] = mod
                if mod in viewed_cands:
                    matches.append({"arm": "exact", "tag": None,
                                    "statement": "import " + mod,
                                    "resolved": mod, "name": None})
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                mods = _resolve_relative(node.level, node.module,
                                         containing_cands)
                if not mods:
                    continue
            else:
                mods = {node.module} if node.module else set()
            for alias in node.names:
                if alias.name == "*":
                    for mod in mods:
                        if mod in viewed_cands:
                            matches.append(
                                {"arm": "exact", "tag": "star-import",
                                 "statement": "from %s import *" % mod,
                                 "resolved": mod, "name": None})
                    continue
                bound = alias.asname or alias.name
                from_bindings.add(bound)
                for mod in mods:
                    for arm, tag in _import_stmt_arms(
                            mod, alias.name, False, viewed_cands,
                            defined, reexport, is_init):
                        matches.append(
                            {"arm": arm, "tag": tag,
                             "statement": "from %s import %s"
                             % (mod, alias.name),
                             "resolved": mod, "name": alias.name})
    # Attribute chains: outermost Attribute nodes only (walk the
    # tree and skip Attribute nodes nested inside another
    # Attribute's value — those are sub-chains of the same use).

    def walk_attr(node):
        if isinstance(node, ast.Attribute):
            chain = _attribute_chain(node)
            if chain is not None and len(chain) >= 2:
                base = chain[0]
                if base not in from_bindings:
                    if base in import_bindings:
                        resolved = import_bindings[base].split(".") \
                            + chain[1:]
                    else:
                        resolved = list(chain)
                    for k in range(1, len(resolved)):
                        mod = ".".join(resolved[:k])
                        nm = resolved[k]
                        if mod in viewed_cands and nm in defined:
                            matches.append(
                                {"arm": "exact", "tag": None,
                                 "statement": ".".join(resolved),
                                 "resolved": mod, "name": nm})
                        elif is_init and nm in reexport:
                            for v in viewed_cands:
                                if mod == _parent_of(v):
                                    matches.append(
                                        {"arm": "re-export-ancestor",
                                         "tag": "re-export-pass-through",
                                         "statement": ".".join(resolved),
                                         "resolved": mod, "name": nm})
                                    break
                # Do not descend into this chain's sub-attributes.
                for child in ast.iter_child_nodes(node):
                    if child is not node.value:
                        walk_attr(child)
                return
        for child in ast.iter_child_nodes(node):
            walk_attr(child)

    walk_attr(tree)
    return matches


def _match_fallback_unit(code, viewed_cands, defined, reexport,
                         is_init, containing_cands):
    """Fallback for unparseable units: tokenize-masked line-start
    import shapes ONLY. A bare name mid-line, inside a string,
    or inside a comment never fires."""
    src = _unescape_code(code)
    masked = _mask_tokenize(src)
    if masked is None:
        masked = _strip_strings_comments_scan(src)
    matches = []
    for line in masked.splitlines():
        m = _IMPORT_RE.match(line)
        if m:
            mod = m.group(1)
            if mod in viewed_cands:
                matches.append({"arm": "exact", "tag": None,
                                "statement": line.strip(),
                                "resolved": mod, "name": None})
            continue
        m = _FROM_RE.match(line)
        if not m:
            continue
        raw_mod, rhs = m.group(1), m.group(2)
        if raw_mod.startswith("."):
            level = len(raw_mod) - len(raw_mod.lstrip("."))
            mods = _resolve_relative(level,
                                     raw_mod.lstrip(".") or None,
                                     containing_cands)
            if not mods:
                continue
        else:
            mods = {raw_mod}
        rhs = rhs.split(";")[0].strip().strip("()").strip()
        if rhs == "*":
            for mod in mods:
                if mod in viewed_cands:
                    matches.append({"arm": "exact",
                                    "tag": "star-import",
                                    "statement": line.strip(),
                                    "resolved": mod, "name": None})
            continue
        for part in rhs.split(","):
            part = part.strip()
            if not part:
                continue
            bits = part.split()
            nm = (bits[2] if len(bits) >= 3 and bits[1] == "as"
                  else bits[0])
            for mod in mods:
                for arm, tag in _import_stmt_arms(
                        mod, nm, False, viewed_cands, defined,
                        reexport, is_init):
                    matches.append({"arm": arm, "tag": tag,
                                    "statement": line.strip(),
                                    "resolved": mod, "name": nm})
    return matches


def match_file(viewed, units, trace_sets=None):
    """All matches for one viewed file over its downstream code
    units. viewed: dict with candidates/defined/reexport/prov/
    is_init (S_window). trace_sets (S_trace): {"defined",
    "reexport", "h3"} where h3 maps name -> proving step_idxs.

    Per unit, the effective name set is S_window ∪ S_trace, with
    H3 names admitted only when proven by a DIFFERENT unit
    (non-circularity gate). Each match carries "provenance":
    None (name in S_window at plain tier), "cond-import" (name
    only via the conditional chain), or "trace-harvested" (name
    only via S_trace). The arm "tag" field is unchanged from the
    successor (star-import / re-export-pass-through / None).
    """
    cands = viewed["candidates"]
    if not cands:
        return []
    t_defined = set()
    t_reexport = set()
    h3 = {}
    if trace_sets:
        t_defined = set(trace_sets.get("defined", ()))
        t_reexport = set(trace_sets.get("reexport", ()))
        h3 = trace_sets.get("h3", {}) or {}
    out = []
    for step_idx, kind, code, containing in units:
        cc = None
        if containing:
            cc = derive_module_paths(_norm_path(containing))
        h3_live = {nm for nm, steps in h3.items()
                   if steps - {step_idx}}
        eff_defined = viewed["defined"] | t_defined | h3_live
        eff_reexport = viewed["reexport"] | t_reexport | h3_live
        eff_prov = dict(viewed.get("prov", {}))
        for nm in t_defined | t_reexport | h3_live:
            eff_prov.setdefault(nm, "trace")
        res = _match_ast_unit(code, cands, eff_defined,
                              eff_reexport, viewed["is_init"], cc)
        if res is None:
            res = _match_fallback_unit(code, cands, eff_defined,
                                       eff_reexport,
                                       viewed["is_init"], cc)
        for m in res:
            m = dict(m)
            m["step_idx"] = step_idx
            m["unit_kind"] = kind
            nm = m.get("name")
            if nm is None:
                m["provenance"] = None
            elif eff_prov.get(nm) == "cond":
                m["provenance"] = "cond-import"
            elif eff_prov.get(nm) == "trace":
                m["provenance"] = "trace-harvested"
            else:
                m["provenance"] = None
            out.append(m)
    # Deduplicate (same arm/statement/resolved/name/step).
    seen, ded = set(), []
    for m in out:
        k = (m["arm"], m["statement"], m["resolved"], m["name"],
             m["step_idx"])
        if k not in seen:
            seen.add(k)
            ded.append(m)
    return ded


# ----------------------------------------------------------------
# Assessment entry point (check-runner shape).


def assess_trace(trace):
    """Import-leg assessment for one trace.

    files: one record per first-viewed non-listing/error file
    (grouped by same-file key, so re-views of one file are ONE
    file whose S_window comes from the flagged first view and
    whose S_trace unions the other views — H1):
      path, norm, key, view_step, candidates (sorted|None),
      defined, reexport, prov, trace_defined, trace_reexport,
      h3_proofs, h3_defeated, fallback, parse_reason,
      partial_view, is_init, matches, fired, matched_symbols,
      excerpts, provenances.
    live: files with fired=True. coverage: counts + parse reasons
    + trace-harvest totals.
    """
    views = _view_calls(trace)
    results = _call_results(trace)
    by_key = {}
    order = []
    for step_idx, path, view_range in views:
        key = _view_key(path)
        if key not in by_key:
            by_key[key] = []
            order.append(key)
        by_key[key].append((step_idx, path, view_range))
    files = []
    cov = {"views": len(views), "unique_files": 0, "fired_files": 0,
           "ast_files": 0, "fallback_files": 0, "partial_views": 0,
           "unrootable_files": 0, "parse_reasons": {},
           "units_scanned": 0, "trace_names": 0, "h3_proofs": 0}
    for key in order:
        step_idx, path, view_range = by_key[key][0]
        norm = _norm_path(path)
        result = results.get(step_idx)
        if result is None:
            continue
        if _is_listing(result) or _is_error(result):
            continue
        cands = derive_module_paths(norm)
        is_init = norm.endswith("/__init__.py") or \
            norm == "__init__.py"
        analyzed = analyze_viewed(result, view_range)
        t_defined, t_reexport = set(), set()
        h3_proofs, h3_defeated = {}, {}
        if cands is None:
            cov["unrootable_files"] += 1
            matches = []
        else:
            units = extract_code_units(trace, step_idx, norm)
            cov["units_scanned"] += len(units)
            # H1: union the name sets of ALL other views of the
            # same file in this trace (not just the flagged view).
            for (s2, p2, vr2) in by_key[key][1:]:
                r2 = results.get(s2)
                if r2 is None or _is_listing(r2) or _is_error(r2):
                    continue
                a2 = analyze_viewed(r2, vr2)
                t_defined |= a2["defined"]
                t_reexport |= a2["reexport"]
            # H2: grep-output definition lines for this file.
            t_defined |= _harvest_grep_names(trace, key)
            # H3: sibling-import harvest (with failure defeat).
            h3_proofs, h3_defeated = _harvest_sibling_imports(
                trace, cands, norm)
            viewed = {"candidates": cands,
                      "defined": analyzed["defined"],
                      "reexport": analyzed["reexport"],
                      "prov": analyzed["prov"],
                      "is_init": is_init}
            trace_sets = {"defined": t_defined,
                          "reexport": t_reexport, "h3": h3_proofs}
            matches = match_file(viewed, units, trace_sets)
            cov["trace_names"] += len(t_defined | t_reexport) + \
                len(h3_proofs)
            cov["h3_proofs"] += len(h3_proofs)
        if analyzed["fallback"]:
            cov["fallback_files"] += 1
        else:
            cov["ast_files"] += 1
        if analyzed["partial_view"]:
            cov["partial_views"] += 1
        reason = analyzed["parse_reason"]
        cov["parse_reasons"][reason] = \
            cov["parse_reasons"].get(reason, 0) + 1
        fired = bool(matches)
        if fired:
            cov["fired_files"] += 1
        files.append({
            "path": path, "norm": norm, "key": key,
            "view_step": step_idx,
            "candidates": sorted(cands) if cands else None,
            "defined": sorted(analyzed["defined"]),
            "reexport": sorted(analyzed["reexport"]),
            "prov": dict(analyzed["prov"]),
            "trace_defined": sorted(t_defined),
            "trace_reexport": sorted(t_reexport),
            "h3_proofs": {nm: sorted(ss)
                          for nm, ss in h3_proofs.items()},
            "h3_defeated": dict(h3_defeated),
            "fallback": analyzed["fallback"],
            "parse_reason": reason,
            "partial_view": analyzed["partial_view"],
            "is_init": is_init,
            "matches": matches, "fired": fired,
            "matched_symbols": sorted({m["name"] for m in matches
                                       if m["name"]}),
            "excerpts": sorted({m["statement"] for m in matches}),
            "provenances": sorted({m["provenance"] for m in matches
                                   if m.get("provenance")}),
        })
    cov["unique_files"] = len(files)
    live = [f for f in files if f["fired"]]
    return {"files": files, "live": live, "coverage": cov}


def import_evidence_items(assessment):
    """Population for the successor2 import leg (mirrors the
    successor's helper shape): fired files with matched symbols +
    excerpts + arm tags + provenance tags (trace-harvested /
    cond-import substrata report separately). No verdicts, no
    other-leg evidence."""
    items = []
    for f in assessment.get("live", []):
        items.append({
            "path": f["path"], "norm": f["norm"],
            "key": f.get("key"),
            "view_step": f["view_step"],
            "import_symbols": list(f.get("matched_symbols", [])),
            "from_import_excerpts": list(f.get("excerpts", [])),
            "arms": sorted({m["arm"] for m in f.get("matches", [])}),
            "tags": sorted({m["tag"] for m in f.get("matches", [])
                            if m.get("tag")}),
            "provenances": list(f.get("provenances", [])),
        })
    return items
