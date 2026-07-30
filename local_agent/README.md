# local_agent

Isolated scope for benchmarking local LLMs against Claude on QGIS/KADAS tasks, and for
turning the failures into reusable **skills**. Nothing here is imported by the shipped
`geoagent` package or the KADAS plugin.

## The finding that shapes everything here

Measured on this repo (2026-07-16, real `cl100k_base` counts):

| Consumer | Tokens |
|---|---|
| `for_kadas()` tool schemas (62 tools) | **~10,583** |
| `KADAS_SYSTEM_PROMPT` | ~2,161 |
| All 5 skills bundled | ~3,894 |

The local model (`qwen2.5-7b-instruct`) is loaded with an **8,192** context window. The
tool schemas alone overflow it by 29% before the user says anything.

**So the lever is the tool surface, not the prompt.** Narrowing an agent to the ~6 tools a
task needs cuts schema cost from ~10,604 to ~134 tokens (measured on E01, a 99% cut).
Trimming SKILL.md prose saves an order of magnitude less. Everything in this directory is
built around that.

Reproduce it yourself:

```bash
~/.open_geoagent/venv_py3.12/bin/python local_agent/tests/context_budget.py
```

## Layout

```
research/     hardware limits, LM Studio wiring, cloud GPU, model matrix
skills/       <slug>/SKILL.md + selector.py (dynamic selection)
telemetry/    tracker.py (per-model logs) + screenshot.py (Qt capture)
tests/        benchmarks JSON + run_evals.py + evaluators.py + context_budget.py
runs/         screenshots land here
```

| File | Purpose |
|---|---|
| `research/hardware_limitations.md` | **Start here.** VRAM math, the context budget, why 6 GiB caps you at a 7B. |
| `research/lm_studio_agents.md` | Live endpoint map + how GeoAgent binds to it via `litellm`. |
| `research/cloud_hosting_options.md` | When cloud GPU is (and is not) worth it; vLLM recipe. |
| `research/llm_efficiency_matrix.md` | Which models to test on 6 GiB. Priors, not results. |
| `skills/<slug>/SKILL.md` | Hand-authored guidance + the `tools:` subset it needs. |
| `skills/selector.py` | Picks the relevant skill(s) for a prompt, returns text + tool subset. |
| `tests/qgis_kadas_benchmarks.json` | 15 progressive benchmarks, easy → hard. |
| `tests/run_evals.py` | The runner. **Runs inside KADAS.** |
| `tests/evaluators.py` | Advisory checks. Not a verdict. |
| `tests/context_budget.py` | Measures what eats the context window. |
| `telemetry/tracker.py` | `<model>_telemetry_<YYYY-MM-DD>.log`, one JSONL record per test. |
| `telemetry/screenshot.py` | Qt-native capture with mss/pyautogui fallbacks. |
| `upskill.py` | Original skill manager (generate/register/bundle/list/remove). |
| `trace_from_log.py` | `~/.kadas/agent_execution.log` → readable Markdown. |

## Running a sweep

The runner needs a **live KADAS** — the agent binds to a real `iface` and the screenshots
grab a real window. There is no headless path, by design.

1. Start LM Studio (Developer → Start Server) with a `tool_use`-capable model loaded.
   **Set the context to 16384**, not the 8192 default (`research/lm_studio_agents.md`).
2. Launch KADAS (`kadas-albireo2/run-kadas.sh`), open a **scratch** project.
3. In the KADAS Python console:

```python
import sys; sys.path.insert(0, "/home/aloha/OPENGIS/plugins/qgis-plugins/GeoAgent")
from local_agent.tests import run_evals

run_evals.run(iface, difficulty="easy")        # smoke test first
run_evals.run(iface)                           # full sweep, all agents
run_evals.run(iface, configs=["local-raw", "local-upskilled"])
```

Preview the suite without KADAS: `python local_agent/tests/run_evals.py --list`

### Agent configs

| Config | What it isolates |
|---|---|
| `claude` | Golden baseline. Bills your `ANTHROPIC_API_KEY`. |
| `local-raw` | The local model, no skill. |
| `local-upskilled` | Local model + the skill selected for that prompt. |
| `local-tools-only` | Tool subset, **no skill text**. The ablation. |

`local-tools-only` matters: if `local-upskilled` beats `local-raw`, it tells you whether
the skill *prose* did the work or the *tool narrowing* did. Without it you would credit
the writing for a win that was really about context.

## Reading the results

**The pass/fail counts are advisory.** They are a triage aid so you know where to look
first, not a verdict. `evaluators.py` does shallow mechanical checks (was the tool called?
did the layer count go up?); it cannot tell whether the circle is geodetically 5 km or the
symbol is the right MilX code.

The real deliverables are:
- `runs/screenshots/[timestamp]_[agent]_[test]_[difficulty].png`
- `raw_output` and `tool_calls` (**with arguments**) in the telemetry JSONL

Each benchmark carries an `eval_criteria.human_check` telling you what to actually look
for. Read it. A human has to judge these.

```bash
python local_agent/telemetry/tracker.py     # summarize today's logs
```

> `tokens` in the log is **accumulated over the agent loop, not context occupancy**. An
> agent turn is N model calls and Strands sums their inputs. Divide by `tokens["cycles"]`
> for the per-call figure comparable to the window.

## Authoring a skill from a failure

1. Run the sweep; find a test the local model failed and Claude passed.
2. Read its `raw_output` and `tool_calls`. The usual culprit is **wrong argument names**
   (`x`/`y` instead of `lon`/`lat`, `bodid` instead of `bod_id`) — which is why the
   telemetry records arguments, not just tool names.
3. Write/extend `skills/<slug>/SKILL.md` with the **verified** signature. Verify it against
   the registry, do not guess:

   ```python
   from geoagent.core import factory
   from geoagent.testing import MockQGISIface, MockQGISProject
   a = factory.for_kadas(MockQGISIface(), MockQGISProject(), provider="litellm", model_id="x")
   {s["name"]: s["inputSchema"]["json"]["properties"]
    for s in a.strands_agent.tool_registry.get_all_tool_specs()}
   ```

   A skill that teaches a wrong argument name is worse than no skill.
4. Add `triggers:` (keywords that select it) and `tools:` (the surface it needs).
5. Re-run: `run_evals.run(iface, test_ids=["M04"], configs=["local-raw","local-upskilled"])`
6. `python upskill.py bundle` to refresh the fallback bundle.

A skill proven useful graduates by folding its guidance into the **shipped**
`KADAS_SYSTEM_PROMPT` via a normal PR — never by shipping `local_agent/`.

## Known tool-surface gaps

Found while building the benchmarks. These are **product gaps, not model failures**, and
no skill can fix them:

- **No MilX/MSS tool exists.** Verified across `geoagent/` and `kadas_geoagent/`. The only
  handle is `trigger_kadas_action`, which activates an interactive tool that waits for a
  human click. `run_pyqgis_script` cannot reach it either: it AST-validates imports against
  `{"qgis", "math"}` (`geoagent/tools/qgis.py:32`), so `import kadasgui` is rejected.
  Benchmarks H02/H03 document this; **every agent fails H02 by design.**
- **Annotations have no styling arguments.** `add_map_marker(lon, lat, label)` has no
  colour. Asking for a "red marker" forces a model to either fail or lie.
- **`for_kadas()` has no `exclude_tool_names` passthrough** to `assemble_tools()`, so
  `run_evals.subset_tools()` reaches into `_tool_list` / `_rebuild_strands_agent()`. Adding
  that passthrough is the clean fix.

> WARNING: `fast-agent.secrets.yaml` contains real API keys — rotate them and untrack the
> file (see DEPLOYMENT.md).
