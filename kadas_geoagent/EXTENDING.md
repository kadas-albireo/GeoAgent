# Keeping GeoAgent in step with KADAS

The problem: every KADAS release can add, rename or remove capabilities, and a
hand-maintained tool list drifts silently. The agent then either misses new
functionality or, worse, confidently tells users something is impossible when it
isn't. That failure already happened here — the operations guide asserted
annotation styling had "no argument", long after the annotation rewrite made it
plain QGIS `setSymbol()`.

The strategies below are ordered by leverage.

---

## 1. Prefer the stock QGIS API over KADAS-private API

**This is the highest-leverage rule, and it is under-exploited.**

KADAS' 2026 annotation rewrite moved everything onto stock QGIS base classes:

| KADAS item | Base class | Styling entry point |
|---|---|---|
| `KadasCircleAnnotationItem` | `QgsAnnotationPolygonItem` | `setSymbol(QgsFillSymbol)` |
| `KadasRectangleAnnotationItem` | `QgsAnnotationPolygonItem` | `setSymbol(QgsFillSymbol)` |
| `KadasPinAnnotationItem` | `QgsAnnotationMarkerItem` | `setSymbol(QgsMarkerSymbol)` |
| `KadasGpxWaypointAnnotationItem` | `QgsAnnotationMarkerItem` | `setSymbol(QgsMarkerSymbol)` |
| `KadasGpxRouteAnnotationItem` | `QgsAnnotationLineItem` | `setSymbol(QgsLineSymbol)` |
| `KadasCoordCrossAnnotationItem` | `QgsAnnotationMarkerItem` | `setSymbol(QgsMarkerSymbol)` |

Anything written against the **base** class keeps working when KADAS changes the
subclass. QGIS' API is far more stable than KADAS' and is versioned publicly.

Same pattern for analysis: KADAS' measure tools are just `QgsDistanceArea`
(`measureLine`, `bearing`, `measurePolygon`). Reimplementing them is exact and
immune to KADAS UI churn.

**Rule:** before adding a KADAS-specific binding, check the base class. If the
capability is reachable through QGIS, bind it there.

## 2. Treat state as project entries, not tool arguments

KADAS keeps cross-tool state in `QgsProject` entries. The heightmap is the clearest
case: hillshade, slope, viewshed, line-of-sight and the height profile all read

```python
QgsProject.instance().readEntry("Heightmap", "layer")
```

There is no per-tool DTM argument. Discovering the *entry* rather than wrapping
each *tool* gave the agent all five capabilities at once, and new terrain tools
that follow the same convention work without any GeoAgent change.

**Rule:** when several KADAS tools share a setting, bind the setting.

## 3. Generate the API reference; never hand-write signatures

`local_agent/docs/gen_kadas_docs.py` generates `geoagent/docs/kadas-*.md` from
KADAS' SIP bindings, and `core/context_docs.py` retrieves the relevant slice into
the prompt tail at question time. Regenerating after a KADAS bump is a build step,
not a code change, and the agent gets real signatures instead of guesses.

**Make this a CI job**: regenerate on every KADAS bump and fail the build if the
diff touches a symbol GeoAgent binds. That converts silent drift into a red build.

## 4. Derive capability from the SIP bindings, not from belief

The SIP `%Include` lists are the authoritative statement of what Python can reach:

```
kadas-albireo2/python/kadasgui/kadasgui_auto.sip
kadas-albireo2/python/kadasanalysis/kadasanalysis_auto.sip
kadas-albireo2/python/kadascore/kadascore_auto.sip
```

If a class is absent there, it is genuinely unreachable and the honest answer is
"not exposed to Python — needs a KADAS-side change". If it is present, the agent
must not claim otherwise. `KadasSvgMarkerAnnotationItem` is the current example of
a real gap: the C++ exists, the SIP entry does not.

A cheap guard: a test that asserts the set of SIP-exposed classes GeoAgent depends
on is still present. It fails loudly on the KADAS bump that removes one, instead of
at runtime in front of a user.

## 5. Push gaps upstream rather than working around them

Where KADAS is the right place to fix something, fix it there — a workaround in
GeoAgent is a permanent maintenance liability. Current candidates:

- **Expose `KadasSvgMarkerAnnotationItem` to SIP** so custom SVG symbols are
  placeable. Today only the interactive Draw tab can create them.
- **Expose the MilX symbol-lookup API** so military symbols become reachable.
- **Fix the Help URL** in `kadas/app/kadashelpviewer.cpp:44`: it builds
  `"http:///%1:%2/%3/"` with three slashes, so `QUrl` parses an empty host and the
  path becomes `/127.0.0.1:PORT/en/`. `QDesktopServices::openUrl` then silently
  fails. (`share/docs/html` is also absent, so the content needs shipping too.)

## 6. Keep the guide honest, and let it fail open

The operations guide steers tool choice, so a stale "you cannot do X" is worse than
no guidance: the model obeys it and refuses valid work. Two habits:

- State limits only where the SIP bindings prove them, and cite the reason.
- Prefer "try it and report the error" over a blanket refusal. A tool that returns
  a structured error teaches the user something; a refusal invented from a stale
  document does not.

## 7. Bind capabilities, not UI actions

`trigger_kadas_action` can fire KADAS UI actions, but interactive map tools then
wait for a human click the agent cannot supply. Wrapping the ribbon is therefore a
dead end for automation. Bind the computation underneath the action instead — the
same conclusion as §1 and §2, arrived at from the UI side.
