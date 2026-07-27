#!/usr/bin/env python3
"""Benchmark runner: Claude vs raw local vs upskilled local, inside KADAS.

Run it from the **KADAS Python console**, because the agent needs a live ``iface`` and a
real window to screenshot::

    import sys; sys.path.insert(0, "/home/aloha/OPENGIS/plugins/qgis-plugins/GeoAgent")
    from local_agent.tests import run_evals

    run_evals.run(iface)                                  # every agent, every test
    run_evals.run(iface, configs=["local-raw"])           # one agent
    run_evals.run(iface, difficulty="easy")               # smoke test first
    run_evals.run(iface, test_ids=["E01", "E03"])

For each (agent, test) it: narrows the tool surface -> sends the prompt -> screenshots the
KADAS window -> writes one telemetry record.

**Read this before trusting the output.** The pass/fail column is advisory (see
``evaluators.py``). The deliverables are the screenshots and ``raw_output``; the counts
are only there to tell you where to look first.

Two things this harness deliberately does NOT do:

- **Reset project state between tests.** Tests mutate the project and later tests see it.
  Run ``difficulty="easy"`` on a fresh project for clean numbers, or accept that M01
  ("remove every layer") will affect everything after it. Automating a reset would mean
  guessing which project to restore, and guessing wrong silently corrupts a sweep.
- **Auto-approve destructive tools.** ``confirm`` defaults to approving everything so the
  sweep runs unattended, which is safe only because these benchmarks touch a scratch
  project. Do not point this at real work.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from geoagent.core import context_docs  # noqa: E402
from local_agent import connection  # noqa: E402
from local_agent.skills import selector  # noqa: E402
from local_agent.telemetry import screenshot as screenshot_mod  # noqa: E402
from local_agent.telemetry.tracker import BenchmarkTracker, summarize  # noqa: E402
from local_agent.tests import evaluators  # noqa: E402

BENCHMARKS = Path(__file__).resolve().parent / "qgis_kadas_benchmarks.json"
SKILL_BUNDLE = REPO_ROOT / "local_agent" / "skills" / "skills_prompt.md"

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
LOCAL_MODEL_ID = "openai/qwen2.5-7b-instruct"

# The ETH hybrid target, read from local_agent/config.json so the tunnel manager and the
# eval runner cannot disagree about which node/model is in play.
_CONNECTION = connection.load_config()
ETH_OLLAMA_HOST = _CONNECTION.base_url
ETH_OLLAMA_MODEL = _CONNECTION.ollama_model

# The agents under comparison. 'upskill' prepends the bundled SKILL.md files to the
# system prompt, which is the whole hypothesis under test.
# Every agent gets the FULL 62-tool surface. An earlier version narrowed each test to the
# tools it needed; that both solved a problem that no longer exists (at 32k context the
# full surface is 39% of the window) and leaked the answer -- handing a "list the layers"
# test exactly [list_project_layers] means the model cannot choose wrong, so it measured
# argument filling while claiming to measure tool selection.
#
# The two guidance axes are independent and separately measurable:
#   upskill  -- inject the hand-authored SKILL.md matching the prompt
#   api_docs -- inject the generated KADAS API reference matching the prompt
AGENT_CONFIGS: dict[str, dict[str, Any]] = {
    "claude": {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "upskill": False,
        "api_docs": False,
        "note": "Golden baseline. Bills the ANTHROPIC_API_KEY in the environment.",
    },
    "local-raw": {
        "provider": "lmstudio",
        "model_id": LOCAL_MODEL_ID,
        "base_url": LM_STUDIO_BASE_URL,
        "upskill": False,
        "api_docs": False,
        "note": "LM Studio, nothing injected. The baseline the others must beat.",
    },
    "local-upskilled": {
        "provider": "lmstudio",
        "model_id": LOCAL_MODEL_ID,
        "base_url": LM_STUDIO_BASE_URL,
        "upskill": True,
        "api_docs": False,
        "note": "+ the hand-authored skill selected for this prompt.",
    },
    "local-api-docs": {
        "provider": "lmstudio",
        "model_id": LOCAL_MODEL_ID,
        "base_url": LM_STUDIO_BASE_URL,
        "upskill": False,
        "api_docs": True,
        "note": "+ the generated KADAS API reference. Isolates docs from hand guidance.",
    },
    "local-both": {
        "provider": "lmstudio",
        "model_id": LOCAL_MODEL_ID,
        "base_url": LM_STUDIO_BASE_URL,
        "upskill": True,
        "api_docs": True,
        "note": "+ both. Do they compound, or does the extra context dilute?",
    },
    # The ETH hybrid path: model on a Slurm GPU node, reached through the SSH tunnel
    # (local_agent/connection.py). The tunnel makes the remote server look local, so this
    # is just the ollama provider pointed at localhost -- no special plumbing.
    # Measured round-trip through the tunnel: 7.6 ms median, i.e. ~45 ms across a
    # 6-call turn. Network is not the bottleneck; the node's GPU is the point.
    "eth-ollama": {
        "provider": "ollama",
        "model_id": ETH_OLLAMA_MODEL,
        "ollama_host": ETH_OLLAMA_HOST,
        "upskill": False,
        "api_docs": False,
        "note": "ETH Slurm node via SSH tunnel. Run `connection doctor` first.",
    },
    "eth-ollama-both": {
        "provider": "ollama",
        "model_id": ETH_OLLAMA_MODEL,
        "ollama_host": ETH_OLLAMA_HOST,
        "upskill": True,
        "api_docs": True,
        "note": "ETH node + skill + API docs.",
    },
}


def load_benchmarks(
    *,
    difficulty: str | None = None,
    category: str | None = None,
    test_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load and filter the benchmark suite."""
    import json

    data = json.loads(BENCHMARKS.read_text(encoding="utf-8"))
    tests = data["benchmarks"]
    if difficulty:
        tests = [t for t in tests if t["difficulty"] == difficulty]
    if category:
        tests = [t for t in tests if t["category"] == category]
    if test_ids:
        wanted = set(test_ids)
        tests = [t for t in tests if t["id"] in wanted]
    return tests


# NOTE: an earlier `subset_tools()` narrowed each agent to the tools its test declared.
# It is gone deliberately, for two reasons:
#   1. It solved an 8k-context problem that no longer exists. At 32k the full 62-tool
#      surface is ~39% of the window, and qwen2.5-7b picks correctly from all of it.
#   2. It leaked the answer. Handing a "list the layers" test exactly
#      [list_project_layers] means the model cannot choose wrong -- that measures argument
#      filling while claiming to measure tool selection.
# If the surface ever does need narrowing, retrieve from the full catalog (Tool Search /
# RAG-MCP) rather than amputating it -- and note that changing the tool block per turn
# breaks the prompt cache.


def build_agent(
    config_name: str,
    iface: Any,
    project: Any = None,
    *,
    fast: bool = False,
) -> Any:
    """Construct a GeoAgent for one named config.

    Deliberately knows nothing about skills or docs: the agent (system prompt + tools) is
    the **cacheable prefix** and must be byte-identical across turns. All per-question
    guidance goes in the user message via :func:`build_turn_prompt`.
    """
    from geoagent.core import factory
    from geoagent.core.config import GeoAgentConfig

    spec = AGENT_CONFIGS[config_name]
    kwargs: dict[str, Any] = {"provider": spec["provider"], "model": spec["model_id"]}
    if spec.get("base_url"):
        kwargs["lmstudio_base_url"] = spec["base_url"]
    if spec.get("ollama_host"):
        kwargs["ollama_host"] = spec["ollama_host"]
    config = GeoAgentConfig(**kwargs)

    return factory.for_kadas(
        iface,
        project,
        config=config,
        fast=fast,
        confirm=lambda *_a, **_k: True,  # unattended sweep; scratch project only
        enable_logging=False,  # this harness owns its own telemetry
    )


def build_turn_prompt(config_name: str, prompt: str) -> tuple[str, dict[str, Any]]:
    """Return the prompt to send, plus what was injected into it.

    This is where "upskilling" actually happens, and it happens **in the user message**.

    An earlier version monkeypatched ``factory.KADAS_SYSTEM_PROMPT`` instead. That put the
    guidance in the *cached prefix*: the system prompt and tool definitions form a
    byte-stable block that llama.cpp caches, and re-sending an identical ~16k prefix costs
    ~0.5s against 13-22s when it changes. Because the injected text varies per test, that
    approach invalidated the cache on **every** test -- paying full prefill each time,
    which is exactly the penalty this harness measured and warned about. It also mutated
    global state mid-sweep.

    Returns:
        ``(prompt_to_send, metadata)`` where metadata records what was injected, so the
        telemetry can attribute a result to the guidance it actually saw.
    """
    spec = AGENT_CONFIGS[config_name]
    meta: dict[str, Any] = {"skill": None, "doc_pack": None, "injected_tokens": 0}
    blocks: list[str] = []

    if spec.get("upskill"):
        # The per-topic SKILL.md files were consolidated into one shipped, tiered guide
        # (geoagent.core.operations_guide). Inject the whole guide here — inside KADAS the
        # window is 32k+, so the ~1.4k guide always fits.
        from geoagent.core import operations_guide

        fragment = operations_guide.build_block()
        if fragment:
            meta["skill"] = "kadas-operations (" + ",".join(
                operations_guide.selected_tiers(None)
            ) + ")"
            blocks.append(fragment)

    if spec.get("api_docs"):
        block = context_docs.build_context_block(prompt)
        if block:
            packs = context_docs.select_packs(prompt)
            meta["doc_pack"] = ", ".join(p.name for p in packs)
            blocks.append(block)

    if not blocks:
        return prompt, meta

    composed = "\n\n".join(blocks) + "\n\n" + prompt
    meta["injected_tokens"] = (len(composed) - len(prompt)) // 4
    return composed, meta


def _extract_tool_calls(agent: Any) -> list[dict[str, Any]]:
    """Read the tools invoked during the last turn, with their arguments.

    The **arguments are the point**, not just the names. This suite exists partly to catch
    a model calling the right tool with wrong argument names (``x``/``y`` instead of
    ``lon``/``lat``, ``bodid`` instead of ``bod_id``), which is the dominant local-model
    failure and the thing a SKILL.md fixes. Recording only names would throw that away.

    GeoAgent stores these as ``{"name", "args", "tool_use_id", "result"}`` -- note ``args``,
    not ``input``. The result status is kept so a "called the right tool, and it errored"
    turn is distinguishable from "called the wrong tool" during gap analysis.
    """
    calls = getattr(agent, "_tool_calls", None) or []
    out = []
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
                "result": _summarize_result(result),
            }
        )
    return out


def _summarize_result(result: dict[str, Any]) -> str:
    """Flatten a tool result to a short string for the log."""
    blocks = result.get("content") or []
    texts = [str(b.get("text", "")) for b in blocks if isinstance(b, dict)]
    return " ".join(texts)[:500]


def _extract_tokens(agent: Any) -> dict[str, int]:
    """Read token usage if the provider reported it.

    **These are ACCUMULATED across the agent loop, not context occupancy.** An agent turn
    is N model calls (one per tool round-trip plus a final answer), and Strands sums the
    input tokens over all of them. Measured 2026-07-16: a 2-tool agent answering E01
    reported inputTokens=4865 with cycle_count=2 -- i.e. ~2,432 per call, not a 4,865-token
    prompt. Dividing by ``cycles`` gives the per-call figure that is comparable to the
    context window.

    The number that actually matters for overflow is the *last* cycle: message history and
    tool results accumulate, so the prompt grows with every tool call. ``cycles`` is
    recorded so a high-tool-count turn that overflowed is identifiable after the fact.

    Local backends frequently omit usage; an empty dict means 'not reported', not 'zero'.
    """
    try:
        metrics = getattr(agent.strands_agent, "event_loop_metrics", None)
        usage = getattr(metrics, "accumulated_usage", None)
        if not usage:
            return {}
        cycles = int(getattr(metrics, "cycle_count", 0) or 0)
        tokens = {
            "input_accumulated": int(usage.get("inputTokens", 0)),
            "output_accumulated": int(usage.get("outputTokens", 0)),
            "total_accumulated": int(usage.get("totalTokens", 0)),
            "cycles": cycles,
        }
        if cycles:
            tokens["input_per_cycle_avg"] = tokens["input_accumulated"] // cycles
        return tokens
    except Exception:
        return {}


def run_one(
    agent_name: str,
    test: dict[str, Any],
    iface: Any,
    tracker: BenchmarkTracker,
    *,
    window: Any = None,
    project: Any = None,
    fast: bool = False,
) -> dict[str, Any]:
    """Run a single benchmark against a single agent and record it.

    Never raises: an agent that blows up is recorded with status='error' so one bad test
    cannot abort a sweep that takes minutes per agent.
    """
    before = evaluators.project_state()
    started = time.monotonic()
    answer, error, tool_calls, tokens = "", None, [], {}
    injected: dict[str, Any] = {}

    try:
        agent = build_agent(agent_name, iface, project, fast=fast)
        # The agent keeps its full tool surface; guidance rides in the user message.
        sent, injected = build_turn_prompt(agent_name, test["prompt"])
        label = injected.get("doc_pack") or injected.get("skill") or "no guidance"
        print(
            f"  [{test['id']}] {agent_name}: {len(agent.tool_names)} tools, "
            f"{label} ... ",
            end="",
            flush=True,
        )
        answer = str(agent.chat(sent))
        tool_calls = _extract_tool_calls(agent)
        tokens = _extract_tokens(agent)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"ERROR {error[:60]}")

    latency_ms = (time.monotonic() - started) * 1000
    after = evaluators.project_state()

    shot = screenshot_mod.capture(
        agent_name, test["id"], test["difficulty"], window=window
    )

    if error:
        status, checks = "error", {}
    else:
        result = evaluators.evaluate(
            test["eval_criteria"],
            answer=answer,
            tool_calls=tool_calls,
            iface=iface,
            before=before,
            after=after,
        )
        status, checks = result.status, result.checks
        print(f"{status} ({latency_ms / 1000:.1f}s)")

    return tracker.record(
        test_id=test["id"],
        difficulty=test["difficulty"],
        category=test["category"],
        prompt=test["prompt"],
        status=status,
        latency_ms=latency_ms,
        raw_output=answer,
        screenshot=shot,
        tool_calls=tool_calls,
        tokens=tokens,
        checks=checks,
        error=error,
        # What guidance this turn actually saw, so a result can be attributed to it
        # rather than inferred from the config name.
        injected=injected,
        human_check=test["eval_criteria"].get("human_check", ""),
    )


def run(
    iface: Any,
    *,
    configs: list[str] | None = None,
    difficulty: str | None = None,
    category: str | None = None,
    test_ids: list[str] | None = None,
    project: Any = None,
    fast: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Run the sweep. Call this from the KADAS Python console.

    Args:
        iface: The live KADAS iface. Wrapped in KadasIfaceAdapter automatically if needed.
        configs: Agent names from AGENT_CONFIGS. Defaults to every config.
        fast: Pass fast=True to for_kadas (41 tools instead of 62). Off by default: the
            full surface fits a 32k window and narrowing it is the thing under test, not
            an assumption to bake in.

    Returns:
        {agent_name: [records]}. The screenshots and raw_output are the real output.
    """
    iface = _ensure_adapter(iface)
    window = screenshot_mod.find_kadas_window()
    if window is None:
        print(
            "WARNING: no KADAS window found; screenshots will be desktop-wide or absent"
        )

    names = configs or list(AGENT_CONFIGS)
    tests = load_benchmarks(difficulty=difficulty, category=category, test_ids=test_ids)
    if not tests:
        print("no benchmarks matched the filter")
        return {}

    print(f"\n{len(tests)} test(s) x {len(names)} agent(s)\n")
    results: dict[str, list[dict[str, Any]]] = {}
    paths = []

    for name in names:
        spec = AGENT_CONFIGS[name]
        tracker = BenchmarkTracker(name, model_id=spec["model_id"])
        paths.append(tracker.log_path)
        print(f"--- {name} ({spec['model_id']}) -> {tracker.log_path.name}")
        results[name] = [
            run_one(
                name, test, iface, tracker, window=window, project=project, fast=fast
            )
            for test in tests
        ]

    print(summarize(paths))
    print("screenshots:", screenshot_mod.SCREENSHOT_DIR)
    return results


def _ensure_adapter(iface: Any) -> Any:
    """Wrap a raw KadasPluginInterface in KadasIfaceAdapter if it needs it.

    KADAS hands plugins an iface without QGIS's layer helpers (addVectorLayer,
    activeLayer, ...). The adapter fills them in against QgsProject/canvas. Detect by
    probing for one of the missing methods rather than by type, so this works whether the
    caller passed the raw iface or an already-wrapped one.
    """
    if hasattr(iface, "addVectorLayer") and hasattr(iface, "activeLayer"):
        return iface
    try:
        from kadas_geoagent.kadas_iface_adapter import KadasIfaceAdapter
    except ImportError:
        try:
            from kadas_geoagent.kadas_geoagent.kadas_iface_adapter import (
                KadasIfaceAdapter,
            )
        except ImportError:
            print(
                "WARNING: KadasIfaceAdapter not importable; passing iface through raw"
            )
            return iface
    return KadasIfaceAdapter(iface)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point -- refuses to run, by design.

    There is no headless path: the agent needs a live KADAS iface and the screenshots need
    a real window. Failing loudly here beats silently benchmarking a mock.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List benchmarks and exit")
    args = parser.parse_args(argv)

    if args.list:
        for test in load_benchmarks():
            print(
                f"{test['id']:4s} {test['difficulty']:6s} {test['category']:22s} "
                f"{len(test.get('tools', [])):2d} tools  {test['prompt'][:50]}"
            )
        return 0

    print(
        "run_evals must run inside KADAS -- it needs a live iface and window.\n\n"
        "  In the KADAS Python console:\n"
        f'    import sys; sys.path.insert(0, "{REPO_ROOT}")\n'
        "    from local_agent.tests import run_evals\n"
        '    run_evals.run(iface, difficulty="easy")\n\n'
        "  --list shows the suite without running it.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
