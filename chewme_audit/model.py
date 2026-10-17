"""Trace model: the normalized shape every adapter produces."""

from dataclasses import dataclass, field


@dataclass
class Step:
    """One observation in a trajectory (usually a tool result)."""
    trace_id: str
    step_idx: int
    text: str
    role: str = "tool"          # "tool" | "assistant" | "system" | ...
    tool_name: str = ""         # when known


@dataclass
class Trace:
    trace_id: str
    steps: list = field(default_factory=list)

    def texts(self):
        return [s.text for s in self.steps]
