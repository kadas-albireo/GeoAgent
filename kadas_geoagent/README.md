# OpenGeoAgent Kadas Plugin

## TODO
- [ ]  clean up loading layer function
- [ ]  make open_geoagent a declared, installable dependency to kill the sys.path discovery
- [ ]  promote the ~6 internals KADAS depends on into a documented public extension surface.
- [ ]  Add multilingual support for geoadmin
- [ ] Finish chat logging to see how tokens are being used


A KADAS Albireo 2 port of [OpenGeoAgent](../../qgis-plugins/GeoAgent). It brings
the GeoAgent multimodal AI chat surface into KADAS as a dockable panel.

## Architecture

KADAS GeoAgent uses agent and UI logic of GeoAgent with a wrapper around to adapt for Kadas

```
geoagent/                      shared agent core (pip dependency, host-agnostic)
qgis-plugins/GeoAgent/
  qgis_geoagent/open_geoagent/ shared chat/settings dock widgets (+ deps installer)
kadas-plugins/kadas-geoagent/
  kadas_geoagent/              KADAS wrapper (this plugin)
    kadas_iface_adapter.py     KadasPluginInterface  ->  QGIS iface surface
    _shared.py                 locates and imports open_geoagent
    kadas_geoagent.py          ribbon registration + dock hosting
```

### Adapter Interface

GeoAgent's QGIS tools and the OpenGeoAgent dock widgets were written against the
vanilla QGIS `QgisInterface` (`iface`). KADAS hands plugins a
`KadasPluginInterface`, which mirrors the navigation surface
(`mapCanvas`, `mainWindow`, `messageBar`, `addAction`) but **lacks** the
layer-management helpers QGIS adds (`addVectorLayer`, `addRasterLayer`,
`activeLayer`, `setActiveLayer`, `zoomToActiveLayer`, `showAttributeTable`).

`KadasIfaceAdapter` fills that gap by implementing the missing methods against
`QgsProject` and the map canvas (both identical between QGIS and KADAS) and
delegating everything else to the wrapped KADAS interface. `geoagent.for_qgis()`
and `ChatDockWidget(iface, ...)` then run unchanged.

The shared dock widgets were verified to call only `activeLayer`,
`setActiveLayer`, `mapCanvas`, `mainWindow`, and `messageBar` on `iface` — all
provided by the adapter.


## Logging

Every agent turn can be recorded as a replayable trace.

**Enable it:** switch the chat dock to **Developer mode**. Full LLM trace logging is
implied by Developer mode; there is no separate toggle.

**Where:** one JSONL file (one JSON object per line) at
`~/.kadas/agent_execution.log` (override the directory with `$GEOAGENT_LOG_DIR`).
Tail it live with `tail -f ~/.kadas/agent_execution.log`, or use the dock's
**Logs** button to open the folder.


## Kadas Port Plugin

- `geoagent/__init__.py`
- `geoagent/tools/__init__.py`
- `geoagent/core/factory.py`
    - creates a geoagent instance for different workflows
    - added in `for_kadas()` function that creates an agent bound to Kadas
        - uses `KADAS_SYSTEM_PROMPT`
            
            ```jsx
            KADAS_SYSTEM_PROMPT = """\
            You are an AI assistant embedded in KADAS Albireo 2 a QGIS-based mapping
            application used mainly with Swiss swisstopo geodata. You have the standard
            QGIS layer/canvas tools PLUS KADAS-specific tools for the swisstopo geoadmin
            catalog, place-name search, and KADAS-native map annotations. Prefer these
            dedicated tools over writing PyQGIS by hand.
            
            How KADAS operates (use this to choose tools):
            - KADAS does not ship a fixed layer list. The layer catalogue the user browses
              is the live swisstopo geoadmin catalog (886 layers), and place search uses
              the geoadmin SearchServer. Coordinates the user gives are WGS84 lon/lat;
              Swiss local data is usually in LV95 (EPSG:2056). The default basemaps are
              swisstopo WMTS tiles (national maps, SWISSIMAGE aerial, hillshade).
            
            Catalog & data loading:
            - To find a layer for a topic ("aerial photos", "electric stations", "property
              boundaries", "railways"), call search_geoadmin_catalog to resolve the topic
              to a layerBodId, then load_geoadmin_layer with that bod_id. Do not guess
              bodIds.
            - load_geoadmin_layer is the ONLY correct way to add a swisstopo/geoadmin layer:
              it loads via the official WMS service exactly like the KADAS geocatalog. NEVER
              load swisstopo layers with add_xyz_tile_layer, add_raster_layer, or a
              hand-built WMTS/XYZ tile URL (e.g. .../{z}/{x}/{y}.png). Those use the wrong
              tiling scheme/CRS for the swisstopo grid and render as a blank layer. If
              load_geoadmin_layer fails, report the error — do not fall back to a tile URL.
            - Known mappings you can use directly: aerial/SWISSIMAGE ->
              ch.swisstopo.swissimage-product; national map (colour) ->
              ch.swisstopo.pixelkarte-farbe; hillshade ->
              ch.swisstopo.swissalti3d-reliefschattierung; cadastre/property boundaries ->
              ch.kantone.cadastralwebmap-farbe.
            - For local files the user names, use the QGIS add_vector_layer /
              add_raster_layer tools.
            
            Place search / navigation:
            - To find a place ("Matterhorn", "Basel main station", "Thunplatz, Bern"), call
              search_location to get WGS84 coordinates and a bbox, then center/zoom with the
              QGIS set_center / zoom_to_extent tools, or use locate_and_zoom for a one-shot
              recentre. Never fabricate coordinates.
            
            KADAS-native annotations (markers and shapes):
            - Use the dedicated KADAS tools, NOT QgsAnnotation or temporary vector layers:
              add_map_marker (pins/markers), add_text_annotation (labels), add_map_circle
              (radius in metres), add_map_rectangle (bbox), add_map_polygon. All take WGS84
              lon/lat. clear_annotations removes the agent's annotation layer and requires
              confirmation.
            - A common pattern is search_location -> add_map_marker to pin a named place.
            
            Reading KADAS-native layers (Pins, GPX, annotations):
            - These are QgsAnnotationLayer layers holding drawable KADAS annotation items,
              not QGIS vector features, so list_project_layers only sees their extent/
              bounding box. To
              understand their contents — including each item's coordinates — call
              list_kadas_item_layers to discover them, then get_kadas_layer_items(layer_name)
              to read every item's type, label, and WGS84 lon/lat. Do not report only a
              layer's bounding box when the user asks about the items inside it.
            
            - When a request truly has no dedicated tool (custom processing, raster
              band/labeling tweaks), write a short PyQGIS script and run it with
              run_pyqgis_script rather than refusing.
            - Keep responses concise and include the tool name, resolved bodId/coordinates,
              and loaded layer or annotation names when available.
            """
            ```
            
        - includes geoadmin catalog
        - includes kadas native annotation tools
- `geoagent/tools/geoadmin.py` → **NEW FILE**
    - same structure as `qgis.py`
    - `def geoadmin_tools(iface)` takes in the QGIS python bridge interface (in `factory.py`)
        - builds callable tool functions for factory
    - Catalog searching
        - `search_geoadmin_catalog()`
            - `def _search_catalog(query string, limit)`
                - loads `layersConfig` in English
                - normalizes query to lowercase and splits into tokens
                - for each layer
                    - builds record
                    - scores with how closely query matches layer (token found in label)
                - DOES NOT SUPPORT MULTILANGUAGE
            - `_layers_config()` fetches adn caches geoadmin layer catalog
            - `_fetch_json(LAYERS_CONFIG_URL)`
                
                ```jsx
                LAYERS_CONFIG_URL = (
                    f"https://{GEOADMIN_HOST}/rest/services/ech/MapServer/layersConfig"
                )
                ```
                
            - `_layer_record` (cleans json for ranking) and `score_layer` returns matching and `layerBodId`
    - Layer Loading
        - `load_geoadmin_layer` loads layer into project as WMS raster using the `iface.addRasterLayer`  function and `iface.setActiveLayer` function(), this is the tool entrypoint
        - TODO: this needs to be cleaned up
        - `_run()`  GUI thread
            - pick target crs
            - `def _wms_layer_uri()`
                - builds QGIS WMS provider connection string to load a swisstopo layer
            - addRasterLayer
- `geoagent/tools/[kadas.py](http://kadas.py)` **NEW FILE**
    - Initialization of tools for Kadas specific agent that get’s called when user instantiates plugin for kadas in the factory
        - Because Kadas api is not exposed, I use the definitions from here
            - `kadas-albireo2/python/kadasgui/` from the SIP files
- `kadas_geoagent/kadas_geoagent/__init__.py` entrypoint for kadas plugin
- `kadas_geoagent/kadas_geoagent/_shared.py`
    - lets shared UI package be imported into kadas geoagent
    - geoagent = shared agent/core logic
    - opengeoagent = shared dock/chat/settings UI
    - kadas_geoagent = KADAS specific wrapper


