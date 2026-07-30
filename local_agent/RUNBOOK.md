# RUNBOOK — running the GeoAgent test harness

How to run the full evaluation under each backend and each guidance condition. Everything
here uses one CLI (`python -m local_agent.suite`) plus the two backend managers
(`geoagent.core.lmstudio`, `geoagent.core.eth_cluster`).

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
| **ETH node** | `eth-ollama` | `eth-docs` | `eth-upskilled` | `eth-both` |
| **Claude (baseline)** | `claude` | — | — | — |

- **docs** = inject the KADAS API reference matched to the prompt (`geoagent/core/context_docs.py`).
- **upskilling** = inject the operations guide, tier-sliced to the model's window
  (`skills/kadas-operations/SKILL.md` via `skills/operations.py`).

Compare cost/context of any subset **without a backend or a model call**:

```bash
$PY -m local_agent.suite budget "Add a hillshade for the area around Grindelwald"
$PY -m local_agent.suite run --mode plan --agents local-raw local-both eth-both
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

## 2. ETH cluster model

The model runs on an ETH D-INFK Slurm GPU node; your laptop reaches it through an SSH
local-forward (`localhost:11434 → login-host → <slurm-node>:11434`). Two sides:

### Server side (on the cluster — you do this once per allocation)

```bash
# 1. Get a GPU allocation (adjust partition/time to your quota). On the login host:
ssh achurchill@student-cluster2.inf.ethz.ch
srun --gres=gpu:1 --time=04:00:00 --pty bash      # or sbatch your usual job script
# 2. On the allocated node, start ollama serving on the forwarded port:
ollama serve &                                     # serves on :11434
```

### Client side (on your laptop)

```bash
# Authenticate once (password typed at a terminal; the shared connection persists ~8h).
$PY -m geoagent.core.eth_cluster login

# Open the tunnel (discovers the live Slurm node from squeue, not the cached one).
$PY -m local_agent.suite provision eth        # == eth_cluster up + verify

# Inspect what you're actually running and whether you should run something bigger:
$PY -m geoagent.core.eth_cluster probe        # GPU + VRAM + model recommendation
$PY -m geoagent.core.eth_cluster models       # what's already pulled on the node
$PY -m geoagent.core.eth_cluster doctor       # diagnose a broken pipeline end to end
```

### Upgrade to the largest model the node can run

`probe` prints the GPU VRAM and a best-first recommendation (Qwen-family lead because they
emit structured `<tool_call>` delimiters reliably, which this pipeline requires). To adopt
one:

```bash
$PY -m geoagent.core.eth_cluster pull qwen3-coder:30b   # runs `ollama pull` on the node
$PY -m geoagent.core.eth_cluster use  qwen3-coder:30b   # sets the eth_hybrid model
```

Then update the ETH agents' `model` in `suite/agents.json` (or edit them) to the tag you
pulled, and run:

```bash
$PY -m local_agent.suite run --mode live --agents eth-ollama eth-docs eth-upskilled eth-both --out runs/eth
$PY -m local_agent.suite report runs/eth/*.log
```

> **Model recommendations are unverified priors** (a 2026-07 web scan; tags drift, so
> `ollama pull` may need a nearby tag). The only authority is your own sweep — `probe`
> gives you a shortlist to test, `run`/`report` give you the verdict. Sources:
> [Morph — Ollama models by VRAM & SWE-bench](https://www.morphllm.com/best-ollama-models),
> [Local AI Master — Ollama models for agents](https://localaimaster.com/blog/best-ollama-models-for-agents),
> [techsy — open-source LLM leaderboard, Jul 2026](https://techsy.io/en/blog/best-open-source-llms-2026).

---

## 3. With / without upskilling and docs (the A/B you asked for)

Because the conditions are separate agents, an A/B is just selecting them. From the UI: in
**GeoAgent Settings → Model**, the *Upskilling* and *Inject API docs* checkboxes toggle the
same two axes for the interactive chat (§ plugin UI). From the CLI:

```bash
# isolate each axis against the same backend
$PY -m local_agent.suite run --mode live --agents eth-ollama eth-upskilled --out runs/ab_upskill
$PY -m local_agent.suite run --mode live --agents eth-ollama eth-docs      --out runs/ab_docs
$PY -m local_agent.suite report runs/ab_upskill/*.log runs/ab_docs/*.log
```

Read the telemetry's **tool-call arguments**, not just the pass column — the dominant
local-model failure is the right tool with the wrong argument names, and that is exactly
what the operations guide and the API docs are there to fix.

---

## 4. One-glance cheatsheet

```bash
PY=~/.open_geoagent/venv_py3.12/bin/python

$PY -m local_agent.suite list                       # all agents + what they inject
$PY -m local_agent.suite status                     # LM Studio + ETH backend snapshot
$PY -m local_agent.suite budget "<prompt>"          # context/cost per agent, no backend
$PY -m local_agent.suite provision lmstudio|eth     # bring a backend up
$PY -m local_agent.suite run --mode plan            # fit + cost sweep, no model
$PY -m local_agent.suite run --mode live --out DIR  # real sweep on mock KADAS
$PY -m local_agent.suite report DIR/*.log           # token/cost/latency/pass table

$PY -m geoagent.core.eth_cluster login|up|probe|pull <m>|use <m>|doctor
```
