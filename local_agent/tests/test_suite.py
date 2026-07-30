#!/usr/bin/env python3
"""Unit tests for local_agent.suite — the parts that need no strands/QGIS.

These cover the pure logic: the agent registry, the cost model, the context-plan
arithmetic, prompt composition when nothing is injected, and provision target parsing.
The strands-dependent paths (``budget.plan_context``, ``runner.run_live``) are exercised
by the KADAS eval framework, not here.

Run:  ~/.open_geoagent/venv_py3.12/bin/python -m pytest local_agent/tests/test_suite.py -q
(or plain python3 if pydantic is importable; build_config is the only pydantic user.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from local_agent.suite import agents, cost, provision, report, runner  # noqa: E402
from local_agent.suite.budget import ContextPlan  # noqa: E402


# -- agents ------------------------------------------------------------------


def test_registry_has_defaults():
    reg = agents.load_agents()
    assert {"claude", "local-raw", "eth-ollama"} <= set(reg)


def test_resolve_preserves_order_and_all():
    names = [s.name for s in agents.resolve(["eth-ollama", "claude"])]
    assert names == ["eth-ollama", "claude"]
    assert len(agents.resolve(None)) == len(agents.load_agents())
    assert len(agents.resolve(["all"])) == len(agents.load_agents())


def test_resolve_unknown_fails_fast():
    with pytest.raises(KeyError):
        agents.resolve(["not-a-real-agent"])


# -- cost --------------------------------------------------------------------


def test_longest_prefix_price_match():
    # claude-sonnet-4-6 must resolve via the 'claude-sonnet-4' key, not a shorter one.
    assert cost.lookup_price("claude-sonnet-4-6") == (3.0, 15.0)
    assert cost.lookup_price("openai/gpt-4o-mini") == (0.15, 0.60)  # strips routing prefix


def test_local_is_free_and_unknown_is_unpriced():
    local = cost.estimate(model="qwen2.5-7b", input_tokens=9999, output_tokens=99, local=True)
    assert local.usd == 0.0 and local.priced

    unknown = cost.estimate(model="mystery", input_tokens=1000, output_tokens=100)
    assert not unknown.priced and unknown.usd == 0.0


def test_explicit_price_overrides_table_and_local():
    est = cost.estimate(
        model="qwen2.5-7b", input_tokens=1_000_000, output_tokens=0,
        local=True, price_in=2.0,
    )
    assert est.usd == pytest.approx(2.0) and est.priced


# -- ContextPlan arithmetic --------------------------------------------------


def _plan(**kw):
    base = dict(
        agent="x", model="m", window=8192, usable=4915, fast=False,
        system_tokens=2000, tool_count=62, tool_tokens=10600,
        api_docs_tokens=0, upskill_tokens=0, prompt_tokens=20,
    )
    base.update(kw)
    return ContextPlan(**base)


def test_overhead_and_fit():
    p = _plan()
    assert p.fixed_overhead == 2000 + 10600 + 20
    assert not p.fits  # 12620 > 4915 usable
    assert p.headroom == p.usable - p.fixed_overhead

    small = _plan(tool_tokens=1000, system_tokens=1500, usable=4915)
    assert small.fits and small.headroom > 0


# -- prompt composition ------------------------------------------------------


def test_compose_prompt_noop_when_nothing_injected():
    spec = agents.load_agents()["local-raw"]  # api_docs=False, upskill=False
    text, meta = runner.compose_prompt(spec, "List the layers.")
    assert text == "List the layers."
    assert meta["injected_tokens"] == 0 and not meta["api_docs"] and not meta["upskill"]


# -- provision target parsing ------------------------------------------------


def test_provision_canonical_aliases():
    assert provision._canonical("local") == "lmstudio"
    assert provision._canonical("cluster") == "eth"
    with pytest.raises(ValueError):
        provision._canonical("nonsense")


# -- report rendering --------------------------------------------------------


def test_render_plan_marks_overflow_and_local_cost():
    rows = [
        {
            "agent": "local-raw", "test_id": "E01", "difficulty": "easy",
            "model": "qwen2.5-7b-instruct", "window": 8192, "fixed_overhead": 12000,
            "headroom": -7085, "fits": False, "tool_tokens": 10600,
            "api_docs_tokens": 0, "upskill_tokens": 0, "usd_per_turn": 0.0,
            "priced": True, "adaptations": [], "recommendations": ["try fast=True"],
        }
    ]
    out = report.render_plan(rows)
    assert "NO" in out and "$0 (local)" in out and "fast" in out


# -- plan-first reasoning ----------------------------------------------------


def test_planning_helpers():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "planning", str(REPO_ROOT / "geoagent" / "core" / "planning.py")
    )
    planning = importlib.util.module_from_spec(spec)
    sys.modules["planning"] = planning
    spec.loader.exec_module(planning)

    # build_execution_prompt: no plan passes through; a plan is prepended.
    assert planning.build_execution_prompt("", "zoom to Bern") == "zoom to Bern"
    out = planning.build_execution_prompt("1. locate_and_zoom", "zoom to Bern")
    assert "1. locate_and_zoom" in out and "zoom to Bern" in out

    # _plan_text pulls text from a Strands-shaped result and drops "none".
    class R:
        message = {"content": [{"text": "1. list_project_layers"}]}

    assert planning._plan_text(R()) == "1. list_project_layers"


def test_plan_flag_on_agentspec():
    reg = agents.load_agents()
    assert "eth-plan" in reg and reg["eth-plan"].plan is True
    assert reg["claude"].plan is False  # default off


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
