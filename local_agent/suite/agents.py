"""Declarative registry of the agents under test.

The point of this module is requirement #1: **test many agent types with minimal setup.**
An "agent" here is a small, JSON-serialisable :class:`AgentSpec` — provider, model, and a
few guidance toggles — not a live object. Specs are cheap to list, diff, and edit, and the
defaults ship in ``agents.json`` next to this file so adding a model is a one-line change,
not a code change.

Two guidance axes are deliberately independent and separately measurable (this is the
whole experimental design; do not fold them together):

- ``api_docs`` — inject the generated KADAS API reference matching the prompt
  (``geoagent.core.context_docs``). The "documancer" strategy of requirement #5.
- ``upskill``  — inject the hand-authored operations pathway matching the prompt
  (``OPERATIONS.md`` via ``local_agent.skills.selector``). Requirement #3.

Both go in the **user message** (the volatile tail), never the system prompt, so they do
not invalidate the model's cached prefix every turn. See ``context_docs`` module docstring.

Import-safe: no ``qgis`` and no network here. :func:`build_config` returns a
``GeoAgentConfig`` but resolves no client.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SUITE_DIR = Path(__file__).resolve().parent
DEFAULT_AGENTS_FILE = SUITE_DIR / "agents.json"


@dataclass
class AgentSpec:
    """One agent configuration under test.

    Attributes:
        name: Unique short id used on the CLI and in telemetry.
        provider: A ``geoagent.core.config.ProviderName`` value.
        model: Model id for that provider.
        base_url: OpenAI-compatible base URL for ``lmstudio``/``litellm``/``vllm``/
            ``openrouter``. ``None`` uses the provider default.
        ollama_host: Ollama base URL for the ``ollama`` / ETH-tunnel path.
        context_window: Advertised max context in tokens. ``None`` means "ask the
            backend / accept the provider default". Used by :mod:`.budget`.
        local: True for self-hosted models (cost is compute+time, billed at $0 by
            :mod:`.cost`). False for metered API providers.
        api_docs: Inject the KADAS API reference for the prompt (documancer, #5).
        upskill: Inject the operations pathway for the prompt (#3).
        fast: Use the smaller fast-mode tool surface.
        plan: Plan-first reasoning — a toolless planning pass before execution. Helps
            small models; wasted on large ones.
        note: Human-readable purpose, shown by ``suite list``.
    """

    name: str
    provider: str
    model: str
    base_url: str | None = None
    ollama_host: str | None = None
    context_window: int | None = None
    local: bool = False
    api_docs: bool = False
    upskill: bool = False
    fast: bool = False
    plan: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# The defaults. ``agents.json`` (loaded by :func:`load_agents`) overrides/extends these,
# so the shipped list stays sensible even if the JSON is deleted. Model ids and context
# windows are what this repo measured against on 2026-07-16; update the JSON, not this.
DEFAULT_AGENTS: dict[str, AgentSpec] = {
    "claude": AgentSpec(
        name="claude",
        provider="anthropic",
        model="claude-sonnet-4-6",
        context_window=200_000,
        local=False,
        note="Golden baseline. Bills ANTHROPIC_API_KEY. No injection: it does not need it.",
    ),
    "local-raw": AgentSpec(
        name="local-raw",
        provider="lmstudio",
        model="qwen2.5-7b-instruct",
        base_url="http://localhost:1234/v1",
        context_window=32_768,
        local=True,
        note="LM Studio, nothing injected. The baseline the local variants must beat.",
    ),
    "local-docs": AgentSpec(
        name="local-docs",
        provider="lmstudio",
        model="qwen2.5-7b-instruct",
        base_url="http://localhost:1234/v1",
        context_window=32_768,
        local=True,
        api_docs=True,
        note="+ generated KADAS API reference (documancer). Isolates docs from guidance.",
    ),
    "local-upskilled": AgentSpec(
        name="local-upskilled",
        provider="lmstudio",
        model="qwen2.5-7b-instruct",
        base_url="http://localhost:1234/v1",
        context_window=32_768,
        local=True,
        upskill=True,
        note="+ the operations pathway selected for this prompt.",
    ),
    "local-both": AgentSpec(
        name="local-both",
        provider="lmstudio",
        model="qwen2.5-7b-instruct",
        base_url="http://localhost:1234/v1",
        context_window=32_768,
        local=True,
        api_docs=True,
        upskill=True,
        note="+ both. Do they compound, or does the extra context dilute tool choice?",
    ),
    "eth-ollama": AgentSpec(
        name="eth-ollama",
        provider="ollama",
        model="qwen2.5:7b-instruct",
        ollama_host="http://localhost:11434",
        context_window=32_768,
        local=True,
        note="ETH Slurm node via SSH tunnel. `suite provision eth` first.",
    ),
}


def load_agents(path: Path | None = None) -> dict[str, AgentSpec]:
    """Return the agent registry: :data:`DEFAULT_AGENTS` overlaid with *path*'s JSON.

    The JSON is a list of objects with the :class:`AgentSpec` fields (``name`` required).
    A missing file is fine — you get the defaults. A malformed file is **not** fine and
    raises immediately (fail fast: a silently ignored config is a debugging trap).
    """
    registry = dict(DEFAULT_AGENTS)
    src = path or DEFAULT_AGENTS_FILE
    if not src.is_file():
        return registry
    raw = json.loads(src.read_text(encoding="utf-8"))
    entries = raw["agents"] if isinstance(raw, dict) else raw
    for entry in entries:
        if "name" not in entry:
            raise ValueError(f"agent entry missing 'name': {entry!r}")
        known = {f: entry[f] for f in AgentSpec.__annotations__ if f in entry}
        registry[entry["name"]] = AgentSpec(**known)
    return registry


def resolve(names: list[str] | None, path: Path | None = None) -> list[AgentSpec]:
    """Resolve *names* against the registry, preserving order.

    ``None`` or ``["all"]`` returns every agent. An unknown name fails fast with the
    valid set, rather than silently running a shorter sweep than asked for.
    """
    registry = load_agents(path)
    if not names or names == ["all"]:
        return list(registry.values())
    out: list[AgentSpec] = []
    for name in names:
        if name not in registry:
            raise KeyError(
                f"unknown agent {name!r}. Known: {', '.join(sorted(registry))}"
            )
        out.append(registry[name])
    return out


def build_config(spec: AgentSpec) -> Any:
    """Return a ``GeoAgentConfig`` for *spec*. Resolves no network client.

    Kept identical in shape to ``local_agent/tests/run_evals.build_agent`` so the two
    cannot disagree about how a provider is wired.
    """
    from geoagent.core.config import GeoAgentConfig

    kwargs: dict[str, Any] = {"provider": spec.provider, "model": spec.model}
    if spec.base_url:
        # lmstudio and litellm both read lmstudio_base_url/litellm_base_url; map by provider.
        if spec.provider == "lmstudio":
            kwargs["lmstudio_base_url"] = spec.base_url
        elif spec.provider in ("litellm", "openrouter", "vllm"):
            kwargs[f"{spec.provider}_base_url"] = spec.base_url
    if spec.ollama_host:
        kwargs["ollama_host"] = spec.ollama_host
    return GeoAgentConfig(**kwargs)
