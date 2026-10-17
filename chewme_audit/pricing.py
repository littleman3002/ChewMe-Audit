"""Recorded provider price sheets.

Waste spans are priced at the cache-MISS rate: measured on public
benchmark trajectories, waste tokens are 100% cache misses (duplicates
at new positions cannot hit under prefix caching; only the stable
prefix hits). See reports/audit-premise-shrink.md in the lab.

Sheets (recorded 2026-10-17; re-verify before quoting):
  deepseek-flash: miss $0.15/M, hit $0.003/M, out $0.60/M.
    Peak windows 01:00-04:00 and 06:00-10:00 UTC Mon-Fri double prices.
  grok-4.20-0309 (reasoning + non-reasoning): in $1.25/M, cached $0.20/M,
    out $2.50/M.
  claude (Sonnet 5 representative): miss $2.00/M, hit $0.20/M (0.1x),
    out $10.00/M. Writes cost 1.25x (5-min) / 2x (1-hour). Newer
    Sonnet 5.5 / Opus 5.5 read at 0.05x (20x); Fable at 0.025x (40x).
  openai (GPT-5/6 class): miss $4.00/M, hit $0.40/M (90% off), out
    $20.00/M. PROMO caveat: GPT-5.6 Sol $4/$20 runs at least through
    2026-11-21. Older models differ (GPT-4o 50% off, GPT-4.1 75% off).
    Automatic caching, no write surcharge (5.6+ writes 1.25x).
  gemini (3.8 Flash): miss $0.75/M, hit $0.075/M (90% off), out $3.75/M.
    Storage billed separately ($0.50/M tokens/hour) — not in per-request
    pricing here. Argon flagship: 95% off cached (20x) but intro pricing
    expires 2026-12-01.

Unknown provider -> no sheet -> dollars are null (tokens still reported).
"""

SHEETS = {
    "deepseek": {
        "model": "deepseek-flash",
        "miss_per_mtok": 0.15,
        "hit_per_mtok": 0.003,
        "out_per_mtok": 0.60,
        "peak_multiplier": 2.0,
        "peak_windows_utc": ["01:00-04:00", "06:00-10:00 Mon-Fri"],
        "cache_discount": 50.0,
    },
    "deepseek-flash": {
        "model": "deepseek-flash",
        "miss_per_mtok": 0.15,
        "hit_per_mtok": 0.003,
        "out_per_mtok": 0.60,
        "peak_multiplier": 2.0,
        "peak_windows_utc": ["01:00-04:00", "06:00-10:00 Mon-Fri"],
        "cache_discount": 50.0,
    },
    "grok": {
        "model": "grok-4.20-0309",
        "miss_per_mtok": 1.25,
        "hit_per_mtok": 0.20,
        "out_per_mtok": 2.50,
        "peak_multiplier": 1.0,
        "peak_windows_utc": [],
        "cache_discount": 6.25,
    },
    "xai": {
        "model": "grok-4.20-0309",
        "miss_per_mtok": 1.25,
        "hit_per_mtok": 0.20,
        "out_per_mtok": 2.50,
        "peak_multiplier": 1.0,
        "peak_windows_utc": [],
        "cache_discount": 6.25,
    },
    "claude": {
        "model": "claude-sonnet-5",
        "miss_per_mtok": 2.00,
        "hit_per_mtok": 0.20,
        "out_per_mtok": 10.00,
        "peak_multiplier": 1.0,
        "peak_windows_utc": [],
        "cache_discount": 10.0,
    },
    "anthropic": {
        "model": "claude-sonnet-5",
        "miss_per_mtok": 2.00,
        "hit_per_mtok": 0.20,
        "out_per_mtok": 10.00,
        "peak_multiplier": 1.0,
        "peak_windows_utc": [],
        "cache_discount": 10.0,
    },
    "openai": {
        "model": "gpt-5.6-sol",
        "miss_per_mtok": 4.00,
        "hit_per_mtok": 0.40,
        "out_per_mtok": 20.00,
        "peak_multiplier": 1.0,
        "peak_windows_utc": [],
        "cache_discount": 10.0,
    },
    "gemini": {
        "model": "gemini-3.8-flash",
        "miss_per_mtok": 0.75,
        "hit_per_mtok": 0.075,
        "out_per_mtok": 3.75,
        "peak_multiplier": 1.0,
        "peak_windows_utc": [],
        "cache_discount": 10.0,
    },
    "google": {
        "model": "gemini-3.8-flash",
        "miss_per_mtok": 0.75,
        "hit_per_mtok": 0.075,
        "out_per_mtok": 3.75,
        "peak_multiplier": 1.0,
        "peak_windows_utc": [],
        "cache_discount": 10.0,
    },
}


def get_sheet(provider):
    """Return the recorded sheet dict, or None if unknown."""
    return SHEETS.get(provider)


def apply_overrides(overrides):
    """Merge user-supplied pricing overrides over the recorded sheets.

    overrides: {provider: {field: value}} — e.g.
      {"deepseek": {"miss_per_mtok": 0.20, "hit_per_mtok": 0.004}}
    Unknown providers may be added outright. Returns the merged dict
    (a copy; the recorded SHEETS are not mutated).
    """
    import copy
    merged = copy.deepcopy(SHEETS)
    for provider, fields in (overrides or {}).items():
        if not isinstance(fields, dict):
            raise ValueError(f"pricing override for {provider!r} must be an object")
        base = merged.get(provider, {})
        base.update(fields)
        merged[provider] = base
    return merged


def get_sheet_from(sheets, provider):
    return sheets.get(provider)


def waste_dollars(waste_tokens, provider, sheets=None):
    """Price waste tokens at the miss rate. Returns None if no sheet."""
    sheet = (sheets or SHEETS).get(provider)
    if sheet is None:
        return None
    return waste_tokens / 1e6 * sheet["miss_per_mtok"]
