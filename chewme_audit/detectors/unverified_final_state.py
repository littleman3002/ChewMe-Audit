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
    (grep 'pytest', cat a test file) is not a run — the discovery
    scanner anchored on execution, and mention-matching inflates
    the run count (93 vs the discovery 77 on the same corpus)."""
    for seg in SEGMENT_SPLIT.split(cmd):
        seg = seg.strip()
        seg = re.sub(r"^(cd\s+\S+\s+)", "", seg)
        seg = re.sub(r"^(\w+=\S+\s+)+", "", seg)
        if TEST_RUN_SIG.match(seg) or TEST_RUN_SIG.search(seg[:12]):
            return True
    return False
SCRIPT_EXEC = re.compile(r"(?:python3?|bash|sh)\s+(\S+\.(?:py|sh))")
SHELL_WRITE = re.compile(r"sed\s+-i|>>?\s*\S|git\s+apply|\bpatch\s*<|tee\s+")

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


def verdict_of(observation):
    """Spec section 3 ordering: exit code, then signatures."""
    if observation:
        m = EXIT_CODE.search(observation)
        if m:
            return 'PASS' if int(m.group(1)) == 0 else 'FAIL'
        if FAIL_SIG.search(observation):
            return 'FAIL'
        if PASS_SIG.search(observation):
            return 'PASS'
    return 'UNKNOWN'


def _classify_command(cmd, observation, open_file, created):
    """One shell command -> (kind, detail). SWE-agent's edit/create
    commands mutate the currently-open file (discovery rule)."""
    parts = cmd.strip().split(None, 1)
    head = parts[0] if parts else ''
    if head == 'create':
        target = parts[1].strip() if len(parts) > 1 else open_file
        if target:
            created.add(target)
        return 'EDIT', ('create', target)
    if head == 'edit':
        return 'EDIT', ('modify', open_file)
    if _is_test_run(cmd):
        return 'TESTRUN', (cmd[:80], verdict_of(observation))
    if SHELL_WRITE.search(cmd):
        return 'EDIT', ('shell', cmd[:80])
    m = SCRIPT_EXEC.search(cmd)
    if m and not is_test_file(m.group(1)):
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
        if blocks and blocks[0].strip():
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
                    raw.append([s.step_idx, 'EDIT', ('create', path),
                                '', open_file])
                elif sub in ('str_replace', 'insert'):
                    raw.append([s.step_idx, 'EDIT', ('modify', path),
                                '', open_file])
                else:
                    raw.append([s.step_idx, 'OTHER', f'editor:{sub}',
                                '', open_file])
            elif name in ('Write', 'Edit'):
                pm = PATH_IN_ARGS.search(seg)
                raw.append([s.step_idx, 'EDIT',
                            ('modify', pm.group(1) if pm else None),
                            '', open_file])
            else:  # execute_bash / Bash
                cm = CMD_IN_ARGS.search(seg)
                cmd = cm.group(1).replace('\\"', '"') if cm else text[:200]
                raw.append([s.step_idx, None, cmd, '', open_file])
                pending = len(raw) - 1
        if re.search(r'^\s*submit\s*$', text, re.M):
            end_type = 'submitted'
    events = []
    for idx, kind, detail, obs, ofile in raw:
        if kind is None:
            kind, detail = _classify_command(detail, obs, ofile, created)
        events.append((idx, kind, detail))
    if end_type is None:
        tail = ' '.join((s.text or '') for s in trace.steps[-3:])
        end_type = 'claimed-complete' if COMPLETION_CLAIM.search(tail) \
            else 'exhausted'
    return events, created, end_type


def assess_trace(trace):
    """Spec section 4 predicates over one trace's events."""
    events, created, end_type = events_for(trace)
    cov = {'commands': len(events), 'test_runs': 0, 'edits': 0,
           'unclassified': 0,
           'verdicts': {'PASS': 0, 'FAIL': 0, 'UNKNOWN': 0}}
    edit_idx, runs, vers = [], [], []
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
            edit_idx.append(idx)
            if isinstance(detail, tuple) and detail[0] in ('create',
                                                           'modify'):
                path = detail[1]
                if is_test_file(path):
                    if detail[0] == 'create' or path in created:
                        info_test_edits += 1
                    else:
                        f4 += 1
        elif kind == 'OTHER':
            cov['unclassified'] += 1
    flags = {}
    if edit_idx:
        last_edit = max(edit_idx)
        passes = [i for i, v in runs if v == 'PASS']
        if passes and last_edit > max(passes) and \
                not any(i > last_edit for i, _ in runs):
            flags['F1'] = True
        elif runs and last_edit > max(i for i, _ in runs):
            flags['F2'] = True
        if not any(i > last_edit for i in vers):
            flags['F3'] = True
        if not vers:
            flags['F3a'] = True
    if f4:
        flags['F4'] = f4
    return {'flags': flags, 'end_type': end_type, 'coverage': cov,
            'info_test_edits': info_test_edits,
            'last_edit_step': max(edit_idx) if edit_idx else None,
            'events': events}


def assess_and_flag(trace):
    """Mirror blind_edit.assess_and_flag's shape: (findings, info)."""
    a = assess_trace(trace)
    findings = []
    for name in ('F1', 'F2', 'F3', 'F4'):
        if name in a['flags']:
            if name == 'F4':
                summary = (f"F4: {a['flags']['F4']} edit(s) to "
                           f"pre-existing test files.")
            else:
                summary = (f"{name}: trace ends ({a['end_type']}) with "
                           f"edits after the last verification event; "
                           f"final state unverified in the trace.")
            findings.append(Finding(
                detector='unverified_final_state',
                trace_id=trace.trace_id,
                step_idx=a['last_edit_step'] or 0,
                waste_tokens=0,
                token_basis='n/a',
                summary=summary,
                detail={'flag': name, 'end_type': a['end_type'],
                        'coverage': a['coverage']},
                fix_key='',
                measurable=False,
            ))
    info = {'assessed': True, 'flags': a['flags'],
            'end_type': a['end_type'], 'coverage': a['coverage'],
            'info_test_edits': a['info_test_edits']}
    return findings, info
