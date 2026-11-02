"""model_limits: output-cap discovery and the local-server exclusion."""

import pytest

from geoagent import GeoAgentConfig
from geoagent.core.model import resolve_model
from geoagent.core.model_limits import (
    configured_max_tokens,
    context_window,
    max_output_tokens,
)


@pytest.mark.parametrize("provider", ["ollama", "lmstudio", "vllm"])
def test_local_servers_report_unknown_window(provider):
    # Their window is the server's load setting, not a model-map value.
    assert context_window(provider, "llama3.1") is None


def test_missing_model_is_unknown():
    assert context_window("anthropic", None) is None


@pytest.mark.parametrize(
    "config, expected",
    [
        ({"max_tokens": 4096}, 4096),  # Anthropic / Ollama: top level
        ({"params": {"max_completion_tokens": 2048}}, 2048),  # OpenAI reasoning
        ({"params": {"max_output_tokens": 1024}}, 1024),  # Gemini
        ({"params": {"temperature": 0.2}}, None),  # Auto
    ],
)
def test_configured_max_tokens(config, expected):
    assert configured_max_tokens(config) == expected


@pytest.mark.parametrize("provider", ["ollama", "lmstudio", "vllm"])
def test_local_servers_report_unknown_output_limit(provider):
    assert max_output_tokens(provider, "llama3.1") is None


def test_anthropic_auto_uses_model_maximum(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(
        "geoagent.core.model.max_output_tokens", lambda provider, model: 128_000
    )
    model = resolve_model(GeoAgentConfig(provider="anthropic", model="claude-x"))
    assert model.get_config()["max_tokens"] == 128_000


def test_anthropic_explicit_max_tokens_wins(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    model = resolve_model(
        GeoAgentConfig(provider="anthropic", model="claude-x", max_tokens=4096)
    )
    assert model.get_config()["max_tokens"] == 4096


def test_anthropic_unknown_limit_fails_fast(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(
        "geoagent.core.model.max_output_tokens", lambda provider, model: None
    )
    with pytest.raises(ValueError, match="Max tokens"):
        resolve_model(GeoAgentConfig(provider="anthropic", model="claude-x"))
