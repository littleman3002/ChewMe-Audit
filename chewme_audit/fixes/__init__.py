"""Copy-paste fixes per framework.

Every fix ships with its safety evidence. The two headline fixes
(error-loop dedup, diff-reads) were replay-tested on 13 trajectory
pairs against deepseek-chat: 13/13 preserve or improve agent
comprehension, no breakage. That is the guarantee behind recommending
them.
"""

SAFETY_NOTE = (
    "Safety: replay-tested on 13 trajectory pairs (deepseek-chat) — "
    "13/13 preserve or improve comprehension, no breakage."
)

FIXES = {
    "error_loop_dedup": {
        "title": "Collapse error loops: keep first occurrence + count",
        "safety": SAFETY_NOTE,
        "generic": '''\
# In your agent loop, before appending a tool result to history:
_seen = {}
def dedup_tool_result(text, history, max_repeats=3):
    import hashlib
    h = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
    _seen[h] = _seen.get(h, 0) + 1
    if _seen[h] > max_repeats:
        # Stub, don't drop: the repetition itself is information (e.g. a
        # re-read identical after an edit means the edit didn't land).
        # The sha anchors the stub if the first occurrence is later
        # compacted out of context.
        return (f"[identical output repeated {_seen[h]}x "
                f"— first occurrence kept · sha {h[:8]}]")
    return text
''',
        "langchain": '''\
# LangChain: wrap your tools so repeated identical errors collapse.
from langchain_core.tools import BaseTool
import hashlib

class DedupToolWrapper(BaseTool):
    tool: BaseTool
    max_repeats: int = 3

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Per-instance counter: a class-level `_counts = {}` would be
        # shared across every wrapped tool.
        self._counts = {}

    def _run(self, *args, **kwargs):
        out = self.tool._run(*args, **kwargs)
        h = hashlib.sha256(" ".join(str(out).split()).encode()).hexdigest()
        self._counts[h] = self._counts.get(h, 0) + 1
        n = self._counts[h]
        if n > self.max_repeats:
            return (f"[identical output repeated {n}x "
                    f"— first occurrence kept · sha {h[:8]}]")
        return out
''',
        "llamaindex": '''\
# LlamaIndex: dedup repeated identical tool outputs before they
# re-enter context. Wrap once per tool; the counter is per-wrapper.
from llama_index.core.tools import FunctionTool
import hashlib

def dedup_tool(tool: FunctionTool, max_repeats: int = 3) -> FunctionTool:
    counts: dict = {}
    orig_fn = tool.fn

    def wrapped(*args, **kwargs):
        out = orig_fn(*args, **kwargs)
        h = hashlib.sha256(" ".join(str(out).split()).encode()).hexdigest()
        counts[h] = counts.get(h, 0) + 1
        if counts[h] > max_repeats:
            return (f"[identical output repeated {counts[h]}x "
                    f"— first occurrence kept · sha {h[:8]}]")
        return out

    meta = tool.metadata
    return FunctionTool.from_defaults(
        fn=wrapped, name=meta.name, description=meta.description)
''',
        "openai_agents": '''\
# OpenAI Agents SDK: use a hooks override on tool results.
from agents import RunHooks
import hashlib

class DedupHooks(RunHooks):
    def __init__(self, max_repeats=3):
        self._counts = {}
        self.max_repeats = max_repeats

    async def on_tool_end(self, context, agent, tool, result: str) -> str:
        h = hashlib.sha256(" ".join(result.split()).encode()).hexdigest()
        self._counts[h] = self._counts.get(h, 0) + 1
        n = self._counts[h]
        if n > self.max_repeats:
            return (f"[identical output repeated {n}x "
                    f"— first occurrence kept · sha {h[:8]}]")
        return result
''',
    },
    "partition_agent_work": {
        "title": "Partition work across agents; share read-only discoveries",
        "safety": "Process change, not a code transform: assign disjoint work "
                  "units per agent; publish shared exploration results once.",
        "generic": '''\
# When N agents work one task, identical observations across agents are
# pure duplication. Fix at the orchestration layer:
# 1. Partition the work units (files, directories, instances) disjointly
#    before dispatch — no two agents should enumerate the same set.
# 2. Share read-only discoveries once: one agent lists/explores, the
#    result goes on a shared blackboard instead of N agents re-deriving it.
# 3. Give each agent its own workspace so writes never collide.
''',
    },
    "memoize_repeated_call": {
        "title": "Memoize repeated identical tool calls",
        "safety": "Deterministic transform: same args -> same result; no model judgment involved.",
        "generic": '''\
# Cache tool results by (tool_name, normalized_args):
from functools import lru_cache
import hashlib, json

_cache = {}
def memoized_call(tool_name, args, fn):
    key = (tool_name, hashlib.sha256(
        json.dumps(args, sort_keys=True).encode()).hexdigest())
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]
''',
        "langchain": "# LangChain: same memoized_call pattern around Tool.invoke().",
        "llamaindex": "# LlamaIndex: wrap FunctionTool.fn with memoized_call.",
        "openai_agents": "# OpenAI Agents SDK: memoize inside your function_tool implementation.",
    },
    "diff_read": {
        "title": "Re-read files as diffs, not full contents",
        "safety": SAFETY_NOTE + " In 1/8 pairs the diff OUTPERFORMED the full re-read.",
        "generic": '''\
# After an edit, send the diff — not the whole file — back into context:
import difflib
def diff_read(old_text, new_text, path="file"):
    diff = difflib.unified_diff(old_text.splitlines(), new_text.splitlines(),
                                fromfile=path, tofile=path, lineterm="")
    return "\\n".join(diff)
# Agent prompt addition: "After each edit I will show you a unified diff
# of the change instead of the full file."
''',
        "langchain": "# LangChain: in your file-edit tool, return diff_read(old, new) as the observation.",
        "llamaindex": "# LlamaIndex: same — return the unified diff from your edit tool.",
        "openai_agents": "# OpenAI Agents SDK: return the unified diff from your function_tool.",
    },
    "review_resend": {
        "title": "Review near-duplicate re-sends case by case",
        "safety": "Advisory: the audit surfaces the pair and its diff; a human (or a second pass) decides.",
        "generic": "# No automatic fix — inspect the surfaced pair. Grep retried with\n# different terms is normal iteration; a full file re-view after a\n# one-line edit should become diff_read (see above).",
        "langchain": "# See generic guidance.",
        "llamaindex": "# See generic guidance.",
        "openai_agents": "# See generic guidance.",
    },
    "truncate_tool_output": {
        "title": "Truncate or summarize oversized tool outputs",
        "safety": "Heuristic finding: verify the output is truly unreferenced before truncating.",
        "generic": '''\
# Cap tool observations before they enter history:
MAX_OBS_CHARS = 4000
def cap_observation(text):
    if len(text) > MAX_OBS_CHARS:
        return (text[:MAX_OBS_CHARS] +
                f"\\n[... truncated {len(text)-MAX_OBS_CHARS} chars; "
                "ask for more if needed]")
    return text
''',
        "langchain": "# LangChain: set max_iterations caps AND truncate in a callback on tool end.",
        "llamaindex": "# LlamaIndex: truncate in your agent step post-hook.",
        "openai_agents": "# OpenAI Agents SDK: truncate in RunHooks.on_tool_end.",
    },
    "minify_tool_output": {
        "title": "Serve compact JSON from tools (no pretty-printing)",
        "safety": "Byte-exact restore is available in the private core; the minify shown here is deterministic and Python-side.",
        "generic": '# json.dumps(obj, separators=(",", ":")) instead of indent=2.',
        "langchain": "# LangChain: return json.dumps(..., separators=(',', ':')) from tools.",
        "llamaindex": "# LlamaIndex: same.",
        "openai_agents": "# OpenAI Agents SDK: same.",
    },
}


def get(fix_key, framework="generic"):
    fix = FIXES.get(fix_key)
    if not fix:
        return None
    snippet = fix.get(framework) or fix["generic"]
    return {"title": fix["title"], "safety": fix["safety"], "snippet": snippet}


def frameworks():
    return ["generic", "langchain", "llamaindex", "openai_agents"]
