"""Run a scenario across many agents — requirement #1, minimal setup.

Two modes, deliberately:

- ``plan`` (default, **zero backend**): for every (agent, scenario) compute the context
  footprint (:mod:`.budget`) and its priced cost (:mod:`.cost`). Calls no model, needs no
  GPU, no API key, no KADAS. This is the "test many agents with minimal setup" path: it
  tells you which agents *can* run a prompt (does it fit?) and what each would cost, before
  you spend a token.

- ``live``: build a real ``GeoAgent`` against the **mock** hosts and actually send the
  prompt, capturing tool calls, tokens, latency, and advisory checks. Headless — no live
  KADAS window (that is what ``local_agent/tests/run_evals.py`` remains for, when you need
  screenshots and real project state). Requires the agent's backend to be provisioned
  (``suite provision ...``).

The mock-host path is the key difference from ``run_evals``: it removes KADAS from the
loop so a sweep runs on any machine. The tradeoff is that state probes (layer counts,
canvas extent) degrade to "unknown" without QGIS — tool *selection* and *arguments* are
still measured, which is where local models actually fail.

Import-safe: QGIS/mock/factory imports happen inside the run functions.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from local_agent.suite import budget as budget_mod
from local_agent.suite import cost as cost_mod
from local_agent.suite.agents import AgentSpec, build_config

BENCHMARKS = (
    Path(__file__).resolve().parents[1] / "tests" / "qgis_kadas_benchmarks.json"
)

# Nominal completion length for pricing the plan-mode estimate. Output tokens are unknown
# before the model runs; 256 is a representative short KADAS answer. Documented so the
# number is not mistaken for a measurement.
NOMINAL_OUTPUT_TOKENS = 256


def load_scenarios(
    path: Path | None = None,
    *,
    difficulty: str | None = None,
    ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load and filter the benchmark scenarios (shared with ``run_evals``)."""
    data = json.loads((path or BENCHMARKS).read_text(encoding="utf-8"))
    tests = data["benchmarks"]
    if difficulty:
        tests = [t for t in tests if t.get("difficulty") == difficulty]
    if ids:
        wanted = set(ids)
        tests = [t for t in tests if t.get("id") in wanted]
    return tests


def compose_prompt(spec: AgentSpec, prompt: str) -> tuple[str, dict[str, Any]]:
    """Prepend the guidance *spec* opts into, in the user message (never the prefix).

    Returns ``(text_to_send, injected_metadata)``. Mirrors ``run_evals.build_turn_prompt``
    but reads its blocks from :mod:`.budget`, so the two share one definition of what
    "api_docs" and "upskill" inject.
    """
    meta: dict[str, Any] = {"api_docs": False, "upskill": False, "injected_tokens": 0}
    blocks: list[str] = []
    if spec.upskill:
        # Size the operations guide to this model's window (CORE-only on a small model,
        # whole guide on a large one), exactly as plan_context accounts for it.
        from local_agent.skills import operations

        plan = budget_mod.plan_context(spec, prompt)
        base = (
            plan.system_tokens + plan.tool_tokens
            + plan.api_docs_tokens + plan.prompt_tokens
        )
        budget_tok = budget_mod.upskill_budget(plan.usable, base)
        frag = budget_mod.upskill_block(prompt, budget_tok)
        if frag:
            meta["upskill"] = True
            meta["upskill_tiers"] = operations.selected_tiers(budget_tok)
            blocks.append(frag)
    if spec.api_docs:
        block = budget_mod.api_docs_block(prompt)
        if block:
            meta["api_docs"] = True
            blocks.append(block)
    if not blocks:
        return prompt, meta
    composed = "\n\n".join(blocks) + "\n\n" + prompt
    meta["injected_tokens"] = (len(composed) - len(prompt)) // 4
    return composed, meta


# -- plan mode ---------------------------------------------------------------


def run_plan(
    specs: list[AgentSpec],
    scenarios: list[dict[str, Any]],
    *,
    adapt: bool = True,
    price_in: float | None = None,
    price_out: float | None = None,
) -> list[dict[str, Any]]:
    """Cost + fit for every (agent, scenario). No model is called."""
    rows: list[dict[str, Any]] = []
    for spec in specs:
        for sc in scenarios:
            prompt = sc["prompt"]
            if adapt:
                used, plan, changes = budget_mod.adapt_spec(spec, prompt)
            else:
                used, plan, changes = spec, budget_mod.plan_context(spec, prompt), []
            est = cost_mod.estimate(
                model=used.model,
                input_tokens=plan.fixed_overhead,
                output_tokens=NOMINAL_OUTPUT_TOKENS,
                local=used.local,
                price_in=price_in,
                price_out=price_out,
            )
            rows.append(
                {
                    "agent": spec.name,
                    "test_id": sc.get("id"),
                    "difficulty": sc.get("difficulty"),
                    "model": used.model,
                    "window": plan.window,
                    "fixed_overhead": plan.fixed_overhead,
                    "headroom": plan.headroom,
                    "fits": plan.fits,
                    "tool_tokens": plan.tool_tokens,
                    "api_docs_tokens": plan.api_docs_tokens,
                    "upskill_tokens": plan.upskill_tokens,
                    "usd_per_turn": est.usd,
                    "priced": est.priced,
                    "adaptations": changes,
                    "recommendations": plan.recommendations,
                }
            )
    return rows


# -- live mode ---------------------------------------------------------------


def run_live(
    specs: list[AgentSpec],
    scenarios: list[dict[str, Any]],
    *,
    tracker_dir: Path | None = None,
    adapt: bool = True,
    progress: Any = None,
) -> list[dict[str, Any]]:
    """Build each agent on mock hosts, send each prompt, record telemetry.

    Requires the backend to be reachable (``suite provision``). Per-record failures are
    captured, not raised, so one dead agent does not abort the sweep.
    """
    from geoagent.testing import MockQGISIface, MockQGISProject
    from local_agent.telemetry.tracker import BenchmarkTracker
    from local_agent.tests import evaluators

    def say(msg: str) -> None:
        if callable(progress):
            progress(msg)

    records: list[dict[str, Any]] = []
    for spec in specs:
        used = spec
        if adapt:
            # Adapt once on the first scenario's prompt; the tool surface (the dominant
            # cost) is prompt-independent, so this is a stable per-agent decision.
            used, _plan, changes = budget_mod.adapt_spec(spec, scenarios[0]["prompt"])
            if changes:
                say(f"{spec.name}: adapted ({'; '.join(changes)})")
        tracker = BenchmarkTracker(
            agent_name=spec.name, model_id=used.model, log_dir=tracker_dir
        )
        for sc in scenarios:
            say(f"{spec.name} · {sc.get('id')}")
            records.append(_run_one_live(used, sc, tracker, evaluators, MockQGISIface, MockQGISProject))
    return records


def _run_one_live(
    spec: AgentSpec,
    sc: dict[str, Any],
    tracker: Any,
    evaluators: Any,
    MockIface: Any,
    MockProject: Any,
) -> dict[str, Any]:
    from geoagent.core import factory

    prompt = sc["prompt"]
    composed, inj = compose_prompt(spec, prompt)
    started = time.perf_counter()
    try:
        agent = factory.for_kadas(
            MockIface(),
            MockProject(),
            config=build_config(spec),
            fast=spec.fast,
            confirm=lambda *_a, **_k: True,
            enable_logging=False,
        )
        turn_prompt = composed
        if spec.plan:
            # Plan-first: a toolless planning pass, then execute the plan (same as the
            # plugin's clickable mode). Measures whether planning lifts a small model.
            from geoagent.core import operations_guide, planning

            try:
                strands_agent = agent.strands_agent
                names = list(getattr(strands_agent, "tool_names", []) or [])
                plan = planning.make_plan(
                    strands_agent.model, prompt, tool_names=names,
                    guide_block=operations_guide.build_block(max_tokens=600),
                )
                turn_prompt = planning.build_execution_prompt(plan, composed)
                inj["plan"] = bool(plan)
            except Exception:
                inj["plan"] = False
        response = agent.chat(turn_prompt)
        latency_ms = (time.perf_counter() - started) * 1000
        answer = str(response)
        tool_calls = _extract_tool_calls(agent)
        tokens = _extract_tokens(agent)
        check = evaluators.evaluate(
            sc.get("eval_criteria", {}), answer=answer, tool_calls=tool_calls
        )
        return tracker.record(
            test_id=sc.get("id", "?"),
            difficulty=sc.get("difficulty", "?"),
            category=sc.get("category", "?"),
            prompt=prompt,
            status=check.status,
            latency_ms=latency_ms,
            raw_output=answer,
            tool_calls=tool_calls,
            tokens=tokens,
            checks=check.checks,
            injected=inj,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return tracker.record(
            test_id=sc.get("id", "?"),
            difficulty=sc.get("difficulty", "?"),
            category=sc.get("category", "?"),
            prompt=prompt,
            status="error",
            latency_ms=latency_ms,
            error=f"{type(exc).__name__}: {exc}",
            injected=inj,
        )


def _extract_tool_calls(agent: Any) -> list[dict[str, Any]]:
    """Names + **arguments** of tools invoked last turn. Args are the point (see #3)."""
    calls = getattr(agent, "_tool_calls", None) or []
    out: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            out.append({"name": str(call), "args": {}, "status": "unknown"})
            continue
        result = call.get("result") or {}
        out.append(
            {
                "name": call.get("name", "?"),
                "args": call.get("args", {}),
                "status": result.get("status", "unknown"),
            }
        )
    return out


def _extract_tokens(agent: Any) -> dict[str, int]:
    """Accumulated usage across the agent loop, if the provider reported it.

    Empty means 'not reported' (common for local backends), not 'zero'. ``input_per_cycle``
    is the figure comparable to the context window; the accumulated total is not.
    """
    try:
        metrics = getattr(agent.strands_agent, "event_loop_metrics", None)
        usage = getattr(metrics, "accumulated_usage", None)
        if not usage:
            return {}
        cycles = int(getattr(metrics, "cycle_count", 0) or 0)
        out = {
            "input_accumulated": int(usage.get("inputTokens", 0)),
            "output_accumulated": int(usage.get("outputTokens", 0)),
            "cycles": cycles,
        }
        if cycles:
            out["input_per_cycle"] = out["input_accumulated"] // cycles
        return out
    except Exception:
        return {}
