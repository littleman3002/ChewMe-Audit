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
- **Correction 2026-10-17 (double-count fix):** the original `--diff` total
  (23,309 tokens) summed two detectors flagging the same 283 repeats
  (`repeated_calls` 10,292 + `near_duplicate_resends` 10,116). Waste totals
  now dedupe: each finding's waste is attributed across the steps it covers
  and each step contributes its max. Corrected: **13,193 tokens ($0.0020)
  → 3,041 ($0.0005), −10,152 (−$0.0015)**. The per-finding receipt
  (`error_loop_dedup`, 10,152 tokens) is unaffected.
- **1M-token calibration (2026-10-17, `traces/calibration_1M/`):** the same
  real loop bytes assembled to exactly 1,000,000 input tokens (27,639
  repeats). Assembled = calibration data, not observed traffic. Audit:
  **998,009 waste tokens (99.80%, $0.1497)** in ~8s; dedupe held (naive
  per-detector sum: 1,992,977). After fix: 3,041 tokens ($0.0005),
  delta −994,968 (−$0.1492). Live deepseek-chat replay with the collapsed
  marker (loop noted 1000× deep): 5,074 prompt / 41 completion tokens,
  0 cached, ≈$0.0014 real billed — the model broke the loop and returned
  to the underlying pickle-protocol issue
  (`grep -rn "pickle" dvc/ --include="*.py" | head -50`).
