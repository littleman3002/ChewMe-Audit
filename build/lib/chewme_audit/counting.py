"""Pluggable token counting with a labeled basis.

Backends, in priority order:
  1. The chewme lab's provider_tokens (DeepSeek v3 local, o200k for xAI),
     when CHEWME_LAB points at the lab directory. This is the only
     backend whose counts may be presented as billed tokens.
  2. tiktoken o200k_base, if installed (xAI's documented proxy).
  3. chars/4 estimate — labeled "chars4-estimate", NEVER priced.

The basis label travels with every count (Tracy's law: a proxy figure
can never be mistaken for a billed figure).
"""

import os

_LAB = os.environ.get("CHEWME_LAB", "")
_provider_tokens = None
_tiktoken_enc = None

BASIS_DEEPSEEK = "deepseek-v3-local"
BASIS_O200K = "o200k-local"
BASIS_ESTIMATE = "chars4-estimate"

# Only these bases may back dollar figures.
PRICEABLE = {BASIS_DEEPSEEK, BASIS_O200K}


def _load_provider_tokens():
    global _provider_tokens
    if _provider_tokens is not None:
        return _provider_tokens
    if not _LAB:
        _provider_tokens = False
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lab_provider_tokens", os.path.join(_LAB, "provider_tokens.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _provider_tokens = mod
        return mod
    except Exception:
        _provider_tokens = False
        return False


def _load_tiktoken():
    global _tiktoken_enc
    if _tiktoken_enc is not None:
        return _tiktoken_enc
    try:
        import tiktoken
        _tiktoken_enc = tiktoken.get_encoding("o200k_base")
        return _tiktoken_enc
    except Exception:
        _tiktoken_enc = False
        return False


def count(text, provider="deepseek"):
    """Return (token_count, basis_label) for text under provider.

    provider: "deepseek" (default) or "xai"/"grok".
    """
    mod = _load_provider_tokens()
    if mod:
        try:
            n, basis = mod.count(provider, text)
            return n, basis
        except Exception:
            pass
    if provider in ("xai", "grok"):
        enc = _load_tiktoken()
        if enc:
            return len(enc.encode(text)), BASIS_O200K
    # DeepSeek has no pip-installable tokenizer; fall through to estimate.
    return max(1, len(text) // 4), BASIS_ESTIMATE


def priceable_basis(basis):
    return basis in PRICEABLE
