"""Read-coverage engine for the blind-edit detector.

Extracts read/write events from a trace's steps, builds a per-write
coverage ledger, and parses git output for post-hoc write evidence.
Pure functions over Step lists; no pricing, no findings — the detector
in detectors/blind_edit.py consumes the ledger.

Evidence rules (spec v0.2, ~/workspace/chewme-launch/
blind-edit-detector-spec.md):
- File size (lines_evidenced) comes from PRE-WRITE evidence only:
  earlier read results, `wc -l`, and the OLD side of git diffs (hunk
  headers and `-` lines describe the pre-change file, so a diff is
  admissible even when it appears after the write). The write's own
  new content and post-write reads are NEVER size evidence.
- `grep` is sampled, not coverage: it contributes 0 covered lines.
- Hunk headers give a LOWER bound on old-file size (a + b - 1); the
  maximum across all hunks is used.
- Git shows a changed line as a `-`/`+` pair: deletions are reported
  split into pure deletions vs changed (paired) lines.
- A deleted line whose content the trace shows the agent adding
  earlier is the agent's own line, not pre-existing content.
"""

import json
import re
from collections import Counter, deque

# --- constants (named in the report) ---------------------------------------
COVERAGE_THRESHOLD = 0.25
MIN_EVIDENCED_LINES = 40
MIN_EVIDENCED_BYTES = 2000
TRACE_MIN_DELETIONS = 10
GENERATED_SUFFIXES = (".lock", ".min.js", ".min.css", ".pb.go", "_pb2.py")
SCRIPT_SUFFIXES = (".py", ".sh", ".js", ".rb", ".pl")

_FENCE_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_CC_PREFIX = re.compile(r"^\[([A-Za-z_ ]+)\]\s+(\{.*\})\s*$", re.DOTALL)
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_HDR = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_STATUS = re.compile(r"^ ([MADRCU]|M|A|D|R|C|\?\?) (.+)$")
_STAT = re.compile(r"^\s*(.+?)\s*\|\s*\d+\s*([+-]*)\s*$")
_WC_LINE = re.compile(r"^\s*(\d+)\s+(\S+)\s*$")
_LS_LINE = re.compile(r"^[-d][rwx-]{9}\s+\d+\s+\S+\s+\S+\s+(\d+)\s+.*\s(\S+)\s*$")
_HEREDOC = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
_DIFF_SUMMARY = re.compile(
    r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?"
    r"(?:, (\d+) deletions?\(-\))?")


def _truncate_heredocs(cmd):
    """Drop heredoc bodies: their content is program text, not shell,
    and splitting it on ; or && invents commands that never ran."""
    lines = cmd.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = _HEREDOC.search(line)
        i += 1
        if m:
            delim = m.group(1)
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
            i += 1  # skip the delimiter line itself
    return "\n".join(out)


def parse_diff_summaries(text):
    """Global `git diff --stat` summaries: (files, insertions, deletions).
    These are trace-global numbers vs HEAD — not per-file evidence."""
    out = []
    for m in _DIFF_SUMMARY.finditer(text):
        out.append((int(m.group(1)), int(m.group(2) or 0),
                    int(m.group(3) or 0)))
    return out


def _norm(path, workdir):
    p = path.strip().strip('"').strip("'")
    if workdir and p.startswith(workdir.rstrip("/") + "/"):
        p = p[len(workdir.rstrip("/")) + 1:]
    if p.startswith("./"):
        p = p[2:]
    return p


def _same(a, b):
    """Same file across path spellings (absolute vs relative). Requires
    the shorter spelling to have >= 2 components — a bare filename is
    too collision-prone to suffix-match."""
    if a == b:
        return True
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return "/" in short and long.endswith("/" + short)


def _lines_of(text):
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _strip_result_prefix(text):
    # CC results look like "[Bash result] <out>" (single prefix, inline).
    m = re.match(r"^\[[^\]]+ result\] ", text)
    if m:
        return text[m.end():]
    # Harness results look like "[run_bash]\n[exit 0]\n<out>".
    if text.startswith("["):
        nl = text.find("\n")
        if nl >= 0:
            head = text[:nl]
            if head.startswith("[") and "]" in head and len(head) < 40:
                text = text[nl + 1:]
                if text.startswith("[exit"):
                    nl2 = text.find("\n")
                    text = text[nl2 + 1:] if nl2 >= 0 else ""
                return text
    return text


# --------------------------------------------------------------------------
# Tool-call extraction
# --------------------------------------------------------------------------

def _extract_calls(step):
    """Return list of (tool_name, args dict) for an assistant step."""
    out = []
    if step.role != "assistant":
        return out
    if step.tool_name:  # adapter-preserved structured call (Claude Code)
        m = _CC_PREFIX.match(step.text or "")
        if m:
            try:
                args = json.loads(m.group(2))
                if isinstance(args, dict):
                    out.append((step.tool_name, args))
            except json.JSONDecodeError:
                pass
        return out
    for m in _FENCE_JSON.finditer(step.text or ""):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "tool" in obj:
            out.append((str(obj["tool"]), obj.get("args") or {}))
    return out


# --------------------------------------------------------------------------
# Bash command parsing (heuristic; unparseable -> no event, never a guess)
# --------------------------------------------------------------------------

def _split_cmds(cmd):
    parts = re.split(r"&&|;", cmd)
    return [p.strip() for p in parts if p.strip()]


def _tokens(s):
    try:
        import shlex
        return shlex.split(s)
    except ValueError:
        return s.split()


def parse_bash(cmd):
    """Return events: list of dicts with kind in
    {read_span, read_full, read_tail, sampled, wc, ls, full_replace,
     pattern_edit, append, exec, git} plus path/params."""
    evs = []
    cmd = _truncate_heredocs(cmd)
    for part in _split_cmds(cmd):
        toks = _tokens(part)
        if not toks:
            continue
        head, rest = toks[0], toks[1:]
        if head == "cd":
            continue
        # Redirects first: `cat > f <<EOF` is a WRITE of f, not a read,
        # and `cmd > f` writes f regardless of the verb.
        rm = re.search(r"(?<![0-9&>])>(>?)\s*([^\s;|&]+)", part)
        if rm:
            evs.append({"kind": "append" if rm.group(1) else "full_replace",
                        "path": rm.group(2)})
            continue
        if head == "git":
            evs.append({"kind": "git", "args": rest})
            continue
        if head == "cat" and rest:
            for t in rest:
                if not t.startswith(("-", "<", ">", "&", "|")):
                    evs.append({"kind": "read_full", "path": t})
            continue
        if head in ("head", "tail") and rest:
            n, files = 10, []
            i = 0
            while i < len(rest):
                t = rest[i]
                if t == "-n" and i + 1 < len(rest):
                    n = int(rest[i + 1]) if rest[i + 1].isdigit() else n
                    i += 2
                    continue
                if re.fullmatch(r"-\d+", t):
                    n = int(t[1:])
                elif t.startswith("-"):
                    pass
                else:
                    files.append(t)
                i += 1
            for f in files:
                evs.append({"kind": "read_span" if head == "head" else "read_tail",
                            "path": f, "n": n})
            continue
        if head == "sed":
            joined = " ".join(toks)
            m = re.search(r"-n\s+['\"]?(\d+),(\d+)p", joined)
            if "-i" in toks or any(t.startswith("-i") for t in toks):
                files = [t for t in rest if not t.startswith("-")
                         and not re.search(r"[syp][/|]", t)]
                if files:
                    evs.append({"kind": "pattern_edit", "path": files[-1]})
            elif m:
                files = [t for t in rest if not t.startswith("-")]
                if files:
                    evs.append({"kind": "read_span", "path": files[-1],
                                "start": int(m.group(1)),
                                "end": int(m.group(2))})
            continue
        if head == "perl" and any(t.startswith("-pi") or t == "-i"
                                  for t in toks):
            files = [t for t in rest if not t.startswith("-")
                     and not t.startswith("s/") and "=" not in t]
            if files:
                evs.append({"kind": "pattern_edit", "path": files[-1]})
            continue
        if head == "grep":
            for t in rest:
                if "/" in t or "." in t.split("/")[-1]:
                    if not t.startswith("-"):
                        evs.append({"kind": "sampled", "path": t})
            continue
        if head == "wc" and "-l" in toks:
            for t in rest:
                if not t.startswith("-"):
                    evs.append({"kind": "wc", "path": t})
            continue
        if head == "ls":
            evs.append({"kind": "ls", "path": rest[-1] if rest else ""})
            continue
        if head == "tee":
            for t in rest:
                if not t.startswith("-"):
                    evs.append({"kind": "full_replace", "path": t})
            continue
        if head in ("python", "python3", "node", "bash", "sh", "ruby"):
            if not rest or rest[0] == "-" or rest[0].startswith("<<"):
                # heredoc program: agent-authored by definition
                evs.append({"kind": "exec", "path": "<stdin>",
                            "authored": True})
            elif rest[0].endswith(SCRIPT_SUFFIXES):
                evs.append({"kind": "exec", "path": rest[0]})
            continue
        if head.startswith("./") and head.endswith(SCRIPT_SUFFIXES):
            evs.append({"kind": "exec", "path": head})
            continue
    return evs


# --------------------------------------------------------------------------
# Git output parsing
# --------------------------------------------------------------------------

def parse_git_output(text):
    """Parse a tool result for git status/diff evidence.

    Returns {path: {pure_del: [contents], changed: [contents],
    added: [contents], old_lb: int, stat_del: bool, status: str}}."""
    out = {}
    cur = None          # current diff file
    dels, adds = [], []  # pending block within a hunk

    def flush():
        nonlocal dels, adds
        if cur is not None and (dels or adds):
            e = out[cur]
            paired = min(len(dels), len(adds))
            e["changed"].extend(dels[:paired])
            e["pure_del"].extend(dels[paired:])
            e["added"].extend(adds)
        dels, adds = [], []

    for line in text.splitlines():
        m = _DIFF_HDR.match(line)
        if m:
            flush()
            cur = m.group(2)
            out.setdefault(cur, {"pure_del": [], "changed": [], "added": [],
                                 "old_lb": 0, "stat_del": False,
                                 "status": ""})
            continue
        m = _HUNK.match(line)
        if m and cur is not None:
            flush()
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else 1
            e = out[cur]
            e["old_lb"] = max(e["old_lb"], a + b - 1)
            continue
        if cur is not None and line.startswith("-") \
                and not line.startswith("---"):
            dels.append(line[1:])
            continue
        if cur is not None and line.startswith("+") \
                and not line.startswith("+++"):
            adds.append(line[1:])
            continue
        if cur is not None and (line.startswith(" ") or line == ""):
            flush()
            continue
        m = _STATUS.match(line)
        if m:
            flush()
            cur = None
            code, path = m.group(1), m.group(2)
            e = out.setdefault(path, {"pure_del": [], "changed": [],
                                      "added": [], "old_lb": 0,
                                      "stat_del": False, "status": ""})
            e["status"] = code
            continue
        m = _STAT.match(line)
        if m and ("|" in line):
            flush()
            cur = None
            path, graph = m.group(1).strip(), m.group(2)
            e = out.setdefault(path, {"pure_del": [], "changed": [],
                                      "added": [], "old_lb": 0,
                                      "stat_del": False, "status": ""})
            if not e["status"]:
                e["status"] = "M"
            if "-" in graph:
                e["stat_del"] = True
            continue
    flush()
    return out


# --------------------------------------------------------------------------
# Assessment
# --------------------------------------------------------------------------

class Assessment:
    def __init__(self):
        self.assessed = False
        self.reason = ""
        self.entries = []        # ledger entries (dicts)
        self.n_calls = 0


def _union_len(spans):
    """Total lines covered by 1-based INCLUSIVE spans [(start, end)]."""
    if not spans:
        return 0
    spans = sorted(spans)
    total, cs, ce = 0, spans[0][0], spans[0][1]
    for s, e in spans[1:]:
        if s > ce + 1:
            total += ce - cs + 1
            cs, ce = s, e
        else:
            ce = max(ce, e)
    return total + (ce - cs + 1)


def assess(trace, workdir_diff_text=None):
    """Build the coverage ledger for one trace."""
    A = Assessment()
    steps = sorted(trace.steps, key=lambda s: s.step_idx)

    # workdir: most common `cd` target in bash commands
    cds = Counter()
    for s in steps:
        for tool, args in _extract_calls(s):
            if tool in ("Bash", "run_bash"):
                for m in re.finditer(r"cd\s+(\S+)", str(args.get("command",
                                        args.get("cmd", "")))):
                    cds[m.group(1)] += 1
    workdir = cds.most_common(1)[0][0] if cds else ""

    reads = []        # (step, path, start, end) 1-based inclusive spans
    tails = []        # (step, path, n)
    sampled = []      # (step, path)
    wc_ev = []        # (step, path, lines)
    ls_ev = []        # (step, path, bytes)
    writes = []       # (step, path, kind) direct writes
    execs = []        # (step, script path)
    authored = set()  # normalized paths the agent wrote
    added_lines = {}  # path -> list of (step, stripped content)
    git_obs = []      # (step, parsed dict)
    git_summaries = []  # (step, files_changed, insertions, deletions)
    pending = deque()  # pending calls awaiting results: (tool, args, events)

    def note_added(path, step, content):
        if content:
            added_lines.setdefault(path, []).extend(
                (step, ln.strip()) for ln in content.splitlines()
                if ln.strip())

    for s in steps:
        calls = _extract_calls(s)
        if calls:
            A.n_calls += len(calls)
        for tool, args in calls:
            evs = []
            if tool in ("Bash", "run_bash"):
                cmd = str(args.get("command", args.get("cmd", "")))
                evs = parse_bash(cmd)
            elif tool in ("Read", "read_file"):
                p = _norm(str(args.get("file_path", args.get("path", ""))),
                          workdir)
                off = args.get("offset") or 1
                lim = args.get("limit")
                evs = [{"kind": "read_span", "path": p,
                        "start": int(off),
                        "end": int(off) + int(lim) - 1}] if lim else \
                      [{"kind": "read_full", "path": p, "start": int(off)}]
            elif tool in ("Write", "write_file"):
                p = _norm(str(args.get("file_path", args.get("path", ""))),
                          workdir)
                evs = [{"kind": "full_replace", "path": p}]
                note_added(p, s.step_idx, str(args.get("content", "")))
            elif tool in ("Edit", "edit_file"):
                p = _norm(str(args.get("file_path", args.get("path", ""))),
                          workdir)
                evs = [{"kind": "span_edit", "path": p}]
                note_added(p, s.step_idx,
                           str(args.get("new_string",
                                        args.get("new_text", ""))))
            for ev in evs:
                if "path" in ev:
                    ev["path"] = _norm(ev["path"], workdir)
            pending.append((tool, args, evs, s.step_idx))

        if s.role == "tool":
            raw_full = s.text or ""
            failed = "tool error" in raw_full[:80]
            raw = _strip_result_prefix(raw_full)
            g = parse_git_output(raw)
            if g:
                git_obs.append((s.step_idx, g))
                for path, ch in g.items():
                    np = _norm(path, workdir)
                    for ln in ch["added"]:
                        note_added(np, s.step_idx, ln)
            for (nf, ins, dels) in parse_diff_summaries(raw):
                git_summaries.append((s.step_idx, nf, ins, dels))
            if pending:
                tool, args, evs, cstep = pending.popleft()
                nlines = _lines_of(raw)
                if failed:
                    evs = []  # a failed call changed nothing, read nothing
                for ev in evs:
                    k, p = ev["kind"], ev.get("path", "")
                    if k == "read_full":
                        st = ev.get("start", 1)
                        reads.append((cstep, p, st, st + max(nlines, 1) - 1))
                    elif k == "read_span" and "start" in ev:
                        reads.append((cstep, p, ev["start"], ev["end"]))
                    elif k == "read_span":
                        reads.append((cstep, p, 1, ev["n"]))
                    elif k == "read_tail":
                        tails.append((cstep, p, ev["n"]))
                    elif k == "sampled":
                        sampled.append((cstep, p))
                    elif k == "wc":
                        for ln in raw.splitlines():
                            m = _WC_LINE.match(ln)
                            if m and _norm(m.group(2), workdir) == p:
                                wc_ev.append((cstep, p, int(m.group(1))))
                    elif k == "ls":
                        for ln in raw.splitlines():
                            m = _LS_LINE.match(ln)
                            if m:
                                ls_ev.append((cstep,
                                              _norm(m.group(2), workdir),
                                              int(m.group(1))))
                    elif k in ("full_replace", "pattern_edit", "span_edit",
                               "append"):
                        writes.append((cstep, p, k))
                        if p not in authored:
                            authored.add(p)
                    elif k == "exec":
                        execs.append((cstep, p, bool(ev.get("authored"))))
            else:
                # result with no pending call: still harvest direct writes
                # recorded above are call-driven; nothing to do here.
                pass
        # direct writes from calls whose results may be missing: also
        # register writes immediately (a write counts even if its result
        # line was dropped from the export).
        # (Handled above via pending results; harness/CC exports pair
        # reliably, and double-registering would corrupt the ledger.)

    if A.n_calls == 0:
        A.reason = ("read-coverage could not be assessed — this export "
                    "does not carry tool inputs")
        return A
    A.assessed = True

    # final size evidence per file (old-side git bounds are timeless:
    # they describe the file as of trace start / HEAD)
    git_lb = {}
    for _, g in git_obs:
        for path, ch in g.items():
            np = _norm(path, workdir)
            if ch["old_lb"]:
                git_lb[np] = max(git_lb.get(np, 0), ch["old_lb"])

    def _lb(path):
        return max([v for k, v in git_lb.items() if _same(k, path)]
                   or [0])

    def evidenced(path, before_step):
        ev = _lb(path)
        for (st, p, a, b) in reads:
            if _same(p, path) and st < before_step:
                ev = max(ev, b)
        for (st, p, n) in wc_ev:
            if _same(p, path) and st < before_step:
                ev = max(ev, n)
        return ev

    def bytes_ev(path, before_step):
        return max([b for (st, p, b) in ls_ev
                    if _same(p, path) and st < before_step] or [0])

    def covered(path, before_step, evid):
        spans = [(a, b) for (st, p, a, b) in reads
                 if _same(p, path) and st < before_step]
        for (st, p, n) in tails:
            if _same(p, path) and st < before_step and evid:
                spans.append((max(1, evid - n + 1), evid))
        return _union_len(spans), [st for (st, p, a, b) in reads
                                   if _same(p, path) and st < before_step]

    created = set()
    seen_write = set()
    for (wstep, path, kind) in sorted(writes):
        pre_existing = any(st < wstep for (st, p, a, b) in reads
                           if _same(p, path)) or _lb(path) or \
            any(st < wstep for (st, p, n) in wc_ev if _same(p, path))
        is_creation = path not in seen_write and not pre_existing
        if is_creation:
            created.add(path)
        seen_write.add(path)
        evid = evidenced(path, wstep)
        byt = bytes_ev(path, wstep)
        cov_lines, ev_steps = covered(path, wstep, evid)
        substantial = evid >= MIN_EVIDENCED_LINES or \
            byt >= MIN_EVIDENCED_BYTES
        cov = (min(cov_lines, evid) / evid) if evid else 1.0
        A.entries.append({
            "file": path, "write_step": wstep, "write_kind": kind,
            "lines_read": cov_lines, "lines_evidenced": evid,
            "bytes_evidenced": byt, "coverage": round(cov, 4),
            "read_steps": ev_steps,
            "sampled_steps": [st for (st, p) in sampled
                              if _same(p, path) and st < wstep],
            "pre_existing": not is_creation, "substantial": substantial,
            "inferred": False, "outside_workdir": bool(
                workdir and path.startswith("/")
                and not path.startswith(workdir)),
            "generated": path.endswith(GENERATED_SUFFIXES),
            "scope": "file",
        })

    # ---- inferred, script-mediated writes from later git evidence ----
    prev_named = {}   # path -> step of last git observation naming it
    for (gstep, g) in git_obs:
        for path, ch in g.items():
            np = _norm(path, workdir)
            own = {c for k, v in added_lines.items() if _same(k, np) for (st, c) in v if st < gstep}
            pure_pre = [c for c in ch["pure_del"] if c.strip() not in own]
            chg_pre = [c for c in ch["changed"] if c.strip() not in own]
            own_ct = (len(ch["pure_del"]) - len(pure_pre)) + \
                     (len(ch["changed"]) - len(chg_pre))
            has_del_evidence = bool(pure_pre or chg_pre) or \
                (ch["stat_del"] and not ch["pure_del"] and not ch["changed"])
            window_start = prev_named.get(np, -1)
            # A modification already explained by a direct write event
            # in the window (Edit/Write/sed-i/redirect) is not
            # script-mediated evidence: inference exists for writes the
            # trace does NOT otherwise observe. (Held-out validation
            # catch: an Edit at step 21 explained a diff that a step-6
            # analysis script would otherwise have been blamed for.)
            explained = any(window_start < wst < gstep
                            for (wst, wp, wk) in writes if _same(wp, np))
            if explained:
                prev_named[np] = gstep
                continue
            # Mediation is the execution itself: an interpreter command
            # the agent chose to run. Authorship of the script file is
            # recorded when known but not required — files created via
            # heredoc redirects or outside the write tools are still
            # the agent's chosen instrument, and the flag is labeled
            # inferred regardless.
            win_execs = [st for (st, sp, au) in execs
                         if window_start < st < gstep]
            if has_del_evidence and win_execs:
                evid = max(_lb(np),
                           evidenced(np, win_execs[0]))
                cov_lines, ev_steps = covered(np, win_execs[0], evid)
                cov = (min(cov_lines, evid) / evid) if evid else 1.0
                A.entries.append({
                    "file": np, "write_step": gstep,
                    "write_kind": "script_mediated",
                    "lines_read": cov_lines, "lines_evidenced": evid,
                    "bytes_evidenced": bytes_ev(np, win_execs[0]),
                    "coverage": round(cov, 4), "read_steps": ev_steps,
                    "sampled_steps": [st for (st, p) in sampled
                                      if _same(p, np) and st < win_execs[0]],
                    "pre_existing": True,
                    "substantial": evid >= MIN_EVIDENCED_LINES,
                    "inferred": True, "outside_workdir": False,
                    "generated": np.endswith(GENERATED_SUFFIXES),
                    "modified_between": [win_execs[0], gstep],
                    "diff_step": gstep,
                    "pure_deletions": len(pure_pre),
                    "changed_lines": len(chg_pre),
                    "own_line_deletions": own_ct,
                    "deletions_from_stat_only": bool(
                        ch["stat_del"] and not ch["pure_del"]
                        and not ch["changed"]),
                    "scope": "file",
                })
            prev_named[np] = gstep

    # ---- trace-level inference: global deletions after script runs --
    # Per-file attribution is often absent (the agent's own `| head`
    # truncated the diffs), and a shallow agent leaves a shallow trace:
    # per-file size evidence may not exist either. What the trace DOES
    # prove is the conjunction — script-mediated mass modification,
    # deletions vs HEAD in the diff summaries, and a shallow read
    # profile over the files git names. One entry per trace, from the
    # last known-clean checkpoint to the last deletion-bearing summary.
    # Deletions are trace-global: how many were the agent's own earlier
    # insertions is not determinable at this tier.
    del_summaries = [(st, nf, ins, dl) for (st, nf, ins, dl)
                     in git_summaries if dl > 0]
    if del_summaries:
        first_del_step = del_summaries[0][0]
        last_del_step, last_nfiles, _, last_dels = del_summaries[-1]
        clean = [st for (st, nf, ins, dl) in git_summaries
                 if dl == 0 and st < first_del_step]
        clean += [st for (st, _) in git_obs if st < first_del_step]
        window_start = max(clean) if clean else -1
        win = [st for (st, sp, au) in execs
               if window_start < st <= last_del_step]
        named = set()
        for (gs2, g2) in git_obs:
            if window_start < gs2 <= last_del_step:
                named.update(_norm(p, workdir) for p in g2)
        named -= created
        shallow, unread, read_ok = [], [], []
        for np in sorted(named):
            spans = [(a, b) for (st, p, a, b) in reads
                     if _same(p, np) and st < last_del_step]
            full = any(b - a >= 50 for (a, b) in spans)
            if not spans:
                unread.append(np)
            elif not full and all(b <= 10 for (a, b) in spans):
                shallow.append(np)
            else:
                read_ok.append(np)
        # Trigger requires SHALLOW-READ files specifically (the agent
        # formed beliefs from partial reads) and a non-trivial deletion
        # count. Merely-unread files do NOT trigger: batch scripts that
        # parse files programmatically are a legitimate pattern, and a
        # clean run's summary can still show a few deletions vs HEAD
        # (its own adjusted insertions). Unread files are still counted
        # in the entry's profile for context.
        if win and named and shallow and last_dels >= TRACE_MIN_DELETIONS:
            A.entries.append({
                "file": "", "write_step": last_del_step,
                "write_kind": "script_mediated",
                "lines_read": None, "lines_evidenced": None,
                "bytes_evidenced": 0, "coverage": None,
                "read_steps": [], "sampled_steps": [],
                "pre_existing": True, "substantial": True,
                "inferred": True, "outside_workdir": False,
                "generated": False,
                "modified_between": [win[0], last_del_step],
                "diff_step": last_del_step,
                "global_deletions": last_dels,
                "files_changed": last_nfiles,
                "window_files": sorted(named),
                "shallow_files": shallow, "unread_files": unread,
                "read_ok_files": read_ok,
                "own_line_split_unknown": True,
                "scope": "trace",
            })

    # ---- optional user-supplied workdir diff (exact write evidence) ----
    if workdir_diff_text:
        g = parse_git_output(workdir_diff_text)
        last_step = steps[-1].step_idx if steps else 0
        for path, ch in g.items():
            np = _norm(path, workdir)
            # Same principle as the inferred tier: if the trace itself
            # already shows a direct write to this file, that observed
            # write governs — the supplied diff adds no new evidence
            # about it (and would double-count a self-evidencing span
            # edit as a blind one).
            if any(_same(wp, np) for (_, wp, _) in writes):
                continue
            own = {c for k, v in added_lines.items() if _same(k, np) for (_, c) in v}
            pure_pre = [c for c in ch["pure_del"] if c.strip() not in own]
            chg_pre = [c for c in ch["changed"] if c.strip() not in own]
            if not (pure_pre or chg_pre or ch["added"]):
                continue
            evid = max(ch["old_lb"], evidenced(np, last_step + 1))
            cov_lines, ev_steps = covered(np, last_step + 1, evid)
            has_reads = any(_same(p, np) for (_, p, a, b) in reads)
            cov = (min(cov_lines, evid) / evid) if (evid and has_reads) \
                else None
            A.entries.append({
                "file": np, "write_step": None,
                "write_kind": "workdir_diff",
                "lines_read": cov_lines if has_reads else None,
                "lines_evidenced": evid, "bytes_evidenced": 0,
                "coverage": (round(cov, 4) if cov is not None else None),
                "read_steps": ev_steps, "sampled_steps": [],
                "pre_existing": True,
                "substantial": evid >= MIN_EVIDENCED_LINES,
                "inferred": False, "outside_workdir": False,
                "generated": np.endswith(GENERATED_SUFFIXES),
                "pure_deletions": len(pure_pre),
                "changed_lines": len(chg_pre),
                "own_line_deletions":
                    (len(ch["pure_del"]) - len(pure_pre))
                    + (len(ch["changed"]) - len(chg_pre)),
                "scope": "file",
            })
    return A
