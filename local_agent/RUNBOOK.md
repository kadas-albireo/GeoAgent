# RUNBOOK — running the GeoAgent test harness

How to run the full evaluation under each guidance condition. Everything here uses one CLI
(`python -m local_agent.suite`) plus the LM Studio backend manager
(`geoagent.core.lmstudio`).

All Python must run under the QGIS venv (it has `strands`):

```bash
PY=~/.open_geoagent/venv_py3.12/bin/python
```

---

## 0. The four conditions map to named agents

The two guidance axes you asked about are **independent** and already wired as agents in
`suite/agents.json`, so each condition is a one-word selection, not a code edit:

| Backend | raw | + docs (documancer) | + upskilling | + both |
|---|---|---|---|---|
| **LM Studio** | `local-raw` | `local-docs` | `local-upskilled` | `local-both` |
| **Claude (baseline)** | `claude` | — | — | — |

- **docs** = inject the KADAS API reference matched to the prompt (`geoagent/core/context_docs.py`).
- **upskilling** = inject the operations guide, tier-sliced to the model's window
  (`skills/kadas-operations/SKILL.md` via `skills/operations.py`).

Compare cost/context of any subset **without a backend or a model call**:

```bash
$PY -m local_agent.suite budget "Add a hillshade for the area around Grindelwald"
$PY -m local_agent.suite run --mode plan --agents local-raw local-both
```

---

## 1. LM Studio model

**Server side = client side** (LM Studio runs on your laptop). One command brings the
server up and loads a model at a context large enough for the KADAS tool schemas (the 8192
default is too small):

```bash
$PY -m geoagent.core.lmstudio            # status: is the server up, what's loaded
$PY -m local_agent.suite provision lmstudio --model qwen2.5-7b-instruct
```

Then run the sweep against any LM Studio agent:

```bash
# headless (mock KADAS, any machine) — measures tool choice + arguments
$PY -m local_agent.suite run --mode live --agents local-raw local-docs local-upskilled local-both --out runs/lmstudio

# aggregate the telemetry it wrote
$PY -m local_agent.suite report runs/lmstudio/*.log
```

For the **full KADAS experience** (real canvas, screenshots, real project state) run the
older KADAS-bound harness from the KADAS Python console instead:

```python
import sys; sys.path.insert(0, "/home/aloha/OPENGIS/plugins/qgis-plugins/GeoAgent")
from local_agent.tests import run_evals
run_evals.run(iface, configs=["local-raw", "local-both"], difficulty="easy")
```

---

## 2. With / without upskilling and docs (the A/B you asked for)

Because the conditions are separate agents, an A/B is just selecting them. From the UI: in
**GeoAgent Settings → Model**, the *Upskilling* and *Inject API docs* checkboxes toggle the
same two axes for the interactive chat (§ plugin UI). From the CLI:

```bash
# isolate each axis against the same backend
$PY -m local_agent.suite run --mode live --agents local-raw local-upskilled --out runs/ab_upskill
$PY -m local_agent.suite run --mode live --agents local-raw local-docs      --out runs/ab_docs
$PY -m local_agent.suite report runs/ab_upskill/*.log runs/ab_docs/*.log
```

Read the telemetry's **tool-call arguments**, not just the pass column — the dominant
local-model failure is the right tool with the wrong argument names, and that is exactly
what the operations guide and the API docs are there to fix.

---

## 3. One-glance cheatsheet

```bash
PY=~/.open_geoagent/venv_py3.12/bin/python

$PY -m local_agent.suite list                       # all agents + what they inject
$PY -m local_agent.suite status                     # LM Studio backend snapshot
$PY -m local_agent.suite budget "<prompt>"          # context/cost per agent, no backend
$PY -m local_agent.suite provision lmstudio         # bring the backend up
$PY -m local_agent.suite run --mode plan            # fit + cost sweep, no model
$PY -m local_agent.suite run --mode live --out DIR  # real sweep on mock KADAS
$PY -m local_agent.suite report DIR/*.log           # token/cost/latency/pass table
```
