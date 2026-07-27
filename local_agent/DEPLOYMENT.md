# Local Agent — Upskill & Deployment Guide

This folder is an **isolated experimentation scope**. Nothing here is imported by
the shipped `geoagent` package or the KADAS plugin at runtime; it exists to turn
recorded GeoAgent sessions into reusable *skills* and to test them against a
local LLM before anything is promoted to production.

The whole loop is: **run GeoAgent → collect telemetry → distil SKILL.md →
bundle → inject into the system prompt → test.**

```
~/.kadas/agent_execution.log   (JSONL telemetry, written by geoagent.core.telemetry)
        │  trace_from_log.py           (JSONL → readable Markdown trace)
        ▼
   trace.md
        │  upskill.py generate         (telemetry → skills/<slug>/SKILL.md)
        ▼
   skills/<slug>/SKILL.md
        │  upskill.py bundle           (all skills → one prompt fragment)
        ▼
   skills/skills_prompt.md ───────────► injected into GeoAgent system prompt
```

Everything is standard-library Python ≥ 3.10, so it runs in either the GeoAgent
venv or the local `.venv` here.

---

## 0. One-time setup

```bash
cd local_agent
uv venv                 # or: python -m venv .venv
source .venv/bin/activate
```

No third-party dependencies are required for `trace_from_log.py` /`upskill.py`.
(The `fast-agent` bits — `main.py`, `fast-agent.secrets.yaml` — are only needed
if you also want to drive a local model; see step 5.)

> ⚠️ **Secrets:** `fast-agent.secrets.yaml` currently contains real API keys.
> Rotate them and keep the file out of git — see the note at the bottom.

---

## 1. Collect telemetry

Telemetry is written whenever GeoAgent runs with logging enabled. In KADAS this
is `for_kadas(..., enable_logging=True)`; the log lands at
`~/.kadas/agent_execution.log` (override with `GEOAGENT_LOG_DIR`).

Use GeoAgent normally for the workflows you want it to get good at (loading
swisstopo layers, pinning places, styling, OSM queries, …). Each turn is
appended as JSONL events (`turn_start`, `tool_call`, `tool_result`, `turn_end`).

The **"Training AI"** panel in the KADAS dock (Developer mode) writes companion
human ratings to `~/.kadas/agent_feedback.log` — use it to mark which answers
were good/bad so you know which turns are worth distilling.

## 2. (Optional) Render a readable trace

```bash
python trace_from_log.py                 # ~/.kadas/... → ./trace.md (clean turns only)
python trace_from_log.py --all           # keep failed turns too
```

## 3. Generate a skill from the telemetry

```bash
python upskill.py generate --name kadas-map-ops \
    --description "Common KADAS map operations"
# → skills/kadas-map-ops/SKILL.md
```

`generate` reads the log, keeps only **clean** turns (reached `turn_end`, no
error), counts tool usage, and embeds a few successful turns as worked examples.
Then **edit the generated `SKILL.md` by hand** — trim noise, tighten the
guidance. The generator gives you a scaffold, not a finished skill.

You can also hand-author a skill:

```bash
python upskill.py register --name swiss-cadastre \
    --description "How to load property boundaries" --body-file my_notes.md
```

List / remove:

```bash
python upskill.py list
python upskill.py remove --name kadas-map-ops
```

**Isolation guarantee:** every write is confined to `local_agent/skills/`. The
`--name` is slugified (path separators stripped) and re-checked against the
`skills/` root in `_skill_dir`, so a skill can never be written outside this
folder.

## 4. Bundle skills for injection

```bash
python upskill.py bundle          # → skills/skills_prompt.md
```

This concatenates every `SKILL.md` into one prompt fragment.

## 5. Test with / without the skill

1. **Baseline:** run the local model on a task *without* the bundle and note
   where it fumbles.
2. **Injected:** prepend `skills/skills_prompt.md` to the GeoAgent system
   prompt and re-run the same task.

### Injecting a skill file straight from the KADAS UI

The KADAS dock can inject a skill file with no code. In **Developer mode**, the
**Training AI** panel has an **"Upskill with:"** row — click **Browse…** and pick
a `SKILL.md` or a bundled `skills_prompt.md`. From then on, that file's contents
are prepended to every request as extra guidance (re-read each turn, so edits
take effect live), and the selection persists across sessions (QSettings key
`kadas_geoagent/skill_file`). Click **Clear** to stop injecting. This is the
fastest way to A/B a freshly generated skill before promoting it.

To inject in code, pass the bundle as extra system guidance. GeoAgent already
accepts a composed system prompt (see `factory.KADAS_SYSTEM_PROMPT`); for local
experiments the simplest hook is:

```python
from pathlib import Path
from geoagent.core import factory

skills = Path("local_agent/skills/skills_prompt.md").read_text()
factory.KADAS_SYSTEM_PROMPT = factory.KADAS_SYSTEM_PROMPT + "\n\n" + skills
agent = factory.for_kadas(iface, enable_logging=True)
```

> This monkeypatch is deliberately confined to a local test harness — do **not**
> commit it into the plugin. Promotion to production means folding the distilled
> guidance into the real system prompt via a normal PR.

---

## Promoting a skill to production

A skill proven useful here graduates by **editing the shipped system prompt**
(or adding a dedicated tool) in `geoagent/`, reviewed as a normal change — never
by shipping `local_agent/` itself. That keeps the experimentation scope and the
product cleanly separated.

## Files in this folder

| File | Purpose |
|------|---------|
| `trace_from_log.py` | JSONL telemetry → Markdown trace |
| `upskill.py` | Isolated skill manager (generate/register/list/bundle/remove) |
| `skills/` | Generated & hand-authored `SKILL.md` files (isolated scope) |
| `main.py`, `fast-agent.secrets.yaml`, `.fast-agent/` | Optional local-model driver |
| `LOCAL_LLM.md` | Checklist for the local-LLM upskill test |

## Security note — rotate the committed keys

`fast-agent.secrets.yaml` contains live-looking `sk-proj-…` (OpenAI) and
`sk-ant-…` (Anthropic) keys. **Rotate both**, then keep the file untracked:

```bash
git rm --cached local_agent/fast-agent.secrets.yaml
echo "local_agent/fast-agent.secrets.yaml" >> .gitignore
```

The KADAS plugin always bills the user's own configured provider key — these
local dev keys must never reach it.


LITELLM_BASE_URL + LITELLM_MODEL="openai/qwen2.5-7b-instruct" + LITELLM_API_KEY=lm-studio