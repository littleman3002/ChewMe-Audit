"""Detector: pretty-printing waste.

Lexical minify (whitespace outside strings) on JSON-shaped
observations; reports the removable share. Measured on real data:
~0-1.5% (ToolBench), 0% on SWE-agent trajectories — expected to rarely
fire. Reported plainly when it does; silence is also a result.
"""

from .. import counting
from .base import Finding

DETECTOR = "pretty_printing"

_JSON_WS = set(" \t\n\r")


def _is_json_shaped(text):
    """Strict shape check: opener must be followed by legal JSON."""
    it = (ch for ch in text if ch not in _JSON_WS)
    first = next(it, None)
    if first not in ("{", "[", '"'):
        return False
    if first == '"':
        return True
    second = next(it, None)
    if second is None:
        return False
    if first == "{":
        return second in ('"', "}")
    return second in set('{}[]"0123456789-tfn')


def _minify_lexical(text):
    """Strip whitespace outside strings. Returns minified text."""
    out = []
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
                out.append(ch)
            elif ch in _JSON_WS:
                continue
            else:
                out.append(ch)
    return "".join(out)


def run(trace, provider="deepseek"):
    findings = []
    for s in trace.steps:
        if not _is_json_shaped(s.text):
            continue
        mini = _minify_lexical(s.text)
        raw_n, basis = counting.count(s.text, provider)
        mini_n, _ = counting.count(mini, provider)
        saved = raw_n - mini_n
        if saved <= 0:
            continue
        share = saved / raw_n
        if share < 0.02:
            continue  # below noise; the premise test found ~1%, rarely worth flagging
        findings.append(Finding(
            detector=DETECTOR,
            trace_id=trace.trace_id,
            step_idx=s.step_idx,
            waste_tokens=saved,
            token_basis=basis,
            summary=(f"pretty-printed JSON: {share:.1%} removable "
                     f"({saved} tokens)"),
            detail={"removable_share": round(share, 4),
                    "tool_name": s.tool_name},
            fix_key="minify_tool_output",
        ))
    return findings
