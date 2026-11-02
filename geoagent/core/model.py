"""Resolve Strands :class:`~strands.models.model.Model` instances from config."""

from __future__ import annotations

import os
from typing import Any

from geoagent.core.config import GeoAgentConfig, ProviderName
from geoagent.core.model_limits import max_output_tokens


def _openai_token_params(model_id: str, max_tokens: int | None) -> dict[str, int]:
    """Return the token-limit parameter supported by the OpenAI model family."""
    if max_tokens is None:
        return {}
    normalized = str(model_id or "").lower()
    completion_prefixes = (
        "gpt-5",
        "gpt-4.1",
        "gpt-4o",
        "chatgpt-4o",
        "o1",
        "o3",
        "o4",
    )
    if normalized.startswith(completion_prefixes):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def _model_uses_default_temperature_only(model_id: str) -> bool:
    """Return True for model families that reject explicit temperature values."""
    normalized = str(model_id or "").lower()
    return normalized.startswith(
        (
            "gpt-5",
            "openai/gpt-5",
            "o1",
            "openai/o1",
            "o3",
            "openai/o3",
            "o4",
            "openai/o4",
        )
    )


def _token_param(name: str, max_tokens: int | None) -> dict[str, int]:
    """Return a provider token parameter only when explicitly configured."""
    if max_tokens is None:
        return {}
    return {name: int(max_tokens)}


def resolve_model(config: GeoAgentConfig | None = None, **overrides: Any) -> Any:
    """Build a Strands model from :class:`GeoAgentConfig` or kwargs overrides.

    Raises:
        ImportError: When optional provider client libraries are missing.
        ValueError: When configuration is inconsistent.
    """
    cfg = (
        config.model_copy(update=overrides)
        if config is not None
        else GeoAgentConfig(**overrides)
    )
    provider: ProviderName = cfg.provider
    if cfg.max_tokens is None:
        # "Auto" means the model's own output maximum when it is known. A high
        # max_tokens costs nothing extra: providers bill and rate-limit the tokens
        # actually generated. Unknown models keep the provider default.
        cfg = cfg.model_copy(
            update={"max_tokens": max_output_tokens(provider, cfg.model)}
        )
    if provider == "bedrock":
        from strands.models.bedrock import BedrockModel

        model_id = cfg.model or os.environ.get(
            "BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6"
        )
        params = {"temperature": cfg.temperature}
        params.update(_token_param("max_tokens", cfg.max_tokens))
        return BedrockModel(model_id=model_id, params=params)

    if provider == "openai":
        from strands.models.openai import OpenAIModel

        model_id = cfg.model or os.environ.get("OPENAI_MODEL", "gpt-5.5")
        client_args = dict(cfg.client_args)
        params = {}
        if not _model_uses_default_temperature_only(model_id):
            params["temperature"] = cfg.temperature
        params.update(_openai_token_params(model_id, cfg.max_tokens))
        return OpenAIModel(
            client_args=client_args or None,
            model_id=model_id,
            params=params,
        )

    if provider == "openai-codex":
        try:
            from strands.models.openai_responses import OpenAIResponsesModel
        except ImportError as exc:
            raise ImportError(
                "The openai-codex provider could not import the OpenAI Responses "
                "API model from strands. This usually means the installed openai "
                "package is too old, because the Responses API requires the "
                "openai package version 2.0 or newer. Upgrade with `pip install "
                "-U 'GeoAgent[openai]'` (or `pip install -U 'openai>=2'`) and "
                "restart QGIS or your Python session. To stay on openai 1.x, "
                "switch the provider to 'openai', which uses the Chat Completions "
                "API instead. If openai 2.x is already installed, the original "
                f"error below has the real cause. Original error: {exc}"
            ) from exc

        model_id = cfg.model or os.environ.get("OPENAI_CODEX_MODEL", "gpt-5.5")
        client_args = dict(cfg.client_args)
        api_key = client_args.get("api_key") or os.environ.get(
            "OPENAI_CODEX_ACCESS_TOKEN"
        )
        if not api_key:
            try:
                from geoagent.core.openai_codex import ensure_openai_codex_environment

                ensure_openai_codex_environment()
                api_key = os.environ.get("OPENAI_CODEX_ACCESS_TOKEN")
            except RuntimeError:
                api_key = ""
        base_url = (
            client_args.get("base_url")
            or cfg.openai_codex_base_url
            or os.environ.get("OPENAI_CODEX_BASE_URL")
            or "https://chatgpt.com/backend-api/codex"
        )
        account_id = os.environ.get("OPENAI_CODEX_ACCOUNT_ID", "").strip()
        if not api_key:
            raise ValueError(
                "OpenAI Codex provider requires a ChatGPT OAuth access token. "
                "Run `geoagent codex login`, call `geoagent.login_openai_codex()`, "
                "or set OPENAI_CODEX_ACCESS_TOKEN."
            )
        client_args["api_key"] = api_key
        client_args["base_url"] = base_url
        default_headers = dict(client_args.get("default_headers") or {})
        default_headers.setdefault("User-Agent", "codex-cli")
        if account_id:
            default_headers["ChatGPT-Account-Id"] = account_id
        client_args["default_headers"] = default_headers
        return OpenAIResponsesModel(
            client_args=client_args,
            model_id=model_id,
            params={},
        )

    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        model_id = cfg.model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        # The Anthropic API requires max_tokens; there is no provider default.
        max_tokens = cfg.max_tokens or max_output_tokens(provider, model_id)
        if max_tokens is None:
            raise ValueError(
                f"Unknown output limit for Anthropic model {model_id!r}: "
                "set Max tokens in Settings."
            )
        return AnthropicModel(
            client_args=dict(cfg.client_args) or None,
            model_id=model_id,
            max_tokens=int(max_tokens),
            params={"temperature": cfg.temperature},
        )

    if provider == "gemini":
        from strands.models.gemini import GeminiModel

        model_id = cfg.model or os.environ.get(
            "GEMINI_MODEL",
            os.environ.get("GOOGLE_MODEL", "gemini-3.1-pro-preview"),
        )
        client_args = dict(cfg.client_args)
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if api_key and "api_key" not in client_args:
            client_args["api_key"] = api_key
        params = {"temperature": cfg.temperature}
        params.update(_token_param("max_output_tokens", cfg.max_tokens))
        return GeminiModel(
            client_args=client_args or None,
            model_id=model_id,
            params=params,
        )

    if provider == "ollama":
        from strands.models.ollama import OllamaModel

        host = cfg.ollama_host or os.environ.get(
            "OLLAMA_HOST", "http://127.0.0.1:11434"
        )
        model_id = cfg.model or os.environ.get("OLLAMA_MODEL", "qwen3.5:4b")
        kwargs = {}
        if cfg.max_tokens is not None:
            kwargs["max_tokens"] = int(cfg.max_tokens)
        return OllamaModel(
            host,
            model_id=model_id,
            temperature=cfg.temperature,
            **kwargs,
        )

    if provider == "litellm":
        from strands.models.litellm import LiteLLMModel

        model_id = cfg.model or os.environ.get("LITELLM_MODEL", "openai/gpt-5.5")
        client_args = dict(cfg.client_args)
        api_key = os.environ.get("LITELLM_API_KEY")
        if api_key and "api_key" not in client_args:
            client_args["api_key"] = api_key
        base_url = cfg.litellm_base_url or os.environ.get("LITELLM_BASE_URL")
        if base_url and "base_url" not in client_args:
            client_args["base_url"] = base_url
        params = _token_param("max_tokens", cfg.max_tokens)
        if not _model_uses_default_temperature_only(model_id):
            params["temperature"] = cfg.temperature
        return LiteLLMModel(
            client_args=client_args or None,
            model_id=model_id,
            params=params,
        )

    if provider == "lmstudio":
        from strands.models.litellm import LiteLLMModel

        from geoagent.core.lmstudio import (
            DEFAULT_BASE_URL,
            PLACEHOLDER_API_KEY,
            ensure_model,
        )

        # The user picks a plain model key ("qwen2.5-7b-instruct"); LiteLLM needs an
        # "openai/" routing prefix to know which dialect to speak. Accept either and
        # normalize, so a pasted LITELLM_MODEL value does not become "openai/openai/...".
        #
        # Blank is the *normal* case from the plugin dropdown and means "whatever LM
        # Studio has loaded" -- not a hardcoded default, which would fail for every user
        # who happens to have a different model downloaded.
        model_key = (cfg.model or "").strip()
        if model_key.startswith("openai/"):
            model_key = model_key[len("openai/") :]

        # Deliberately NOT cfg.litellm_base_url: this provider starts a *local* server,
        # so inheriting someone's remote LiteLLM proxy URL would load a model on this
        # machine while sending requests to a different host.
        base_url = cfg.lmstudio_base_url or DEFAULT_BASE_URL

        # Start the server and load the model if needed. Side-effectful, deliberately:
        # it mirrors the openai-codex branch above, which calls
        # ensure_openai_codex_environment() here for the same reason -- the point of
        # picking this provider is "make the local model work without me setting it up".
        # Callers construct agents on a worker thread (the plugin's ChatWorker), so the
        # seconds this can take do not block a GUI thread.
        #
        # Take the model id back from ensure_model rather than re-deriving it: when
        # model_key was blank, ensure_model is the thing that decided which model this is.
        prepared = ensure_model(model_key or None, base_url=base_url)

        client_args = dict(cfg.client_args)
        client_args.setdefault("api_key", PLACEHOLDER_API_KEY)
        client_args.setdefault("base_url", base_url)

        model_id = str(prepared.model)
        params = _token_param("max_tokens", cfg.max_tokens)
        if not _model_uses_default_temperature_only(model_id):
            params["temperature"] = cfg.temperature
        return LiteLLMModel(
            client_args=client_args,
            model_id=model_id,
            params=params,
        )

    if provider == "openrouter":
        from strands.models.openai import OpenAIModel

        model_id = cfg.model or os.environ.get(
            "OPENROUTER_MODEL", "deepseek/deepseek-chat"
        )
        client_args = dict(cfg.client_args)
        api_key = client_args.get("api_key") or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenRouter provider requires an API key. Set OPENROUTER_API_KEY "
                "or pass client_args={'api_key': ...}."
            )
        client_args["api_key"] = api_key
        base_url = (
            client_args.get("base_url")
            or cfg.openrouter_base_url
            or os.environ.get("OPENROUTER_BASE_URL")
            or "https://openrouter.ai/api/v1"
        )
        client_args["base_url"] = base_url
        params = _token_param("max_tokens", cfg.max_tokens)
        if not _model_uses_default_temperature_only(model_id):
            params["temperature"] = cfg.temperature
        return OpenAIModel(
            client_args=client_args,
            model_id=model_id,
            params=params,
        )

    if provider == "apertus":
        from geoagent.core.apertus import DEFAULT_BASE_URL, DEFAULT_MODEL, ApertusModel

        model_id = cfg.model or os.environ.get("APERTUS_MODEL", DEFAULT_MODEL)
        client_args = dict(cfg.client_args)
        api_key = client_args.get("api_key") or os.environ.get("APERTUS_API_KEY")
        if not api_key:
            raise ValueError(
                "Apertus provider requires an API key. Set APERTUS_API_KEY "
                "or pass client_args={'api_key': ...}."
            )
        client_args["api_key"] = api_key
        client_args["base_url"] = (
            client_args.get("base_url")
            or cfg.apertus_base_url
            or os.environ.get("APERTUS_BASE_URL")
            or DEFAULT_BASE_URL
        )
        params = {"temperature": cfg.temperature}
        params.update(_token_param("max_tokens", cfg.max_tokens))
        return ApertusModel(client_args=client_args, model_id=model_id, params=params)
    if provider == "requesty":
        from strands.models.openai import OpenAIModel

        model_id = cfg.model or os.environ.get("REQUESTY_MODEL", "openai/gpt-4o-mini")
        client_args = dict(cfg.client_args)
        api_key = client_args.get("api_key") or os.environ.get("REQUESTY_API_KEY")
        if not api_key:
            raise ValueError(
                "Requesty provider requires an API key. Set REQUESTY_API_KEY "
                "or pass client_args={'api_key': ...}."
            )
        client_args["api_key"] = api_key
        base_url = (
            client_args.get("base_url")
            or cfg.requesty_base_url
            or os.environ.get("REQUESTY_BASE_URL")
            or "https://router.requesty.ai/v1"
        )
        client_args["base_url"] = base_url
        params = _token_param("max_tokens", cfg.max_tokens)
        if not _model_uses_default_temperature_only(model_id):
            params["temperature"] = cfg.temperature
        return OpenAIModel(
            client_args=client_args,
            model_id=model_id,
            params=params,
        )

    if provider == "openai-compatible":
        from strands.models.openai import OpenAIModel

        client_args = dict(cfg.client_args)
        base_url = (
            client_args.get("base_url")
            or cfg.openai_compatible_base_url
            or os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
        )
        if not base_url:
            raise ValueError(
                "The openai-compatible provider requires the base URL of an "
                "OpenAI-compatible server, for example http://localhost:8000/v1. "
                "Set OPENAI_COMPATIBLE_BASE_URL, pass "
                "openai_compatible_base_url=..., or configure it in OpenGeoAgent "
                "Settings."
            )
        model_id = cfg.model or os.environ.get("OPENAI_COMPATIBLE_MODEL")
        if not model_id:
            raise ValueError(
                "The openai-compatible provider requires a model id, because a "
                "generic endpoint has no default. Pass model=..., set "
                "OPENAI_COMPATIBLE_MODEL, or configure the model in OpenGeoAgent "
                "Settings."
            )
        client_args["base_url"] = base_url
        # Local servers usually ignore the key, but the OpenAI SDK rejects an
        # empty one, so fall back to the same placeholder the vLLM path uses.
        client_args["api_key"] = (
            client_args.get("api_key")
            or os.environ.get("OPENAI_COMPATIBLE_API_KEY")
            or "EMPTY"
        )
        params = _token_param("max_tokens", cfg.max_tokens)
        if not _model_uses_default_temperature_only(model_id):
            params["temperature"] = cfg.temperature
        return OpenAIModel(
            client_args=client_args,
            model_id=model_id,
            params=params,
        )

    if provider == "vllm":
        model_id = cfg.model or os.environ.get("VLLM_MODEL_ID")
        if not model_id:
            raise ValueError(
                "vLLM provider requires a model id. Pass model=..., set "
                "VLLM_MODEL_ID, or configure the model in OpenGeoAgent settings."
            )
        client_args = dict(cfg.client_args)
        base_url = (
            cfg.vllm_base_url
            or client_args.pop("base_url", None)
            or os.environ.get("VLLM_BASE_URL")
            or "http://localhost:8000/v1"
        )
        api_key = client_args.pop("api_key", None) or os.environ.get(
            "VLLM_API_KEY", "EMPTY"
        )
        params = {"temperature": cfg.temperature}
        params.update(_token_param("max_tokens", cfg.max_tokens))
        try:
            from strands_vllm import VLLMModel
        except ImportError:
            # strands-vllm pins openai<2.0, so it is not in the default install
            # (openai>=2.0 is required). vLLM serves the OpenAI Chat Completions
            # API at /v1, so the stock OpenAI model reaches it just as well.
            from strands.models.openai import OpenAIModel

            return OpenAIModel(
                client_args={**client_args, "base_url": base_url, "api_key": api_key},
                model_id=model_id,
                params=params,
            )
        return VLLMModel(
            base_url=base_url,
            model_id=model_id,
            api_key=api_key,
            params=params,
            **client_args,
        )

    raise ValueError(f"Unknown provider: {provider}")


def get_default_model() -> Any:
    """Default model using environment-derived provider selection."""
    return resolve_model(GeoAgentConfig())


def get_llm(**kwargs: Any) -> Any:
    """Build a model (alias for :func:`resolve_model` with a fresh config)."""
    if not kwargs:
        return get_default_model()
    return resolve_model(GeoAgentConfig.model_validate(kwargs))
