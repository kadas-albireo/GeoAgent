"""Tests for the LM Studio provider and its lifecycle helper.

Covers the two mistakes that were actually made while building this, since both were
silent and neither would fail loudly at runtime:

1. ``--gpu max`` looks like the safe choice but overrides LM Studio's offload planner and
   makes borderline loads fail. The flag must stay off by default.
2. ``lmstudio`` must not inherit ``litellm_base_url``. This provider starts a *local*
   server, so following someone's remote LiteLLM proxy would load a model here and send
   requests elsewhere.

No LM Studio installation is required: the CLI and HTTP layers are faked.
"""

from __future__ import annotations

import ast
import sys
import types
import typing
from pathlib import Path

import pytest

from geoagent.core import lmstudio
from geoagent.core.config import GeoAgentConfig, ProviderName

REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_fake_litellm(monkeypatch):
    """Install a fake Strands LiteLLM module that records constructor kwargs."""

    class FakeLiteLLMModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module = types.ModuleType("strands.models.litellm")
    module.LiteLLMModel = FakeLiteLLMModel
    monkeypatch.setitem(sys.modules, "strands", types.ModuleType("strands"))
    monkeypatch.setitem(
        sys.modules, "strands.models", types.ModuleType("strands.models")
    )
    monkeypatch.setitem(sys.modules, "strands.models.litellm", module)
    return FakeLiteLLMModel


# Config


def test_lmstudio_config_is_valid() -> None:
    """Verify that LM Studio is accepted as a configured provider."""
    cfg = GeoAgentConfig(provider="lmstudio", model="qwen2.5-7b-instruct")

    assert cfg.provider == "lmstudio"
    assert cfg.model == "qwen2.5-7b-instruct"


def test_lmstudio_is_a_known_provider_name() -> None:
    """The Literal must include lmstudio, or GeoAgentConfig rejects it."""
    assert "lmstudio" in typing.get_args(ProviderName)


# sanitize / paths


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("qwen2.5-7b-instruct", "qwen2.5-7b-instruct"),
        ("openai/qwen2.5-7b-instruct", "openai-qwen2.5-7b-instruct"),
        ("claude sonnet 4.6", "claude-sonnet-4.6"),
        ("///", "unknown-model"),
    ],
)
def test_sanitize_model_name(raw: str, expected: str) -> None:
    """Model ids become filesystem-safe without collapsing to nothing."""
    from local_agent.telemetry.tracker import sanitize_model_name

    assert sanitize_model_name(raw) == expected


# load_model flags


def test_load_model_does_not_pass_gpu_max_by_default(monkeypatch) -> None:
    """Regression: ``--gpu max`` must not be sent unless explicitly requested.

    It overrides LM Studio's automatic offload planning and makes a borderline load fail
    with an opaque error. Verified on a 6 GiB RTX 4050: `-c 32768 --gpu max` failed, the
    same load without the flag succeeded.
    """
    captured: dict[str, list[str]] = {}

    def fake_run(args, *, timeout=120.0):
        captured["args"] = args
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lmstudio, "_run", fake_run)
    lmstudio.load_model("qwen2.5-7b-instruct", context_length=32768)

    assert "--gpu" not in captured["args"]
    assert "--context-length" in captured["args"]
    assert "32768" in captured["args"]


def test_load_model_passes_gpu_when_explicitly_requested(monkeypatch) -> None:
    """An explicit gpu ratio is still honoured for callers who want it."""
    captured: dict[str, list[str]] = {}

    def fake_run(args, *, timeout=120.0):
        captured["args"] = args
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lmstudio, "_run", fake_run)
    lmstudio.load_model("m", gpu="0.5")

    assert "--gpu" in captured["args"]
    assert "0.5" in captured["args"]


def test_load_model_raises_with_guidance_on_failure(monkeypatch) -> None:
    """A failed load explains the likely cause rather than surfacing raw CLI noise."""

    def fake_run(args, *, timeout=120.0):
        return types.SimpleNamespace(
            returncode=1, stdout="", stderr="Error loading model"
        )

    monkeypatch.setattr(lmstudio, "_run", fake_run)
    with pytest.raises(lmstudio.LMStudioError, match="context_length"):
        lmstudio.load_model("m", context_length=32768)


# ensure_model gating


def test_ensure_model_rejects_a_model_without_tool_support(monkeypatch) -> None:
    """Fail fast: an agent on a non-tool model can only talk, never act."""
    monkeypatch.setattr(lmstudio, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(
        lmstudio,
        "model_info",
        lambda *a, **k: {"id": "m", "state": "loaded", "capabilities": []},
    )
    with pytest.raises(lmstudio.LMStudioError, match="tool calling"):
        lmstudio.ensure_model("m")


def test_ensure_model_is_a_noop_when_already_loaded(monkeypatch) -> None:
    """Idempotent: safe to call on every agent construction."""
    monkeypatch.setattr(lmstudio, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(
        lmstudio,
        "model_info",
        lambda *a, **k: {
            "id": "m",
            "state": "loaded",
            "capabilities": ["tool_use"],
            "max_context_length": 32768,
            "loaded_context_length": 32768,
        },
    )

    def fail(*a, **k):
        raise AssertionError("load_model must not be called when already loaded")

    monkeypatch.setattr(lmstudio, "load_model", fail)
    config = lmstudio.ensure_model("m")

    assert config.provider == "litellm"
    assert config.model == "openai/m"


def test_ensure_model_reloads_when_context_is_too_small(monkeypatch) -> None:
    """LM Studio's 8192 default cannot fit the ~10.6k KADAS tool schemas."""
    monkeypatch.setattr(lmstudio, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(
        lmstudio,
        "model_info",
        lambda *a, **k: {
            "id": "m",
            "state": "loaded",
            "capabilities": ["tool_use"],
            "max_context_length": 32768,
            "loaded_context_length": 8192,
        },
    )
    calls: dict[str, int] = {}
    monkeypatch.setattr(lmstudio, "unload_model", lambda *a, **k: None)
    monkeypatch.setattr(
        lmstudio,
        "load_model",
        lambda key, **kw: calls.update(context=kw.get("context_length")),
    )
    lmstudio.ensure_model("m")

    assert calls["context"] == 32768


def _stub_ensure_model(monkeypatch, record: dict | None = None):
    """Stand in for ensure_model(), echoing back the key resolve_model() passed.

    It must return a config, not None: resolve_model() takes the final model id from the
    return value precisely so that an auto-detected key (model_key=None) reaches LiteLLM.
    """

    def ensure(model_key=None, **kwargs):
        if record is not None:
            record.update(base_url=kwargs.get("base_url", ""), model_key=model_key)
        return lmstudio.config_for(model_key or "auto-detected-model")

    monkeypatch.setattr(lmstudio, "ensure_model", ensure)
    return ensure


# resolve_model wiring


def test_resolve_model_normalizes_the_openai_prefix(monkeypatch) -> None:
    """Accept both 'qwen...' and 'openai/qwen...' without double-prefixing."""
    fake = _install_fake_litellm(monkeypatch)
    _stub_ensure_model(monkeypatch)
    from geoagent.core.model import resolve_model

    for given in ("qwen2.5-7b-instruct", "openai/qwen2.5-7b-instruct"):
        model = resolve_model(GeoAgentConfig(provider="lmstudio", model=given))
        assert isinstance(model, fake)
        assert model.kwargs["model_id"] == "openai/qwen2.5-7b-instruct"


def test_resolve_model_ignores_litellm_base_url(monkeypatch) -> None:
    """Regression: lmstudio must not follow a remote LiteLLM proxy.

    It starts a local server; inheriting litellm_base_url would load a model here while
    talking to another host.
    """
    _install_fake_litellm(monkeypatch)
    seen: dict[str, str] = {}
    _stub_ensure_model(monkeypatch, record=seen)
    from geoagent.core.model import resolve_model

    model = resolve_model(
        GeoAgentConfig(
            provider="lmstudio",
            model="m",
            litellm_base_url="https://remote-proxy.example.com/v1",
        )
    )

    assert seen["base_url"] == lmstudio.DEFAULT_BASE_URL
    assert model.kwargs["client_args"]["base_url"] == lmstudio.DEFAULT_BASE_URL


def test_resolve_model_honours_explicit_lmstudio_base_url(monkeypatch) -> None:
    """A deliberate lmstudio_base_url is used (e.g. a non-default port)."""
    _install_fake_litellm(monkeypatch)
    _stub_ensure_model(monkeypatch)
    from geoagent.core.model import resolve_model

    model = resolve_model(
        GeoAgentConfig(
            provider="lmstudio",
            model="m",
            lmstudio_base_url="http://localhost:9999/v1",
        )
    )

    assert model.kwargs["client_args"]["base_url"] == "http://localhost:9999/v1"


# Plugin/core agreement


def _plugin_constant(name: str):
    """Read a constant out of chat_dock.py without importing it (needs qgis/PyQt)."""
    source = REPO_ROOT / "qgis_geoagent" / "open_geoagent" / "dialogs" / "chat_dock.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in chat_dock.py")


def test_plugin_provider_combo_matches_geoagent_providers() -> None:
    """Every provider the dock offers must be one resolve_model() accepts.

    The plugin's PROVIDERS list and geoagent's ProviderName are declared in different
    packages, so they can drift silently: the combo would offer a provider that explodes
    at chat time. The plugin's own suite cannot catch this locally (it needs PyQt6 and
    skips), hence reading the constant via AST from here.
    """
    providers = set(_plugin_constant("PROVIDERS"))
    valid = set(typing.get_args(ProviderName))

    assert providers - valid == set(), "combo offers unknown provider(s)"
    assert valid - providers == set(), "provider exists but is not offered in the combo"


def test_every_offered_provider_has_a_default_model_entry() -> None:
    """A provider missing from DEFAULT_MODELS is a KeyError-shaped gap in the UI."""
    providers = _plugin_constant("PROVIDERS")
    defaults = _plugin_constant("DEFAULT_MODELS")

    assert [p for p in providers if p not in defaults] == []


def test_self_configuring_hints_cover_real_providers() -> None:
    """The dock's hint map must not name a provider the combo does not offer."""
    providers = set(_plugin_constant("PROVIDERS"))
    hints = _plugin_constant("SELF_CONFIGURING_PROVIDERS")

    assert set(hints) <= providers


def test_self_configuring_providers_default_to_a_blank_model() -> None:
    """Blank is the point: the provider detects the model, the user types nothing.

    A hardcoded default here would be wrong for anyone whose LM Studio holds a different
    model, which is the normal case.
    """
    defaults = _plugin_constant("DEFAULT_MODELS")

    assert defaults["lmstudio"] == ""
    assert defaults["eth-cluster"] == ""


def test_a_blank_model_auto_detects_the_loaded_lmstudio_model(monkeypatch) -> None:
    """The dropdown path: provider=lmstudio, model blank -> whatever is loaded."""
    fake = _install_fake_litellm(monkeypatch)
    seen: dict[str, str] = {}
    _stub_ensure_model(monkeypatch, record=seen)
    from geoagent.core.model import resolve_model

    model = resolve_model(GeoAgentConfig(provider="lmstudio", model=None))

    assert seen["model_key"] is None, "blank model must reach ensure_model as None"
    assert isinstance(model, fake)
    assert model.kwargs["model_id"] == "openai/auto-detected-model"


# Auto-detection of the loaded model


def _fake_listing(monkeypatch, entries):
    monkeypatch.setattr(lmstudio, "list_models", lambda *a, **k: entries)


def test_loaded_model_prefers_the_already_loaded_one(monkeypatch) -> None:
    """A loaded model costs nothing to use; any other choice pays a multi-second load."""
    _fake_listing(
        monkeypatch,
        [
            {
                "id": "downloaded",
                "type": "llm",
                "state": "not-loaded",
                "capabilities": ["tool_use"],
            },
            {
                "id": "in-memory",
                "type": "llm",
                "state": "loaded",
                "capabilities": ["tool_use"],
            },
        ],
    )

    assert lmstudio.loaded_model() == "in-memory"


def test_loaded_model_skips_a_model_without_tool_support(monkeypatch) -> None:
    """Auto-picking a non-tool model hands the user an agent that can only talk."""
    _fake_listing(
        monkeypatch,
        [
            {"id": "chatty", "type": "llm", "state": "loaded", "capabilities": []},
            {
                "id": "useful",
                "type": "llm",
                "state": "not-loaded",
                "capabilities": ["tool_use"],
            },
        ],
    )

    assert lmstudio.loaded_model() == "useful"


def test_loaded_model_ignores_non_llm_entries(monkeypatch) -> None:
    """Embedding models are listed too, and cannot drive an agent."""
    _fake_listing(
        monkeypatch,
        [{"id": "nomic-embed", "type": "embeddings", "state": "loaded"}],
    )

    assert lmstudio.loaded_model() is None


def test_loaded_model_returns_none_when_lmstudio_is_unreachable(monkeypatch) -> None:
    """Callers raise with the listing; this must not explode on a dead server."""

    def boom(*a, **k):
        raise lmstudio.LMStudioError("no server")

    monkeypatch.setattr(lmstudio, "list_models", boom)

    assert lmstudio.loaded_model() is None


def test_ensure_model_auto_detects_when_no_key_is_given(monkeypatch) -> None:
    monkeypatch.setattr(lmstudio, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(lmstudio, "loaded_model", lambda *a, **k: "picked")
    monkeypatch.setattr(
        lmstudio,
        "model_info",
        lambda *a, **k: {
            "id": "picked",
            "state": "loaded",
            "capabilities": ["tool_use"],
            "max_context_length": 32768,
            "loaded_context_length": 32768,
        },
    )
    config = lmstudio.ensure_model()

    assert config.model == "openai/picked"


def test_ensure_model_explains_an_empty_lmstudio(monkeypatch) -> None:
    """Nothing usable installed must say how to fix it, not fail obscurely later."""
    monkeypatch.setattr(lmstudio, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(lmstudio, "loaded_model", lambda *a, **k: None)

    with pytest.raises(lmstudio.LMStudioError, match="no usable model"):
        lmstudio.ensure_model()
