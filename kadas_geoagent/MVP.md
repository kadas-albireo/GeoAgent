# KADAS GeoAgent — the MVP

What the minimum viable product is, what it took to build, and what it can and
cannot do today. For the install procedure see [SETUP.md](SETUP.md); for the rule
set that keeps it working across KADAS releases see [EXTENDING.md](EXTENDING.md).

---

## 1. The product in one sentence

A dockable AI chat panel inside KADAS Albireo 2 that can **operate the map** —
load swisstopo layers, draw and style annotations, run terrain analysis, measure,
and answer questions about what is on screen — driven by the user's own LLM key.

## 2. What "minimum viable" means here

The MVP bar is: **a non-technical KADAS user can ask for a map operation in plain
language and get it done, without writing PyQGIS.**

Three consequences follow, and they shaped every design decision:

1. **Dedicated tools beat generated code.** A `run_pyqgis_script` fallback exists
   but is confirmation-gated and AST-restricted. Anything a user asks for
   routinely should be a real tool with typed arguments, because generated PyQGIS
   fails silently and is unreviewable by the target user.
2. **The agent must never lie about its limits.** A stale "I can't do that" is
   worse than an error: the user believes it and stops asking. This was the single
   biggest defect class found (see §6).
3. **It must bill the user's own provider key**, never a vendor account.

## 3. Architecture — the four pieces

```
geoagent/                     the shared, host-agnostic pip package
  core/factory.py             for_kadas() + KADAS_SYSTEM_PROMPT + assemble_tools()
  tools/<surface>.py          one module per tool surface, closure-bound to iface
qgis_geoagent/open_geoagent/  the shared chat + settings dock widgets
kadas_geoagent/               the KADAS wrapper (this package)
  kadas_iface_adapter.py      KadasPluginInterface -> QGIS iface surface
  user_chat_dock.py           simple "user mode" front end over the shared dock
```

**The one hard problem the wrapper solves:** KADAS hands plugins a
`KadasPluginInterface` that lacks QGIS' layer helpers (`addVectorLayer`,
`activeLayer`, `showAttributeTable`, …). `KadasIfaceAdapter` implements the
missing methods against `QgsProject` and the canvas and delegates the rest, so
`for_qgis()` and the shared dock widgets run **unchanged**. That single adapter is
what makes this a port rather than a fork.

**Tool assembly** is a 3-stage filter in `assemble_tools()`:
`_filter_by_imports` (drop tools whose packages are missing) →
`_filter_by_permission` (apply the security profile) → `_drop_tools_by_name`
(per-host exclusions), plus a `fast` subset for low-latency models.

## 4. What it took to build

| Layer | Work |
|---|---|
| **Host adaptation** | The iface adapter; locating `open_geoagent` on KADAS' path (`_shared.py`) |
| **Deployment** | Per-Python-version venvs under `~/.open_geoagent/`, editable via `.pth`, because `geoagent` is a pip dependency and KADAS bundles its own Python 3.13 |
| **Tool surfaces** | swisstopo geoadmin catalog + place search, KADAS-native annotations, OSM/Overpass, external-folder browsing, terrain analysis, measurement, capabilities |
| **Prompt engineering** | `KADAS_SYSTEM_PROMPT` plus a tiered operations guide, and keyword-retrieved API docs generated from KADAS' SIP bindings |
| **UI** | A two-mode dock: a plain ask/answer view for users, the full developer panel behind one toggle |
| **Safety** | Confirmation hook, denied-by-default for destructive/long-running/paid tools |

## 5. Capability matrix (today)

| Area | Status | Entry point |
|---|---|---|
| Load swisstopo layers | ✅ | `search_geoadmin_catalog` → `load_geoadmin_layer` |
| Place search / coordinates | ✅ | `search_location`, `convert_coordinates` |
| Markers, text, shapes | ✅ | `add_map_marker`, `add_text_annotation`, `add_map_*` |
| **Annotation styling** | ✅ | colour/opacity/outline on shapes; colour/size/bold/font on text |
| **GPX waypoints & routes** | ✅ | `add_gpx_waypoint`, `add_gpx_route` |
| **Custom SVG symbols** | ⚠️ equivalent | `add_svg_marker` (QGIS SVG layer; KADAS' own item is not SIP-exposed) |
| **Item tooltips ("annotate")** | ✅ | `set_annotation_tooltip` |
| **Terrain: hillshade/slope/viewshed** | ✅ | `set_heightmap_layer` → `compute_*` (KADAS' own filters) |
| Line of sight, elevation | ✅ | `check_line_of_sight`, `get_elevation_at` |
| **Distance/azimuth, area** | ✅ | `measure_distance_bearing`, `measure_polygon_area` |
| Raster + vector symbology | ✅ | `set_layer_symbology` |
| OSM features | ✅ | `query_osm_features` |
| Geoprocessing | ✅ | `run_processing_algorithm`, `run_pyqgis_script` (gated) |
| MilX / military symbols | ❌ | symbol-lookup API not bound to Python |
| GPS / live position | ❌ | no tool; KADAS-side only (see §7) |

## 6. The defect class worth remembering

The most damaging bugs were **not** crashes. They were the agent confidently
refusing work it could do:

- The operations guide asserted annotation styling was "a hard limit with no API
  binding". In fact every `Kadas*AnnotationItem` subclasses a stock QGIS item, so
  styling is plain `setSymbol()`/`setFormat()`.
- `set_layer_symbology` was described as "simple layer symbology such as color and
  line width", which reads vector-only — so the agent refused raster restyling
  that the tool already implemented.
- Waypoints and routes have dedicated, SIP-exposed KADAS items, but no tool
  existed, so the agent silently degraded to generic annotations.

**Lesson:** tool docstrings and the operations guide are *executable policy*, not
documentation. Every negative claim in them must be justified against the SIP
bindings, and re-checked when KADAS moves.

## 7. Known gaps / next up

1. **GPS is unreachable from the agent.** KADAS wraps QGIS' GPS stack
   (`QgsGpsDetector` → gpsd / serial NMEA / Qt Location) and ships a simulator
   (`kadas --gps-simulator`). A tool surface reading
   `QgsApplication::gpsConnectionRegistry()` would let the agent reason about
   "where I am".
2. **`KadasSvgMarkerAnnotationItem` has no SIP entry** — KADAS-side fix needed for
   true parity with the Draw tab.
3. **MilX symbol lookup is unbound** — KADAS-side.
4. **Help button is broken in KADAS** — `kadashelpviewer.cpp` builds
   `"http:///%1:%2/%3/"` (three slashes → empty host); `share/docs/html` is also
   absent.
5. **No live-KADAS integration test.** Everything is unit-tested against mock
   hosts and verified against the KADAS/QGIS sources, but nothing exercises a
   running KADAS. This is the largest remaining risk.

## 8. Verifying the MVP works

```bash
./kadas_geoagent/install_kadas_geoagent.sh   # plugin symlink, editable venv, DTM
~/.open_geoagent/venv_py3.12/bin/python -m pytest tests/ -q   # 386 passing
```

Then in KADAS, a smoke sequence that touches every major surface:

1. "Load the swisstopo aerial imagery layer."
2. "Draw a semi-transparent red circle 500 m around Bern and label it."
3. "Add a GPX route from Bern to Thun to Interlaken."
4. "Set DTM CH 10m as the heightmap, then compute a hillshade."
5. "How far and what bearing from Bern to Zurich?"
