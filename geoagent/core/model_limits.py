"""Model token limits (context window), looked up from LiteLLM's model map.

LiteLLM ships a maintained map of per-model limits; using it avoids a
hand-kept table that goes stale. Models it does not know (e.g. Apertus on
PublicAI) resolve to ``None``.

Local servers are excluded: their window is whatever the server loaded the
model with (Ollama ``num_ctx``, LM Studio ``-c``, vLLM ``--max-model-len``),
not the model's advertised maximum, and LiteLLM's entries for them can be
wrong (it lists ``ollama/llama3.1`` at 8,192; Llama 3.1 supports 128k).
"""

from __future__ import annotations

from typing import Any

_MAX_TOKEN_KEYS = ("max_tokens", "max_completion_tokens", "max_output_tokens")
_LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio", "vllm"})


def _model_limit(provider: str, model_id: str | None, field: str) -> int | None:
    """Return one limit from LiteLLM's model map, or ``None`` when unknown."""
    if not model_id or provider in _LOCAL_PROVIDERS:
        return None
    try:
        import litellm
    except ImportError:
        return None
    litellm.suppress_debug_info = True  # else it prints a banner per unmapped model
    for key in (f"{provider}/{model_id}", model_id):
        try:
            value = litellm.get_model_info(key).get(field)
        except Exception:  # litellm raises a bare Exception for unmapped models
            continue
        if value:
            return int(value)
    return None


def context_window(provider: str, model_id: str | None) -> int | None:
    """Return the model's maximum input tokens, or ``None`` when unknown."""
    return _model_limit(provider, model_id, "max_input_tokens")


def max_output_tokens(provider: str, model_id: str | None) -> int | None:
    """Return the most tokens the model can generate per request, or ``None``."""
    return _model_limit(provider, model_id, "max_output_tokens")


def configured_max_tokens(model_config: dict[str, Any]) -> int | None:
    """Return the output-token cap a Strands model was built with, if any.

    Providers store it under different keys, either top-level (Anthropic,
    Ollama) or inside ``params`` (OpenAI, LiteLLM, Gemini).
    """
    for source in (model_config, model_config.get("params") or {}):
        for key in _MAX_TOKEN_KEYS:
            if source.get(key) is not None:
                return int(source[key])
    return None
