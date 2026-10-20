---
name: chewme-audit
description: Audit Claude Code session transcripts for wasted tokens. Use when the user asks where their tokens went, why a session was expensive, or wants a cost/waste breakdown of a past session. Runs the chewme-audit CLI on transcript JSONL and explains the findings.
license: MIT
---

# Chewme-Audit skill

chewme-audit is a CLI that reads agent traces and reports where tokens
were wasted, priced per provider, with copy-paste fixes for each waste
pattern. It runs locally: no API calls, nothing uploaded.

## When to use

- The user asks how many tokens a session used, where they went, or why
  a session was expensive.
- The user wants a cost breakdown or waste report for a past session.

It audits session transcripts on disk — completed sessions, or the
current session's transcript so far (incomplete until the session ends).

## How to run an audit

1. **Find the transcript.** Session transcripts live under
   `~/.claude/projects/`:
   ```
   ls -t ~/.claude/projects/*/*.jsonl | head -20
   ```
   Use the most recent one, or the one the user names.

2. **Make sure the CLI is installed:**
   ```
   pip install chewme-audit
   ```

3. **Run the audit.** Claude Code sessions bill on Claude pricing:
   ```
   chewme-audit <transcript> --format claude-code --provider claude
   ```

4. **Summarize the report for the user:**
   - Headline: waste tokens and share of input — lead with these.
   - Prioritized findings: the top 2–3 by waste, in plain language.
   - Recommended fixes: offer them; do not change the user's code
     without being asked.
   - Honesty labels: every dollar figure is **estimated** unless the
     user provides API logs. On flat-rate subscription plans, waste
     tokens and waste share are the meaningful numbers ("35% of session
     I/O was pure re-verification"); dollar figures are illustrative
     there, and the report labels them as such.

## What it finds

Repeated identical tool calls (agents stuck in error loops),
near-duplicate re-sends (full file re-reads after one-line edits), and
oversized tool outputs nothing later references. Each finding names the
exact call, with a copy-paste fix and its safety evidence.
