"""Unverified-final-state detector — the second RISK flag family.

Flags coding-agent traces whose final code state was never verified
after the agent's last edit (F1/F2/F3), and edits to pre-existing
test files (F4). Risk flags are never priced: an unverified finish
that works costs no tokens — its cost is damage when it doesn't.
Findings ship measurable=False, waste_tokens=0.

Spec: ~/workspace/chewme-launch/unverified-final-state-spec.md (v0.2).
Scope: coding-agent traces only (spec section 2). The flag
predicates are section 4 of the spec, verbatim; verdicts follow
section 3's ordering (exit code first, text signatures as fallback,
plain-language reports included — the discovery run's v1 error was
summary-shaped-only signatures).
"""

import re

from .base import Finding

DEFINITION = ("unverified final state = the trace ends with edits "
              "no test run or verification event follows")

# ---- test-run / verification recognition (spec section 3) ----
TEST_RUN_SIG = re.compile(
    r"pytest|python\s+-m\s+(pytest|unittest)|runtests\.py|\btox\b|"
    r"nosetests|\bjest\b|go\s+test|cargo\s+test|reframe|"
    r"python\s+\S*test_\w*\.py|python\s+\S*/tests?/\S*\.py")
SEGMENT_SPLIT = re.compile(r"&&|\|\||;")


def _is_test_run(cmd):
    """A test run must EXECUTE: the runner heads a shell segment
    (after any cd/env prefixes). A mention inside another command
    (grep 'pytest', cat a test file, find/open a path containing
    'reframe') is not a run — the discovery scanner anchored on
    execution, and mention-matching inflates the run count
    (93 vs the discovery 77 on the same corpus).

    Recognition is by the segment's executable, not by substring:
    - pytest / py.test / nosetests / tox / jest as the executable;
    - python -m pytest|unittest, or python executing a file that
      is a test file under section 3's identification table
      (direct_test_*.py is NOT one — it is a verification script);
    - runtests.py as the executable;
    - go test / cargo test;
    - a reframe executable running checks/unittests (the
      discovery scanner's reframe rule)."""
    for exe, args, seg in _segments(cmd):
        if exe in ('pytest', 'py.test', 'nosetests', 'tox', 'jest',
                   'runtests.py'):
            return True
        if exe in ('python', 'python3'):
            if len(args) >= 2 and args[0] == '-m' and \
                    args[1] in ('pytest', 'unittest', 'nose'):
                return True
            if args and args[0].endswith('.py') and \
                    is_test_file(args[0].strip("'\"")):
                return True
        if exe == 'go' and args[:1] == ['test']:
            return True
        if exe == 'cargo' and args[:1] == ['test']:
            return True
        if exe == 'reframe' and ('check' in seg or 'unittest' in seg):
            return True
    return False
SCRIPT_EXEC = re.compile(r"(?:python3?|bash|sh)\s+(\S+\.(?:py|sh))")
SHELL_WRITE = re.compile(r"sed\s+-i|>>?\s*[^\s;&|]|git\s+apply|"
                         r"\bpatch\s*<|tee\s+")
BUILD_EXES = {'make', 'tsc', 'mypy', 'pyright', 'gradle', 'mvn'}


def _segments(cmd):
    """Shell segments as (executable basename, args, raw segment),
    with cd/env prefixes stripped. Recognition keys on the
    executable that actually runs — never on substrings elsewhere
    in the command line."""
    out = []
    for seg in SEGMENT_SPLIT.split(cmd or ''):
        seg = seg.strip()
        seg = re.sub(r"^(cd\s+\S+\s*&&\s*)?", "", seg)
        seg = re.sub(r"^(\w+=\S+\s+)+", "", seg)
        toks = seg.split()
        if not toks:
            continue
        exe = toks[0].strip("'\"").rsplit('/', 1)[-1]
        out.append((exe, toks[1:], seg))
    return out


def _norm_path(path):
    if not path:
        return ''
    p = str(path).strip().strip("'\"").replace('\\', '/')
    p = re.sub(r'/+', '/', p)
    if p.startswith('./'):
        p = p[2:]
    return p.strip('/')


def _same_path(a, b):
    """Path identity across the forms a trace mixes: an editor
    create may record 'reproduce.py' while a later modify names
    '/repo/reproduce.py'. Equal after normalization, or one a
    path-boundary suffix of the other (A3's normalization rule —
    the dev-slice breakdown depended on it)."""
    na, nb = _norm_path(a), _norm_path(b)
    if not na or not nb:
        return False
    return na == nb or na.endswith('/' + nb) or nb.endswith('/' + na)


def _in_created(path, created_paths):
    return any(_same_path(path, c) for c in created_paths)


CODE_EXT = re.compile(r"\.(py|js|jsx|ts|tsx|go|rs|java|rb|php|"
                      r"c|cc|cpp|h|hpp|cs|swift|kt|scala|sh)$", re.I)


def file_class(path):
    """Spec section 4 file classes: test / source / other
    (docs, config, notes, unknown targets)."""
    if not path:
        return 'other'
    if is_test_file(path):
        return 'test'
    base = _norm_path(path).rsplit('/', 1)[-1]
    return 'source' if CODE_EXT.search(base) else 'other'


def _strip_quotes(cmd):
    """Remove single/double-quoted spans. Shell metacharacters
    inside quotes are data, not operators: a python -c script
    whose code contains '>' (regex named groups, comparisons)
    is not a redirection, and Stage C hand-checks found exactly
    that phantom. Escapes are honored inside double quotes."""
    out = []
    quote = None
    i = 0
    while i < len(cmd or ''):
        ch = cmd[i]
        if quote:
            if ch == '\\' and quote == '"' and i + 1 < len(cmd):
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _shell_target(cmd):
    """Best-effort target of a shell write: the redirection
    target, the tee argument, or the file a sed -i rewrites.
    Quoted spans are stripped first, and an fd duplication
    (2>&1) is not a file target."""
    bare = _strip_quotes(cmd)
    m = re.search(r">>?\s*([^\s;&|]+)", bare)
    if m:
        target = m.group(1).strip("'\"")
        # The null device is not a file: 'cmd > /dev/null' mutates
        # nothing (Stage C hand-check found an F1 resting on it).
        return None if target == '/dev/null' else target
    m = re.search(r"\btee\s+(?:-\w+\s+)*([^\s;&|]+)", bare)
    if m:
        return m.group(1).strip("'\"")
    if re.search(r"sed\s+-i", bare):
        toks = [t.strip("'\"") for t in cmd.split()]
        files = [t for t in toks[1:] if not t.startswith('-')
                 and ('/' in t or '.' in t)]
        if files:
            return files[-1]
    return None

EXIT_CODE = re.compile(r"exit code[:\s]*(-?\d+)", re.I)
FAIL_SIG = re.compile(r"\d+\s+failed|\bFAILED\b|\d+\s+errors?\b|FAILURES|"
                      r"error code [1-9]|returning error|"
                      r"Traceback \(most recent call last\):"
                      r"[\s\S]{0,400}(Error|assert)", re.I)
PASS_SIG = re.compile(r"\d+\s+passed|^\s*OK\s*$|\bOK\b\s*$|100%|"
                      r"all tests passed|completed successfully",
                      re.M | re.I)

TEST_DIR = re.compile(r"(^|/)(tests?|__tests__|spec)(/|$)")
TEST_BASE = re.compile(r"(^test_\w+\.py$|_test\.(py|go)$|_spec\.\w+$|"
                       r"\.test\.\w+$|\.spec\.\w+$|conftest\.py$)")
FENCED = re.compile(r"```[^\n]*\n(.*?)```", re.S)
OPEN_FILE = re.compile(r"\(Open file:\s*([^)]+)\)")
PATH_IN_ARGS = re.compile(r'"(?:path|file_path)"\s*:\s*"([^"]+)"')
CMD_IN_ARGS = re.compile(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"')
FN_NAME = re.compile(r'"name"\s*:\s*"(str_replace_editor|execute_bash|'
                     r'Write|Edit|Bash)"')
COMPLETION_CLAIM = re.compile(
    r"TASK COMPLETE|task (is )?complete|all (tests|checks) pass|"
    r"successfully (fixed|completed|implemented)", re.I)


def is_test_file(path):
    if not path:
        return False
    base = path.rsplit('/', 1)[-1]
    return bool(TEST_DIR.search(path) or TEST_BASE.search(base))


HARD_FAIL_SIG = re.compile(r"\d+\s+failed|FAILED\s*\(|"
                           r"failures\s*=\s*[1-9]|errors\s*=\s*[1-9]",
                           re.I)


def verdict_of(observation):
    """Spec section 3 ordering: exit code, then signatures.

    Signature precedence: a hard failure summary (a failed count,
    FAILED (...), failures=N>0) dominates everything. Below that,
    the run's own success evidence (a passed count with no failed
    count, unittest OK, a plain-language pass report) beats soft
    failure-shaped content — a traceback the run was DESIGNED to
    produce inside a passing error-handling test is content, not
    a verdict. Soft failure evidence alone is a FAIL; no evidence
    either way is UNKNOWN, never rounded."""
    if observation:
        m = EXIT_CODE.search(observation)
        if m:
            return 'PASS' if int(m.group(1)) == 0 else 'FAIL'
        if HARD_FAIL_SIG.search(observation):
            return 'FAIL'
        fail = FAIL_SIG.search(observation)
        passed = PASS_SIG.search(observation)
        if fail and passed:
            return 'PASS'
        if fail:
            return 'FAIL'
        if passed:
            return 'PASS'
    return 'UNKNOWN'


def _is_verify(cmd):
    """A verification event that is not a test run (spec section
    3): executing a reproduction/verification script, or a build
    / typecheck. Recognition is by segment executable, like test
    runs — a script merely mentioned is not executed."""
    for exe, args, _seg in _segments(cmd):
        if exe in ('python', 'python3', 'bash', 'sh') and args and \
                args[0].endswith(('.py', '.sh')) and \
                not is_test_file(args[0].strip("'\"")):
            return True
        if exe in BUILD_EXES:
            return True
        if exe == 'cargo' and args[:1] in (['build'], ['check']):
            return True
        if exe == 'go' and args[:1] in (['build'], ['vet']):
            return True
        if exe in ('npm', 'yarn', 'pnpm') and \
                args[:2] == ['run', 'build']:
            return True
    return False


def _provenance_moves(cmd):
    """mv/cp segments in a command, as (kind, src, dst) — applied
    as a side effect whatever else the command is (a compound
    'mv a b && pytest' is a test run AND a rename). Provenance
    follows the file across a rename; a copy target is a new
    file by the agent's act (Stage C false-F4 class)."""
    moves = []
    for exe, args, _seg in _segments(cmd):
        plain = [a.strip("'\"") for a in args
                 if not a.startswith('-')]
        if exe == 'mv' and len(plain) >= 2:
            moves.append(('RENAME', plain[-2], plain[-1]))
        elif exe == 'cp' and len(plain) >= 2:
            moves.append(('COPY', plain[-2], plain[-1]))
    return moves


def _classify_command(cmd, observation, open_file, created):
    """One shell command -> (kind, detail). SWE-agent's edit/create
    commands mutate the currently-open file (discovery rule).
    EDIT details are dicts: {op, target, agent_created} — the
    caller resolves agent_created against the created-set as it
    stood BEFORE this event (a creation precedes the edit)."""
    parts = cmd.strip().split(None, 1)
    head = parts[0] if parts else ''
    if head == 'create':
        target = parts[1].strip().strip("'\"") if len(parts) > 1 \
            else open_file
        if target:
            created.add(target)
        return 'EDIT', {'op': 'create', 'target': target,
                        'agent_created': True}
    if head == 'edit':
        return 'EDIT', {'op': 'modify', 'target': open_file,
                        'agent_created': None}
    if _is_test_run(cmd):
        return 'TESTRUN', (cmd[:80], verdict_of(observation))
    if SHELL_WRITE.search(_strip_quotes(cmd)):
        target = _shell_target(cmd)
        if target is None and '>' in _strip_quotes(cmd) and \
                'sed' not in cmd and 'tee' not in cmd and \
                'apply' not in cmd and 'patch' not in cmd:
            # The only write shape was a redirection whose target
            # is not a file (e.g. /dev/null): not an edit.
            return 'OTHER', cmd[:60]
        # A truncating '>' redirection CREATES its target when
        # the target has not been seen before — the file comes
        # into existence by this very command, so it is an
        # agent-created file, not an edit of a pre-existing one
        # (Stage C hand-check: F1s resting on 'echo ... > /tmp/x'
        # scratch creations were false flags). The conversion
        # loop applies this via write_mode + the created
        # sequence; appends and in-place rewrites keep modify
        # semantics.
        bare = _strip_quotes(cmd)
        write_mode = None
        if re.search(r">>(?![>&])", bare):
            write_mode = 'append'
        elif re.search(r">(?![>&])", bare):
            write_mode = 'truncate'
        return 'EDIT', {'op': 'shell', 'target': target,
                        'agent_created': None,
                        'write_mode': write_mode}
    if _is_verify(cmd):
        return 'VERIFY', cmd[:80]
    return 'OTHER', cmd[:60]


def events_for(trace):
    """Derive (events, created_paths, end_type) from normalized Steps.

    Single in-order pass. Command events snapshot the open file at
    command time; the following tool/user step is the observation
    (verdict source). Native tool calls flattened to text by the
    adapters are recognized by function name in the step text."""
    raw = []            # [step_idx, kind|None, detail, observation, open_file]
    created = set()
    end_type = None
    open_file = None
    pending = None
    for s in trace.steps:
        text = s.text or ''
        role = s.role or ''
        if role in ('tool', 'user'):
            m = OPEN_FILE.search(text)
            if m:
                open_file = m.group(1).strip()
            if pending is not None:
                raw[pending][3] = text
                pending = None
            continue
        if role not in ('assistant', 'ai'):
            continue
        blocks = FENCED.findall(text)
        if blocks and blocks[0].strip() and not s.tool_name:
            # Fenced-command extraction is the SWE-agent convention:
            # it applies to steps with no structured tool identity.
            # A step an adapter already typed (tool_name set) carries
            # its actions as structured calls, parsed below — its
            # fenced blocks are prose/code snippets, and reading one
            # as a command manufactures phantom edits (Stage C).
            cmd = blocks[0].strip().splitlines()[0].strip()
            if cmd:
                raw.append([s.step_idx, None, cmd, '', open_file])
                pending = len(raw) - 1
        for nm in FN_NAME.finditer(text):
            name = nm.group(1)
            seg = text[nm.start():nm.start() + 4000]
            if name == 'str_replace_editor':
                cm = CMD_IN_ARGS.search(seg)
                pm = PATH_IN_ARGS.search(seg)
                sub = cm.group(1) if cm else ''
                path = pm.group(1) if pm else None
                if sub == 'view':
                    raw.append([s.step_idx, 'READ', path, '', open_file])
                elif sub == 'create':
                    if path:
                        created.add(path)
                    raw.append([s.step_idx, 'EDIT',
                                {'op': 'create', 'target': path,
                                 'agent_created': True},
                                '', open_file])
                elif sub in ('str_replace', 'insert'):
                    raw.append([s.step_idx, 'EDIT',
                                {'op': 'modify', 'target': path,
                                 'agent_created': None},
                                '', open_file])
                else:
                    raw.append([s.step_idx, 'OTHER', f'editor:{sub}',
                                '', open_file])
            elif name in ('Write', 'Edit'):
                pm = PATH_IN_ARGS.search(seg)
                raw.append([s.step_idx, 'EDIT',
                            {'op': 'modify',
                             'target': pm.group(1) if pm else None,
                             'agent_created': None},
                            '', open_file])
            else:  # execute_bash / Bash
                cm = CMD_IN_ARGS.search(seg)
                cmd = cm.group(1).replace('\\"', '"') if cm else text[:200]
                raw.append([s.step_idx, None, cmd, '', open_file])
                pending = len(raw) - 1
        if re.search(r'^\s*submit\s*$', text, re.M):
            end_type = 'submitted'
    events = []
    created_seq = []    # creation order: A3 counts a file as
    # agent-created only when its creation PRECEDES the edit.
    seen_seq = []       # every path the trace has touched so
    # far (views, edits, creates): a truncating redirection to
    # a never-seen path creates a new file; to a seen path it
    # rewrites a pre-existing one.
    for idx, kind, detail, obs, ofile in raw:
        if kind is None:
            for mv_kind, src, dst in _provenance_moves(detail):
                if mv_kind == 'RENAME':
                    if _in_created(src, created_seq):
                        created_seq.append(dst)
                else:  # COPY: target is a new file by the act
                    created_seq.append(dst)
                seen_seq.append(dst)
            kind, detail = _classify_command(detail, obs, ofile, created)
        if kind == 'READ' and detail:
            seen_seq.append(detail)
        if kind == 'EDIT' and isinstance(detail, dict):
            tgt = detail.get('target')
            if detail.get('op') == 'create':
                detail['agent_created'] = True
                if tgt:
                    created_seq.append(tgt)
                    seen_seq.append(tgt)
            elif detail.get('agent_created') is None:
                if detail.get('write_mode') == 'truncate' and tgt \
                        and not _in_created(tgt, seen_seq):
                    detail['agent_created'] = True
                    created_seq.append(tgt)
                else:
                    detail['agent_created'] = _in_created(
                        tgt, created_seq)
                if tgt:
                    seen_seq.append(tgt)
        events.append((idx, kind, detail))
    if end_type is None:
        tail = ' '.join((s.text or '') for s in trace.steps[-3:])
        end_type = 'claimed-complete' if COMPLETION_CLAIM.search(tail) \
            else 'exhausted'
    return events, created, end_type


def assess_trace(trace):
    """Spec section 4 predicates over one trace's events, with
    amendment A3 applied to F1: F1 fires only when at least one
    post-pass edit targets a PRE-EXISTING file (a file whose
    creation does not precede the edit in this trace, paths
    normalized across editor/shell forms). Post-pass edits to
    files the agent itself created — verification scripts it
    kept iterating, scratch it later deleted — do not fire F1;
    on the development slice they were 69% of post-pass edits
    and 222 of 327 old-F1 traces had nothing else."""
    events, created, end_type = events_for(trace)
    cov = {'commands': len(events), 'test_runs': 0, 'edits': 0,
           'unclassified': 0,
           'verdicts': {'PASS': 0, 'FAIL': 0, 'UNKNOWN': 0}}
    edit_events, runs, vers = [], [], []
    info_test_edits = 0
    f4 = 0
    for idx, kind, detail in events:
        if kind == 'TESTRUN':
            cov['test_runs'] += 1
            cov['verdicts'][detail[1]] += 1
            runs.append((idx, detail[1]))
            vers.append(idx)
        elif kind == 'VERIFY':
            vers.append(idx)
        elif kind == 'EDIT':
            cov['edits'] += 1
            d = detail if isinstance(detail, dict) else {}
            rec = {'step': idx, 'op': d.get('op'),
                   'target': d.get('target'),
                   'agent_created': bool(d.get('agent_created')),
                   'file_class': file_class(d.get('target'))}
            edit_events.append(rec)
            if is_test_file(rec['target']):
                if rec['agent_created']:
                    info_test_edits += 1
                else:
                    f4 += 1
        elif kind == 'OTHER':
            cov['unclassified'] += 1
    flags = {}
    flag_details = {}
    if edit_events:
        last_edit = max(e['step'] for e in edit_events)
        passes = [i for i, v in runs if v == 'PASS']
        last_pass = max(passes) if passes else None
        last_run = max(i for i, _ in runs) if runs else None
        last_ver = max(vers) if vers else None

        def _detail(ref_step, post):
            classes = sorted({e['file_class'] for e in post})
            return {
                'reference_step': ref_step,
                'post_edits': post,
                'post_edit_classes': classes,
                'only_non_code': bool(post) and
                all(e['file_class'] == 'other' for e in post),
            }

        f1 = False
        if last_pass is not None and last_edit > last_pass and \
                not any(i > last_edit for i, _ in runs):
            post_pass = [e for e in edit_events if e['step'] > last_pass]
            if any(e['target'] and not e['agent_created']
                   for e in post_pass):
                f1 = True
                flags['F1'] = True
                flag_details['F1'] = _detail(last_pass, post_pass)
        if not f1 and runs and last_edit > last_run:
            post_run = [e for e in edit_events if e['step'] > last_run]
            flags['F2'] = True
            flag_details['F2'] = _detail(last_run, post_run)
        if not any(i > last_edit for i in vers):
            post_ver = [e for e in edit_events
                        if last_ver is None or e['step'] > last_ver]
            flags['F3'] = True
            flag_details['F3'] = _detail(last_ver, post_ver)
        if not vers:
            flags['F3a'] = True
            flag_details['F3a'] = flag_details.get('F3', {})
    if f4:
        flags['F4'] = f4
    return {'flags': flags, 'end_type': end_type, 'coverage': cov,
            'info_test_edits': info_test_edits,
            'flag_details': flag_details,
            'edit_events': edit_events,
            'last_edit_step': max(e['step'] for e in edit_events)
            if edit_events else None,
            'events': events}


_FLAG_BLURB = {
    'F1': 'edit(s) after the last PASSING test run, at least one '
          'to a pre-existing file, no test run after them',
    'F2': 'edit(s) after the last test run, no test run after them',
    'F3': 'no verification event after the final edit',
    'F3a': 'no verification event anywhere in the trace',
}


def assess_and_flag(trace):
    """Mirror blind_edit.assess_and_flag's shape: (findings, info)."""
    a = assess_trace(trace)
    findings = []
    for name in ('F1', 'F2', 'F3', 'F4'):
        if name in a['flags']:
            if name == 'F4':
                summary = (f"F4: {a['flags']['F4']} edit(s) to "
                           f"pre-existing test files.")
                detail = {'flag': name, 'coverage': a['coverage']}
            else:
                d = a['flag_details'].get(name, {})
                post = d.get('post_edits', [])
                classes = ', '.join(d.get('post_edit_classes', []))
                summary = (f"{name}: trace ends ({a['end_type']}) with "
                           f"{_FLAG_BLURB[name]}"
                           + (f" — {len(post)} post-verification "
                              f"edit(s), classes: {classes}."
                              if post else ".")
                           + " Final state unverified in the trace.")
                detail = {'flag': name, 'end_type': a['end_type'],
                          'coverage': a['coverage'],
                          'reference_step': d.get('reference_step'),
                          'post_edits': post,
                          'post_edit_classes':
                              d.get('post_edit_classes', []),
                          'only_non_code': d.get('only_non_code', False)}
            findings.append(Finding(
                detector='unverified_final_state',
                trace_id=trace.trace_id,
                step_idx=a['last_edit_step'] or 0,
                waste_tokens=0,
                token_basis='n/a',
                summary=summary,
                detail=detail,
                fix_key='',
                measurable=False,
            ))
    info = {'assessed': True, 'trace_id': trace.trace_id,
            'flags': a['flags'],
            'end_type': a['end_type'], 'coverage': a['coverage'],
            'info_test_edits': a['info_test_edits'],
            'flag_details': a['flag_details']}
    return findings, info


def aggregate(infos):
    """Fold per-trace info dicts into the report-level block the
    spec's section 7 requires: flag counts (traces per flag),
    the F1–F3 breakdown by end type, the informational count,
    non-code-only flag counts, and the mandatory coverage block.
    The report does not render a UFS verdict line without this
    coverage beside it (spec section 2)."""
    import collections
    flags = {n: 0 for n in ('F1', 'F2', 'F3', 'F3a', 'F4')}
    flagged_traces = {n: [] for n in flags}
    by_end = {n: collections.Counter() for n in ('F1', 'F2', 'F3', 'F3a')}
    non_code_only = collections.Counter()
    cov = {'traces': len(infos), 'commands': 0, 'test_runs': 0,
           'edits': 0, 'unclassified': 0, 'no_commands': 0,
           'verdicts': {'PASS': 0, 'FAIL': 0, 'UNKNOWN': 0}}
    info_test_edits = 0
    for info in infos:
        c = info['coverage']
        cov['commands'] += c['commands']
        cov['test_runs'] += c['test_runs']
        cov['edits'] += c['edits']
        cov['unclassified'] += c['unclassified']
        if c['commands'] == 0:
            cov['no_commands'] += 1
        for v in cov['verdicts']:
            cov['verdicts'][v] += c['verdicts'][v]
        info_test_edits += info['info_test_edits']
        for name in flags:
            if name in info['flags']:
                flags[name] += 1
                flagged_traces[name].append(info['trace_id'])
                if name in by_end:
                    by_end[name][info['end_type']] += 1
                d = info['flag_details'].get(name, {})
                if d.get('only_non_code'):
                    non_code_only[name] += 1
    return {
        'traces_checked': len(infos),
        'flags': flags,
        'flagged_traces': flagged_traces,
        'by_end_type': {n: dict(by_end[n]) for n in by_end},
        'non_code_only': dict(non_code_only),
        'info_test_edits': info_test_edits,
        'coverage': cov,
    }
