# OPERATIONS.md — the operations & decision-pathways reference

This is the **authoritative, hand-authored** guide to how the GeoAgent should drive
KADAS/QGIS: for each kind of task, which tool pathway to take, with the exact argument
names, and where the boundaries are. It is the source of truth that requirement #3 asked
for, and it **replaces the telemetry-to-skill auto-generation** in `upskill.py`.

It is written for two readers:

- a **maintainer** deciding what guidance a local model should receive, and
- the **`SKILL.md` pathway files** under `skills/`, which are the machine-readable slices
  of this document that `skills/selector.py` injects per prompt.

If a pathway here and a `SKILL.md` disagree, this document wins; fix the `SKILL.md`.

---

## 1. Why curated, not auto-generated

The previous strategy was: run Claude in KADAS, record telemetry, and have
`upskill.py generate` distil a `SKILL.md` per topic from the log. It did not work, and the
worst example (`skills/kadas-map-ops/SKILL.md`) has now been **deleted** along with the
other per-topic files. What it produced, for the record:

- A "**Preferred tools by observed frequency**" table (`run_pyqgis_script` used 98×,
  `remove_layer` 53×) that measured *what a past session happened to do*, not *what the
  right pathway is*. `run_pyqgis_script` topping the list is a **failure signal** — the
  escape hatch got used because dedicated tools were missed — yet the skill presented it as
  the preferred tool. That teaches the wrong lesson.
- "**Worked examples**" with the prompt `"Use the recent conversation history for
  context…"`, because the generator could not recover the real user turn from the log.
- The same shallow table on every regeneration: volume, not insight.

**The replacement is a single cohesive, tiered file:** `skills/kadas-operations/SKILL.md`.
It is hand-authored and **general** — it says "to move the map to a named place call
`locate_and_zoom` once", never "zoom to Zurich". It states the argument-name traps
(`lon`/`lat` not `x`/`y`, `target_epsg` not `target_crs`, `radius_m` is metres) and the
"one tool, not a chain" rules that actually fix local-model behaviour. Those facts cannot
be counted out of a log; they must be known and written down. The file is split into nested
tiers (`core` → `extended` → `reference`) and injected at the depth that fits the model's
context window (`skills/operations.py`; see §5).

**So the policy is:** operations knowledge lives here and in that one guide.
`upskill.py generate` is deprecated (it prints a pointer to this file). Telemetry is still
valuable — but as **input to a human deciding what to write here**, via `trace_from_log.py`,
not as an automatic skill factory.

---

## 2. The tools-vs-freedom policy (requirement #4)

The balance the agent should strike, in one rule: **prefer the narrowest dedicated tool
that does the job; treat `run_pyqgis_script` as a gated last resort.**

| Situation | Do |
|---|---|
| A dedicated tool exists (see the pathways below) | Use it. It has correct CRS handling, GUI-thread marshalling, and confirmation gating built in. |
| Several dedicated tools chain to the goal | Chain them in the canonical order (§3). Do not collapse the chain into a script. |
| No dedicated tool, task is a standard geoprocessing op | `run_processing_algorithm` (QGIS Processing) before any hand-written code. |
| No tool and no algorithm | `run_pyqgis_script` — **confirmation-gated**, AST-validated (`qgis`/`math` imports only; `eval`/`exec`/`open`/`__import__` blocked). |
| The capability is genuinely absent (e.g. MilX symbol lookup, §3.7) | Say so plainly. Do not fabricate a tool call or claim success. |

On **context** (the freedom to see the whole tool surface): at a 32k window the full
62-tool KADAS surface is ~39% of the budget and a 7B picks correctly from all of it, so
**do not pre-narrow the tool list per task** — that both solves a problem that no longer
exists and leaks the answer (handing a "list the layers" task exactly `[list_project_layers]`
means the model cannot choose wrong). Narrow the surface (`fast=True`, or the
`suite budget --no-adapt` recommendations) **only** when a small-window model actually
overflows. See `local_agent/README.md` and `suite/budget.py`.

---

## 3. The pathways

Every coordinate argument is **WGS84 `lon, lat` in degrees** (longitude first); the tools
project to the LV95 project CRS internally. Every `*_m` argument is **metres** (5 km =
`5000`). LV95 easting ≈ 2.6M, northing ≈ 1.2M — a value outside that is a bug.

The canonical call sequences below are the `expected_api_calls` in
`tests/qgis_kadas_benchmarks.json`; that file is the executable form of this section.

### 3.1 Layer management
- **List layers:** `list_project_layers()`. Just answer — do not add layers first.
- **Remove all:** `list_project_layers` → `remove_layer(layer_name=…)` per layer →
  `list_project_layers` to confirm empty. `remove_layer` takes `layer_name`, not an index.
- **Add OSM basemap:** `add_osm_basemap()`. Fall back to
  `add_xyz_tile_layer(url, name, attribution, zmin, zmax)` only for a non-OSM tile source.

### 3.2 Coordinate search & conversion
- **Move the map to a place:** `locate_and_zoom(query)` — one call, geocode + zoom.
  Do **not** chain `search_location` → `set_center` → `set_scale`.
- **Get coordinates without moving:** `search_location(query)`.
- **Convert:** `convert_coordinates(lon, lat, target_epsg=2056)`. **Never** do the maths
  yourself — this is the single most common failure. Arg is `target_epsg`, not `target_crs`.

### 3.3 Drawing / redlining
- **Marker with label:** `add_map_marker(lon, lat, label=…)` — the label is an argument;
  do not add a separate `add_text_annotation`.
- **Circle:** `add_map_circle(lon, lat, radius_m)`. **Resolve the place first**
  (`search_location`), then draw.
- **Rectangle:** `add_map_rectangle(min_lon, min_lat, max_lon, max_lat)`.
- **Colour/weight/style: not possible.** No styling argument exists. If asked for a "red"
  marker, place it and **say you cannot set the colour** — never claim you did.

### 3.4 swisstopo / geoadmin layers
- **Load a named swisstopo layer:** `search_geoadmin_catalog(query)` →
  `load_geoadmin_layer(layer_id)`. Inspect with `get_geoadmin_layer_info` if unsure.

### 3.5 Terrain analysis
- **Elevation at a place:** `search_location` → `get_elevation_at(lon, lat)`.
- **Hillshade:** `search_geoadmin_catalog` → `load_geoadmin_layer` (a DTM) →
  `create_hillshade_layer`.
- **Line of sight:** `search_location` (both endpoints) → `convert_coordinates` →
  `check_line_of_sight`.

### 3.6 OSM features
- **Find features:** `query_osm_features(...)` (Overpass). This returns and can add the
  features; you usually do not need a separate `search_location` first.

### 3.7 MilX / military symbols  (a boundary, not a pathway)
- **There is no `add_milx_symbol` tool. Do not invent one.** The symbol-lookup API
  (`KadasMilxClient.getSymbolMetadata`) is not bound to Python, so turning a symbol *name*
  into a placeable MSS string is **not reachable**. `run_pyqgis_script` cannot help:
  `import kadasgui` is rejected by the AST allowlist.
- **What works is read-only:** `list_kadas_annotation_layers`, `get_kadas_layer_items`,
  and counting symbols in existing MilX layers. For "place symbol X", explain the gap.

### 3.8 The escape hatches (last resort)
- **Standard geoprocessing:** `list_processing_algorithms` / `describe_processing_algorithm`
  → `run_processing_algorithm(algorithm_id, params)`.
- **Anything else:** `run_pyqgis_script(script)` — confirmation-gated, `qgis`/`math` imports
  only. Used for the composite H04-style tasks (buffer → clip DTM → zonal max) that no
  single tool covers.

---

## 4. How to maintain this (the new upskilling loop)

1. Run real sessions; collect `~/.kadas/agent_execution.log`.
2. `python local_agent/trace_from_log.py` → a readable trace. **Read it yourself.**
3. When you find a systematic failure (wrong arg name, needless chain, a fabricated tool),
   **write the fix in two places**: this document (§3) and the single injected guide
   `skills/kadas-operations/SKILL.md`. Put a universal rule in its `<!-- TIER: core -->`
   block (always injected); put a category pathway in `<!-- TIER: extended -->`.
4. Verify with `python -m local_agent.suite run --ids <id> --mode live`, and check the
   tool-call **arguments** in the telemetry — the arguments are the point.
5. Do **not** run `upskill.py generate`. It is deprecated; step 3 is the replacement.

There is now **one** machine-readable guide, and it is **shipped** so the plugin can inject
it too (the plugin cannot import `local_agent`):

| File | Role |
|---|---|
| `geoagent/core/kadas_operations_guide.md` | The cohesive, tiered operations guide. **Single source of truth.** Edit here. |
| `geoagent/core/operations_guide.py` | Shipped tier-slicer (`build_block(max_tokens)`). Used by the plugin **and** the harness. |
| `local_agent/skills/operations.py` | Thin delegate to the shipped module (back-compat for the suite/CLI). |

## 5. Context-adaptive injection (requirement: "depends on the agent context size")

The guide is nested in three tiers, cheapest first:

| Tier | Content | When injected |
|---|---|---|
| `core` | The argument conventions + the tool-vs-freedom / last-resort rule. | Whenever it fits (it is small; ~a few hundred tokens). |
| `extended` | The intent → tool catalog and the capability limits. | When the window has room after tools + system + docs. |
| `reference` | How the injected API reference relates to this guide. | Only on a large-context model. |

`suite/budget.py` computes the leftover budget after the fixed base (system prompt + tool
schemas + any `api_docs` + the prompt), caps it at `UPSKILL_MAX_FRACTION` of the usable
window to preserve headroom, and `geoagent.core.operations_guide.build_block(max_tokens)`
returns the largest tier prefix that fits. The live plugin chat does the same in
`chat_dock._apply_agent_guidance` (full guide, or `core` only in fast mode). Net effect:
**Claude / a 131k llama gets the whole guide; a 7B whose tool schemas already fill its 8k
window gets only `core`.** Preview it with:

```bash
python local_agent/skills/operations.py --max-tokens 400   # what a small model sees
python local_agent/skills/operations.py                    # the whole guide
```

## 6. Injected API documentation (the documancer)

Separately from the operations guide, `geoagent.core.context_docs` injects the **slice of
the API** a prompt is about — retrieved by keyword from the shipped doc packs in
`geoagent/docs/*.md`. This keeps context from blowing up: a prompt about elevation gets the
terrain classes, not the whole API. KADAS packs are generated by
`local_agent/docs/gen_kadas_docs.py`; **PyQGIS packs** (for `run_pyqgis_script`) by
`local_agent/docs/gen_qgis_docs.py`, which introspects the installed QGIS so signatures are
real, never invented. Run the QGIS generator once inside QGIS/KADAS:

```bash
python local_agent/docs/gen_qgis_docs.py --stats   # preview sizes
python local_agent/docs/gen_qgis_docs.py           # write qgis-*.md packs
```

Both injections are toggled per prompt in **GeoAgent Settings → Model** ("Inject API docs",
"Apply operations guidance"), gated to the KADAS/QGIS agent modes.
