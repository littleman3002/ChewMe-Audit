# Worked example provenance

- **Source trajectory:** `iterative__dvc-7734::swe-agent-llama-70b::15930` — public SWE-agent/nebius set
  (`~/workspace/tokenizer-lab/public_traces/nebius_observations.jsonl`).
  Chosen as the clearest loop case in the set (283 identical repeats,
  most in the 73-trajectory set). NOT claimed representative.
- **before.jsonl:** the original 305 tool observations, verbatim.
- **Fix applied:** error-loop dedup — the 283× repeated
  "Usage: edit <start_line>:<end_line>" observation collapsed to its
  first occurrence + a "[repeated 283× — deduplicated]" marker.
- **after.jsonl:** steps 0–21 (verbatim pre-loop context) + the collapsed
  marker + ONE real model step.
- **Re-run (real, not simulated):** deepseek-chat, 2026-10-17, temperature 0.0,
  max_tokens 256. Prompt = pre-loop observations + collapsed marker, asking for
  the next command. Prompt 4,976 tokens (0 cached), completion 103 tokens.
  Cost ≈ $0.0015. The model broke the loop and issued a new investigative
  command instead of repeating the malformed edit a 284th time.
- **What this proves:** the fix lets the agent progress. It does NOT prove the
  agent solves the underlying dvc issue — the re-run was one step.
