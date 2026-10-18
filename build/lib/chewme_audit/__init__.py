"""chewme-audit: cost-audit reports for AI agent traces.

Reads a team's agent traces and reports every fixable waste pattern,
its measured dollar cost, and a concrete copy-paste fix.

Honest scope (standing): benchmark-trajectory numbers stay labeled as
such; no claim beyond what was measured. Token counting labels its
basis on every figure; where no provider tokenizer exists, figures are
labeled as estimates, never priced.
"""

__version__ = "0.1.0"
