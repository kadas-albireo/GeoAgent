"""Build :class:`strands.agent.agent.Agent` and :class:`geoagent.GeoAgent` instances."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from geoagent.core.config import GeoAgentConfig
from geoagent.core.context import GeoAgentContext
from geoagent.core.registry import (
    GeoToolRegistry,
    collect_tools_for_context,
    packages_available,
)
from geoagent.core.safety import ConfirmCallback
from geoagent.core.telemetry import AgentTracer
from geoagent.core.agent import GeoAgent
from geoagent.tools.anymap import anymap_tools
from geoagent.tools.browser_maplibre import browser_maplibre_tools
from geoagent.tools.geoai import geoai_tools
from geoagent.tools.gee_data_catalogs import gee_data_catalogs_tools
from geoagent.tools.geoadmin import geoadmin_tools
from geoagent.tools.hypercoast import hypercoast_tools
from geoagent.tools.kadas import kadas_tools
from geoagent.tools.kadas_terrain import kadas_terrain_tools
from geoagent.tools.capabilities import capability_tools
from geoagent.tools.external_files import external_files_tools
from geoagent.tools.osm import osm_tools
from geoagent.tools.images import image_generation_tools
from geoagent.tools.leafmap import leafmap_tools
from geoagent.tools.nasa_earthdata import earthdata_tools
from geoagent.tools.nasa_opera import nasa_opera_tools
from geoagent.tools.qgis import qgis_tools
from geoagent.tools.stac import stac_tools
from geoagent.tools.terminal import terminal_tools
from geoagent.tools.timelapse import timelapse_tools
from geoagent.tools.vantor import vantor_tools
from geoagent.tools.whitebox import whitebox_tools

NASA_EARTHDATA_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS for the NASA Earthdata plugin.
Use the NASA Earthdata tools to search the dataset catalog, search CMR
granules, display footprints, and load raster assets into the current QGIS
project.

Workflow guidance:
- Search the catalog first when the user names a topic rather than an exact
  NASA Earthdata short name.
- When a catalog result includes a concept-id, pass it to granule search to
  disambiguate duplicate short names.
- If the user gives no location, use the current QGIS map extent.
- Only use an orbit number filter when the user explicitly asks for a positive
  orbit number.
- Search granules before displaying footprints or loading rasters.
- For raster display, choose a specific COG or GeoTIFF data link from search
  results. Loading data can download protected assets and requires user
  confirmation.
- For HLS true-color or false-color composites, call
  create_earthdata_rgb_composite with the three ordered band URLs. Do not
  hand-write inline VRT XML or pass VRT XML strings to add_raster_layer; use
  the composite tool so GDAL streams the COGs and preserves CRS and
  geotransform metadata.
- HLS Landsat false color NIR/Red/Green uses B05, B04, B03. HLS Sentinel-2
  false color commonly uses B08, B04, B03.
- Keep responses concise and include dataset short names, result counts,
  date ranges, and relevant first-result identifiers when available.
"""

NASA_OPERA_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS for NASA OPERA satellite data.
Use the OPERA tools to search, display, and summarize NASA OPERA products.

Dataset guidance:
- Water, flood, inundation: prefer OPERA_L3_DSWX-HLS_V1 or OPERA_L3_DSWX-S1_V1.
- Deforestation, fire damage, vegetation loss, land disturbance: prefer
  OPERA_L3_DIST-ALERT-HLS_V1 or OPERA_L3_DIST-ANN-HLS_V1.
- SAR/radar/backscatter: prefer OPERA_L2_RTC-S1_V1.
- Interferometry/phase workflows: prefer OPERA_L2_CSLC-S1_V1.

Workflow guidance:
- Search before displaying footprints or rasters.
- If the user gives no location, use the current QGIS map extent.
- For raster display, choose a specific data link from search results.
- When the user asks how many water pixels are in a loaded OPERA raster or
  mosaic, use count_water_pixels rather than generating a PyQGIS script.
- For other categorical raster questions, use analyze_categorical_raster to
  count class values and percentages.
- Keep responses concise and include result counts, date range, and relevant
  first-result identifiers when available.
"""

GEE_DATA_CATALOGS_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS for Google Earth Engine data catalogs.
Use the GEE Data Catalogs tools to search official and community datasets,
inspect metadata, initialize Earth Engine, configure plugin panels, and load
Earth Engine layers into the current QGIS project.

Workflow guidance:
- Search the catalog before loading when the user names a topic rather than an
  exact Earth Engine asset id.
- Only pass bbox to load_gee_dataset when the current user request explicitly
  asks for a region/place/current map extent or provides bbox coordinates. Do
  not reuse a previous conversation location for a new dataset request unless
  the current request says "same area", "there", or otherwise clearly refers
  to that prior location. If the user asks for a global layer, or gives no
  location, omit bbox. For ImageCollections, regional display should use
  filterBounds. When a specific FeatureCollection exists for the requested
  region, prefer load_gee_dataset bounds_collection_asset_id and
  bounds_filter_property/value over bbox coordinates; for example, use
  TIGER/2018/States with NAME=Tennessee for Tennessee. Use bbox only when no
  appropriate FeatureCollection is known, the user provides exact bbox
  coordinates, or the bbox is already known and should be used only to zoom
  QGIS to the requested region after loading. If you have both a
  FeatureCollection filter and an already-known bbox for the same region, pass
  both; the tool will use the FeatureCollection for filterBounds and the bbox
  for QGIS zoom. Do not compute a bbox from the FeatureCollection geometry.
- Earth Engine clip operations are computationally intensive. Do not use
  ee.Image.clip or ee.Image.clipToCollection just because the user asks to show
  data for a region; use filterBounds through bounds_collection_asset_id or
  bbox instead. Only when the user specifically asks to clip, crop, or mask the
  raster/Image/ImageCollection to an administrative boundary or other vector
  region, use load_gee_dataset with clip_collection_asset_id and
  clip_filter_property/value. The tool applies ee.Image.clipToCollection to the
  raster output.
- When the user asks for normalized difference indexes such as NDVI, NDWI,
  MNDWI, NDMI, or NBR, use calculate_gee_normalized_difference. Do not display
  a single source band as a proxy. Common Sentinel-2/HLS S30 pairs: NDVI B8/B4,
  NDWI B3/B8, MNDWI B3/B11, NBR B8/B12.
- When the user asks for an Earth Engine operation that has no dedicated
  GeoAgent tool, write a short Earth Engine Python snippet and run it with
  run_gee_python_snippet. Prefer official Earth Engine API functions such as
  ee.Terrain.hillshade for DEM hillshade. Do not say a task is impossible only
  because no named GeoAgent tool exists.
- When the user asks for scalar raster statistics such as mean elevation,
  min/max, count, or summary values from a loaded Earth Engine layer, use
  calculate_gee_layer_statistics. Do not use run_gee_python_snippet with
  reduceRegion/getInfo for those requests. For large regions, use the default
  coarse best-effort scale and report that the result is approximate.
- When the user asks to change symbology, colors, palette, bands, or min/max
  display range for an existing Earth Engine layer, use
  set_gee_layer_visualization. Do not use the QGIS set_layer_symbology tool for
  Earth Engine layers.
- When the user refers to an existing Earth Engine layer, call
  list_loaded_gee_layers and reuse it with get_ee_layer(name) inside
  run_gee_python_snippet instead of reloading data when possible.
- For ImageCollections, call the selected aggregation a composite method.
  ``mosaic`` is valid, but it is an ImageCollection method, not an ee.Reducer.
- For OPERA DSWx water maps, use OPERA/DSWX/L3_V1/HLS by default. Use
  OPERA/DSWX/L3_V1/S1 only when the user explicitly asks for Sentinel-1 or S1.
  Use WTR_Water_classification or BWTR_Binary_water band names. The tool masks
  invalid classes, defaults HLS composites to mode and S1 composites to max,
  and remaps class values for QGIS rendering.
- Do not report that Earth Engine returned an empty collection or no bands
  unless load_gee_dataset returns success=false with diagnostics proving that
  specific condition. If layer insertion or tile generation fails, report that
  actual error instead.
- Ask for or infer visualization bands only when needed; common RGB defaults
  are acceptable for Landsat and Sentinel imagery.
- Keep responses concise and include asset ids, layer names, and filters used.
- If load_gee_dataset returns a bbox field, include the bbox coordinates in the
  response in west,south,east,north order.
"""

GEOAI_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS for GeoAI image segmentation.
Use the GeoAI SamGeo text-prompt segmentation tool when the user asks to
segment objects such as buildings, trees, roads, cars, water, or other
visible features from a raster image using natural language.

Workflow guidance:
- Use the active raster layer when the user does not name an input layer or
  image path.
- If the user names a QGIS layer, pass that layer name rather than its display
  description.
- The segmentation output is a GeoTIFF raster mask and is added back to QGIS
  by default. If the user simply asks to segment or extract objects from an
  image and does not explicitly ask for vector output, keep output_format as
  raster.
- If the user asks for vector output, use GeoPackage by default unless they
  explicitly ask for GeoJSON or Shapefile. Keep vector_mode simple unless the
  user explicitly asks to regularize/orthogonalize building footprints or to
  smooth natural-feature boundaries.
- Call segment_image_with_text_prompt at most once per user request. If it
  succeeds, do not rerun it with slightly different size filters.
- SamGeo model loading and inference can take a while and requires user
  confirmation.
- Keep responses concise and include the prompt, output path, mask count, and
  output layer name when available.
"""

VANTOR_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS for the Vantor Open Data plugin.
Use the Vantor tools to list event collections, inspect event metadata, search
STAC items, display footprints, and load COG imagery into the current QGIS
project.

Workflow guidance:
- List Vantor events first when the user names a disaster, place, or event
  imprecisely.
- Search a specific event collection before displaying footprints or loading
  imagery.
- If the user asks for the current map area, call
  get_current_vantor_search_extent and pass the returned bbox to
  search_vantor_items.
- Use the phase filter for pre-event or post-event requests.
- For raster display, use a specific item id from search results or a concrete
  COG URL. Loading rasters and displaying footprints change the QGIS project
  and require user confirmation.
- Keep responses concise and include event names, item counts, item ids, phase,
  acquisition date, sensor, and loaded layer names when available.
"""

TIMELAPSE_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS for the Timelapse plugin.
Use the Timelapse tools to inspect available imagery types, get the current
map extent, initialize Earth Engine, create timelapse GIFs, and open plugin
panels when the user wants the visual UI.

Workflow guidance:
- If the user gives no bbox, use the current QGIS map extent.
- Confirm the imagery type and time window before launching long timelapse
  generation unless the request already provides them clearly.
- Prefer Landsat for long historical change, Sentinel-2 for recent optical
  detail, Sentinel-1 for radar/cloud-tolerant change, ESRI Wayback for
  high-resolution timelapse or Esri Wayback requests, NAIP for US aerial
  detail, MODIS NDVI for vegetation phenology, and GOES for weather animation.
- ESRI Wayback does not require Earth Engine initialization.
- Timelapse generation can take a while and requires user confirmation.
- Keep responses concise and include imagery type, bbox, time window, and
  output path when available.
"""

HYPERCOAST_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS for the HyperCoast plugin.
Use the HyperCoast tools to search, download, preview, and visualize
hyperspectral data.

Workflow guidance:
- Search before downloading when the user asks for online EMIT or PACE data.
- For online hyperspectral data, default to EMIT for mineral/surface
  reflectance workflows and PACE for ocean color, water quality, and
  chlorophyll workflows unless the user specifies a source.
- If the user asks for the current map area, use the current QGIS map extent
  for the search bbox.
- If the user asks for cloud-free, clear-sky, low-cloud, or a specific cloud
  cover limit, pass cloud_cover_max to search_hypercoast_data. Use 10 percent
  for generic cloud-free or low-cloud requests unless the user gives another
  threshold.
- If the user asks to show footprints after a HyperCoast search, use
  display_hypercoast_footprints. Do not generate ad hoc PyQGIS footprint code.
- If the user asks to download or visualize a selected HyperCoast footprint,
  first call get_selected_hypercoast_footprints for the footprint layer, then
  pass its granules to download_hypercoast_data.
- For PACE OCI BGC products such as chlor_a, download the NetCDF locally first,
  then use load_hypercoast_variable with variable_name="chlor_a" unless the
  user asks for another BGC variable. Do not load grouped PACE NetCDF variables
  directly through QGIS /vsicurl or GDAL subdataset strings.
- Never visualize HyperCoast search results with add_raster_layer, browse PNGs,
  remote /vsicurl paths, or raw NetCDF subdataset strings. Use
  load_hypercoast_rgb for AOP/Rrs imagery and load_hypercoast_variable for BGC
  variables.
- Do not add cloud_cover filters to PACE BGC searches unless the user explicitly
  asks for cloud-free or low-cloud results.
- Downloading data and loading visualizations can take time and require user
  confirmation.
- For local hyperspectral files, preview metadata first when the requested
  data type or available variables are unclear, then load an RGB visualization
  with load_hypercoast_rgb.
- Use true color wavelengths 650,550,450 nm by default. For vegetation, prefer
  color infrared 850,650,550 nm. For water, prefer 550,480,450 nm.
- Keep responses concise and include source, result count, output paths, layer
  names, selected wavelengths, and selected variable when available.
"""

QGIS_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS with access to PyQGIS-backed tools.

Workflow guidance:
- Use QGIS layer names as input values only when the layer is backed by a
  local file. Otherwise ask the user to export the layer or provide a file.
- Generated outputs are added back to QGIS when possible.
- When the user asks for a QGIS API operation that has no dedicated tool, such
  as raster renderer/band styling, labeling, layer tree tweaks, or other
  project/canvas changes, write a short PyQGIS script and run it with
  run_pyqgis_script. Do not merely provide a script for the user to paste when
  run_pyqgis_script can safely perform the requested QGIS change.
- When the user asks to create, draw, render, or generate an image or picture,
  or provides a standalone visual description after discussing image
  generation, call generate_image if it is available. Do not reply with only a
  prompt for another image generator unless the tool reports that image
  generation is not configured.
- Keep responses concise and include the tool name, output path, and loaded
  layer names when available.
"""

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
- To measure distance between two loaded features, select them and use
  run_processing_algorithm with native:shortestline.

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
  list_kadas_annotation_layers to discover them, then get_kadas_layer_items(layer_name)
  to read every item's type, label, and WGS84 lon/lat. Do not report only a
  layer's bounding box when the user asks about the items inside it.

OpenStreetMap data:
- For an OSM backdrop call add_osm_basemap (style "standard"/"humanitarian"/
  "cyclosm"). NEVER hand-build an OSM tile URL through add_xyz_tile_layer — the
  dedicated tool uses the correct, well-formed source.
- For actual OSM features (cafes, roads, buildings, ...) call
  query_osm_features(tags, bbox): it runs an Overpass query in-process and loads
  the result as native, selectable QGIS vector layers — not tiles. Pass tags
  like {"amenity": "cafe"} and a WGS84 [min_lon, min_lat, max_lon, max_lat].

Coordinates, elevation and terrain (KADAS-native):
- convert_coordinates(lon, lat, target_format) formats a point as MGRS, UTM,
  DegMinSec, DegMin, DecDeg or LV95 using KADAS' own formatter — use it instead
  of hand-rolling coordinate maths. get_elevation_at(lon, lat) returns terrain
  height in metres. check_line_of_sight(observer, target, heights) tests
  observer→target visibility over the terrain.

External reference folders (Developer mode):
- If external folders are configured, list_external_roots shows them;
  scan_external_folder and read_external_file browse/read files there (read-only,
  sandboxed to the allowed roots). Use these instead of run_command for files
  outside the project.
- find_spatial_data searches those folders for spatial datasets (Shapefile,
  GeoPackage, GeoJSON, KML, ...) and inspects each natively (geometry type,
  feature count, CRS, fields) via QGIS' provider registry — use it to discover
  local data before add_vector_layer, never hand-parse the files.

Runtime awareness, plugins, export and logs (KADAS-native):
- list_qgis_capabilities reports the active plugins, the loaded Processing
  providers/algorithms and whether the KADAS modules are available. Call it when
  unsure whether a capability exists here instead of guessing.
- Discover, then act (do not reimplement plugins): list_processing_algorithms
  (filter_text) and describe_processing_algorithm(algorithm_id) enumerate every
  Processing algorithm — including ones from imported plugins — and give its
  parameters, so you can build a valid parameters dict and run it with
  run_processing_algorithm. Use these instead of guessing algorithm ids.
- list_plugins() and describe_plugin(name) read a plugin's metadata and its
  registered commands (label, menu, keyboard shortcut). For GUI-only plugins
  (e.g. kadas_print, kadas_ephem) you cannot run them headlessly — use these to
  tell the user exactly which menu/button/shortcut to use.
- Native command bridge: list_kadas_actions(filter_text) enumerates KADAS's own
  named commands (File/Map ops, map tools, plugin actions) and
  trigger_kadas_action(name) runs one as if clicked (e.g. mActionSaveMapExtent =
  Save Map, mActionCopy = Copy Map, mActionNew/mActionOpen/mActionSave,
  mActionPrint). Prefer triggering the native action over writing a
  run_pyqgis_script wrapper. Triggering opens the command's dialog when it needs
  input — for a path/parameter you must pass programmatically, use the dedicated
  headless tools below instead.
- export_gpkg(output_path, layer_names) / import_gpkg(path) reuse the KADAS
  kadas_gpkg plugin to round-trip a full-project GeoPackage (layers + project +
  resources embedded), so styling and layout survive. Prefer these over ogr2ogr
  or a per-layer dump. import_gpkg also loads plain GeoPackages.
- export_layer(layer_name, output_path) writes a vector layer to a file (KML,
  KMZ, GeoJSON, SHP, …) natively via OGR — prefer over a run_pyqgis_script.
- new_project() / open_project(path) / save_project(path) create, load and save a
  .qgs/.qgz project headlessly; use these instead of a run_pyqgis_script that
  calls QgsProject.clear/read/write.
- query_agent_logs(kind, contains) reads and filters the agent's own execution
  and Training-AI feedback logs; use it to answer what the last run did or what
  errored, rather than asking the user to open log files.

- When a request truly has no dedicated tool (custom processing, raster
  band/labeling tweaks), write a short PyQGIS script and run it with
  run_pyqgis_script rather than refusing.
- Keep responses concise and include the tool name, resolved bodId/coordinates,
  and loaded layer or annotation names when available.
"""

TERMINAL_GUIDANCE = """\

Terminal use:
- run_command runs a shell command and returns its exit code and output. Use it
  for external programs not covered by a QGIS tool, e.g. the GDAL/OGR CLI
  utilities (gdalwarp, gdaldem, gdal_translate, ogr2ogr, ogrinfo). For QGIS
  processing algorithms prefer run_processing_algorithm; for PyQGIS prefer
  run_pyqgis_script.
- Terminal use always needs user confirmation. Never run destructive shell
  commands (recursive deletes of system/home paths, disk formatting, etc.);
  they are blocked.
"""


WHITEBOX_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS with access to WhiteboxTools.
WhiteboxTools exposes hundreds of geospatial analysis commands through a
routed tool interface.

Workflow guidance:
- Do not guess exact Whitebox command parameters. Search first when the user
  describes an analysis task, then inspect the selected tool's parameter
  metadata before running it.
- Use search_whitebox_tools to find candidate commands, get_whitebox_tool_info
  to inspect required parameters, then run_whitebox_tool to execute.
- For active DEM flow accumulation requests, prefer
  run_whitebox_flow_accumulation.
- For active DEM sink/depression filling requests, prefer
  run_whitebox_fill_sinks with method="fill_depressions"; this is the default
  and is preferred before flow direction or flow accumulation.
- Use run_whitebox_fill_sinks with method="breach_depressions" only when the
  user explicitly asks to breach, carve, or channel depressions.
- Run each long-running Whitebox command at most once per user request unless
  the tool returns an error. Do not repeat an identical tool call after it has
  already produced an output.
- For active DEM color shaded relief requests, prefer
  run_whitebox_color_shaded_relief.
- For active vector layer buffer requests, prefer buffer_active_layer.
- Use QGIS layer names as input values only when the layer is backed by a
  local file. Otherwise ask the user to export the layer or provide a file.
- Generated outputs are added back to QGIS when possible.
- When the user asks for a QGIS API operation that has no dedicated tool, such
  as raster renderer/band styling, labeling, layer tree tweaks, or other
  project/canvas changes, write a short PyQGIS script and run it with
  run_pyqgis_script. Do not merely provide a script for the user to paste when
  run_pyqgis_script can safely perform the requested QGIS change.
- Keep responses concise and include the Whitebox tool name, output path, and
  loaded layer names when available.
"""

STAC_SYSTEM_PROMPT = """\
You are an AI assistant embedded in QGIS with access to STAC catalog tools.

Workflow guidance:
- If the user does not name a STAC catalog, use the Planetary Computer STAC
  catalog: https://planetarycomputer.microsoft.com/api/stac/v1.
- Use list_stac_collections when the user has a catalog URL but no collection.
- Use search_stac_items for catalog search, including the current QGIS map
  extent when the user asks for the current area. Use
  get_current_stac_search_extent for the current QGIS map extent; do not use
  run_pyqgis_script to calculate STAC search bounds.
- When the user asks for cloud-free, clear-sky, or low-cloud imagery, pass
  max_cloud_cover=10 to search_stac_items and select the returned item with the
  best spatial fit and lowest cloud_cover rather than the newest item. Prefer
  items where contains_query_center is true and bbox_overlap_ratio is high.
  Mention cloud_cover in the response when available.
- For DEM/elevation requests, do not pass max_cloud_cover. Prefer Planetary
  Computer collection cop-dem-glo-30 and load the data/elevation asset rather
  than a rendered preview.
- Inspect item assets before loading. Prefer cloud-optimized raster assets
  such as COG, GeoTIFF, visual, analytic, or band-specific raster assets.
- If search_stac_items returns a suitable preferred_assets entry, use that href
  directly with add_stac_asset_to_qgis instead of making a separate
  get_stac_item_assets call.
- Use add_stac_asset_to_qgis only for a concrete asset href. If QGIS cannot
  load the asset directly, report the returned asset URL and reason instead of
  claiming the layer was added. If the tool reports queued=True, tell the user
  the QGIS background task has started and the layer will appear when QGIS
  validates the raster.
- Keep responses concise and include catalog URL, collection, item id, asset
  key, and layer name when available.
"""

BROWSER_MAPLIBRE_SYSTEM_PROMPT = """\
You are an AI assistant embedded in a browser web app with access to a live
MapLibre map through safe browser tools.

Workflow guidance:
- Use browser map tools for map navigation, layer inspection, marker creation,
  GeoJSON display, layer visibility, feature queries, and screenshots.
- Coordinates in user-facing prompts are latitude/longitude, but browser map
  internals use longitude/latitude. Use the tool parameter names exactly.
- Do not ask the user to paste JavaScript or run Python for actions that the
  browser map tools can perform.
- If a requested operation has no browser map tool, explain the limitation
  briefly rather than trying to execute arbitrary JavaScript.
- Keep responses concise and include layer names, locations, and tool results
  when useful.
"""

BROWSER_MAPLIBRE_CODE_SYSTEM_PROMPT = """\
Browser JavaScript code execution is enabled for this local session.

When no dedicated browser map tool can perform the requested MapLibre
operation, write a short JavaScript snippet and run it with
run_maplibre_script. The snippet executes in the browser with these names in
scope: map, maplibregl, and helpers. Prefer MapLibre GL JS API calls, keep code
focused on map operations, and avoid credential handling, storage access,
unrelated DOM manipulation, or broad network operations.
"""


def _filter_by_imports(tools: list[Any]) -> list[Any]:
    """Drop tools whose declared optional packages are unavailable."""
    out: list[Any] = []
    for t in tools:
        meta = getattr(t, "_geoagent_meta", None)
        if (
            meta
            and meta.requires_packages
            and not packages_available(meta.requires_packages)
        ):
            continue
        out.append(t)
    return out


def _permission_allows_tool(permission_profile: str | None, tool: Any) -> bool:
    """Return whether a QGIS/plugin tool should be exposed for a profile."""
    profile = permission_profile or "Trusted auto-approve"
    if profile == "Execute PyQGIS":
        profile = "Execute Scripts"
    name = (
        getattr(tool, "tool_name", "")
        or getattr(tool, "__name__", "")
        or getattr(tool, "name", "")
    )
    meta = getattr(tool, "_geoagent_meta", None)
    category = str(getattr(meta, "category", "") or "")
    requires_confirmation = bool(getattr(meta, "requires_confirmation", False))
    destructive = bool(getattr(meta, "destructive", False))
    long_running = bool(getattr(meta, "long_running", False))

    if profile == "Trusted auto-approve":
        return True
    if profile == "Execute Scripts":
        return True
    if name in {"run_pyqgis_script", "run_command"}:
        return False
    if profile == "Run processing":
        return True
    if category in {
        "whitebox",
        "nasa_earthdata",
        "nasa_opera",
        "gee_data_catalogs",
        "timelapse",
        "vantor",
        "geoai",
        "hypercoast",
    }:
        return profile in {"Run processing", "Execute Scripts", "Trusted auto-approve"}
    if profile == "Edit layers":
        return not destructive and name != "run_processing_algorithm"
    return not (requires_confirmation or destructive or long_running)


def _filter_by_permission(
    tools: list[Any], permission_profile: str | None
) -> list[Any]:
    """Filter QGIS-related tool surfaces according to a permission profile."""
    if not permission_profile:
        return tools
    return [tool for tool in tools if _permission_allows_tool(permission_profile, tool)]


def _drop_tools_by_name(tools: list[Any], excluded: set[str]) -> list[Any]:
    """Return tools except those whose Strands name is excluded."""
    if not excluded:
        return tools
    out = []
    for tool in tools:
        name = (
            getattr(tool, "tool_name", "")
            or getattr(tool, "__name__", "")
            or getattr(tool, "name", "")
        )
        if str(name) not in excluded:
            out.append(tool)
    return out


def register_all_tools(registry: GeoToolRegistry, tools: Iterable[Any]) -> None:
    """Populate registry from decorated tools."""
    for t in tools:
        meta = getattr(t, "_geoagent_meta", None)
        if meta is not None:
            registry.register_tool(t, meta)


def assemble_tools(
    *,
    context: GeoAgentContext,
    extra_tools: Optional[list[Any]] = None,
    include_leafmap: bool = False,
    include_anymap: bool = False,
    include_qgis: bool = False,
    include_geoadmin: bool = False,
    include_kadas: bool = False,
    include_capabilities: bool = False,
    include_osm: bool = False,
    include_external_files: bool = False,
    external_roots: Optional[list[Any]] = None,
    include_terminal: bool = False,
    include_nasa_earthdata: bool = False,
    include_nasa_opera: bool = False,
    include_gee_data_catalogs: bool = False,
    include_timelapse: bool = False,
    include_vantor: bool = False,
    include_whitebox: bool = False,
    include_stac: bool = False,
    include_geoai: bool = False,
    include_hypercoast: bool = False,
    include_image_generation: bool = False,
    nasa_earthdata_plugin: Any | None = None,
    gee_data_catalogs_plugin: Any | None = None,
    timelapse_plugin: Any | None = None,
    vantor_plugin: Any | None = None,
    geoai_plugin: Any | None = None,
    hypercoast_plugin: Any | None = None,
    fast: bool = False,
    permission_profile: str | None = None,
    exclude_tool_names: set[str] | None = None,
) -> tuple[list[Any], GeoToolRegistry]:
    """Collect tools for a context and build a metadata registry."""
    registry = GeoToolRegistry()
    collected: list[Any] = []
    if include_leafmap and context.map_obj is not None:
        lt = _filter_by_imports(leafmap_tools(context.map_obj))
        register_all_tools(registry, lt)
        collected.extend(lt)
    if include_anymap and context.map_obj is not None:
        at = _filter_by_imports(anymap_tools(context.map_obj))
        register_all_tools(registry, at)
        collected.extend(at)
    if include_qgis:
        qt = _filter_by_imports(qgis_tools(context.qgis_iface, context.qgis_project))
        register_all_tools(registry, qt)
        collected.extend(qt)
    if include_geoadmin:
        gat = _filter_by_imports(
            geoadmin_tools(context.qgis_iface, context.qgis_project)
        )
        register_all_tools(registry, gat)
        collected.extend(gat)
    if include_kadas:
        kt = _filter_by_imports(kadas_tools(context.qgis_iface, context.qgis_project))
        register_all_tools(registry, kt)
        collected.extend(kt)
        ktt = _filter_by_imports(
            kadas_terrain_tools(context.qgis_iface, context.qgis_project)
        )
        register_all_tools(registry, ktt)
        collected.extend(ktt)
    if include_capabilities:
        ct = _filter_by_imports(
            capability_tools(context.qgis_iface, context.qgis_project)
        )
        register_all_tools(registry, ct)
        collected.extend(ct)
    if include_osm:
        ot = _filter_by_imports(osm_tools(context.qgis_iface, context.qgis_project))
        register_all_tools(registry, ot)
        collected.extend(ot)
    if include_external_files:
        eft = _filter_by_imports(external_files_tools(external_roots))
        register_all_tools(registry, eft)
        collected.extend(eft)
    if include_terminal:
        tt = _filter_by_imports(terminal_tools())
        register_all_tools(registry, tt)
        collected.extend(tt)
    if include_nasa_earthdata:
        earthdata_tool_list = _filter_by_imports(
            earthdata_tools(
                context.qgis_iface,
                context.qgis_project,
                plugin=nasa_earthdata_plugin,
            )
        )
        register_all_tools(registry, earthdata_tool_list)
        collected.extend(earthdata_tool_list)
    if include_nasa_opera:
        opera_tools = _filter_by_imports(
            nasa_opera_tools(context.qgis_iface, context.qgis_project)
        )
        register_all_tools(registry, opera_tools)
        collected.extend(opera_tools)
    if include_gee_data_catalogs:
        gee_tools = _filter_by_imports(
            gee_data_catalogs_tools(
                context.qgis_iface,
                plugin=gee_data_catalogs_plugin,
            )
        )
        register_all_tools(registry, gee_tools)
        collected.extend(gee_tools)
    if include_timelapse:
        timelapse_tool_list = _filter_by_imports(
            timelapse_tools(
                context.qgis_iface,
                context.qgis_project,
                plugin=timelapse_plugin,
            )
        )
        register_all_tools(registry, timelapse_tool_list)
        collected.extend(timelapse_tool_list)
    if include_vantor:
        vantor_tool_list = _filter_by_imports(
            vantor_tools(
                context.qgis_iface,
                context.qgis_project,
                plugin=vantor_plugin,
            )
        )
        register_all_tools(registry, vantor_tool_list)
        collected.extend(vantor_tool_list)
    if include_whitebox:
        whitebox_tool_list = _filter_by_imports(
            whitebox_tools(context.qgis_iface, context.qgis_project)
        )
        register_all_tools(registry, whitebox_tool_list)
        collected.extend(whitebox_tool_list)
    if include_stac:
        stac_tool_list = _filter_by_imports(
            stac_tools(context.qgis_iface, context.qgis_project)
        )
        register_all_tools(registry, stac_tool_list)
        collected.extend(stac_tool_list)
    if include_geoai:
        geoai_tool_list = _filter_by_imports(
            geoai_tools(
                context.qgis_iface,
                context.qgis_project,
                plugin=geoai_plugin,
            )
        )
        register_all_tools(registry, geoai_tool_list)
        collected.extend(geoai_tool_list)
    if include_hypercoast:
        hypercoast_tool_list = _filter_by_imports(
            hypercoast_tools(
                context.qgis_iface,
                context.qgis_project,
                plugin=hypercoast_plugin,
            )
        )
        register_all_tools(registry, hypercoast_tool_list)
        collected.extend(hypercoast_tool_list)
    if include_image_generation:
        image_tools = _filter_by_imports(image_generation_tools())
        register_all_tools(registry, image_tools)
        collected.extend(image_tools)
    if extra_tools:
        register_all_tools(registry, extra_tools)
        collected.extend(extra_tools)
    effective_exclude_tool_names = set(exclude_tool_names or set())
    if include_hypercoast:
        effective_exclude_tool_names.add("add_raster_layer")
    collected = _filter_by_permission(collected, permission_profile)
    collected = _drop_tools_by_name(collected, effective_exclude_tool_names)
    tools = collect_tools_for_context(collected, fast=fast, registry=registry)
    return tools, registry


def create_agent(
    *,
    context: GeoAgentContext | None = None,
    tools: list[Any] | None = None,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
) -> GeoAgent:
    """Create a :class:`GeoAgent` with explicit tools and optional model."""
    ctx = context or GeoAgentContext()
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    registry = GeoToolRegistry()
    tool_list = _filter_by_imports(list(tools or []))
    register_all_tools(registry, tool_list)
    tool_list = collect_tools_for_context(tool_list, fast=fast, registry=registry)
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tool_list,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
    )


def for_leafmap(
    m: Any,
    *,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
) -> GeoAgent:
    """Bind an agent to a leafmap-compatible map instance."""
    ctx = GeoAgentContext(map_obj=m)
    tools, registry = assemble_tools(
        context=ctx,
        include_leafmap=True,
        include_image_generation=True,
        extra_tools=extra_tools,
        fast=fast,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
    )


def for_anymap(
    m: Any,
    *,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
) -> GeoAgent:
    """Bind an agent to an anymap map instance."""
    ctx = GeoAgentContext(map_obj=m)
    tools, registry = assemble_tools(
        context=ctx,
        include_anymap=True,
        include_image_generation=True,
        extra_tools=extra_tools,
        fast=fast,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
    )


def for_browser_maplibre(
    session: Any,
    *,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    allow_browser_code: bool = False,
) -> GeoAgent:
    """Bind an agent to a MapLibre map running in a browser session."""
    system_prompt = BROWSER_MAPLIBRE_SYSTEM_PROMPT
    if allow_browser_code:
        system_prompt = f"{system_prompt}\n\n{BROWSER_MAPLIBRE_CODE_SYSTEM_PROMPT}"
    ctx = GeoAgentContext(
        metadata={
            "integration": "browser_maplibre",
            "system_prompt": system_prompt,
        }
    )
    tool_list = _filter_by_imports(
        browser_maplibre_tools(session, allow_code=allow_browser_code)
    )
    if extra_tools:
        tool_list.extend(extra_tools)
    registry = GeoToolRegistry()
    register_all_tools(registry, tool_list)
    tools = collect_tools_for_context(tool_list, fast=fast, registry=registry)
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
    )


def for_qgis(
    iface: Any,
    project: Any = None,
    *,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    permission_profile: str | None = None,
    include_terminal: bool = False,
    enable_logging: bool = False,
    tracer: AgentTracer | None = None,
) -> GeoAgent:
    """Bind an agent to QGIS ``iface`` (and optional ``project``).

    Args:
        include_terminal: Expose the run_command terminal tool. Off by default
            for vanilla QGIS; enable for shell-capable workflows.
        enable_logging: Turn on full LLM-mode execution tracing. Ignored when
            ``tracer`` is given.
        tracer: An explicit :class:`~geoagent.core.telemetry.AgentTracer`.
    """
    system_prompt = QGIS_SYSTEM_PROMPT
    if include_terminal:
        system_prompt = system_prompt + TERMINAL_GUIDANCE
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={"system_prompt": system_prompt},
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=True,
        include_terminal=include_terminal,
        include_image_generation=True,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    if tracer is None and enable_logging:
        tracer = AgentTracer()
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
        tracer=tracer,
    )


def for_kadas(
    iface: Any,
    project: Any = None,
    *,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    permission_profile: str | None = None,
    include_terminal: bool = True,
    external_roots: Optional[list[Any]] = None,
    enable_logging: bool = False,
    tracer: AgentTracer | None = None,
) -> GeoAgent:
    """Bind an agent to KADAS Albireo 2.

    Exposes the general QGIS map/project tools plus the KADAS-specific surface:
    the swisstopo geoadmin catalog and location search
    (:mod:`geoagent.tools.geoadmin`) and KADAS-native map annotations
    (:mod:`geoagent.tools.kadas`). ``iface`` is typically a
    :class:`~kadas_geoagent.kadas_iface_adapter.KadasIfaceAdapter`.

    Args:
        include_terminal: Expose the run_command terminal tool
            (:func:`geoagent.tools.terminal.terminal_tools`).
        enable_logging: Turn on full LLM-mode execution tracing to
            ``~/.kadas/agent_execution.log``. Ignored when ``tracer`` is given.
        tracer: An explicit :class:`~geoagent.core.telemetry.AgentTracer` to
            record the turn into (e.g. a shared developer-console buffer).
    """
    system_prompt = KADAS_SYSTEM_PROMPT
    if include_terminal:
        system_prompt = system_prompt + TERMINAL_GUIDANCE
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "kadas",
            "system_prompt": system_prompt,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=True,
        include_geoadmin=True,
        include_kadas=True,
        include_capabilities=True,
        include_osm=True,
        include_external_files=True,
        external_roots=external_roots,
        include_terminal=include_terminal,
        include_image_generation=True,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    if tracer is None and enable_logging:
        tracer = AgentTracer()
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
        tracer=tracer,
    )


def for_nasa_opera(
    iface: Any,
    project: Any = None,
    *,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to the NASA OPERA QGIS plugin runtime.

    The factory exposes native GeoAgent OPERA tools and, by default, the
    general QGIS map/project tools used for navigation and layer management.
    """
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "nasa_opera",
            "system_prompt": NASA_OPERA_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_nasa_opera=True,
        include_image_generation=True,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
    )


def for_nasa_earthdata(
    iface: Any,
    project: Any = None,
    *,
    plugin: Any | None = None,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to the NASA Earthdata QGIS plugin runtime.

    The factory exposes native NASA Earthdata tools and, by default, the
    general QGIS map/project tools used for navigation and layer management.
    """
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "nasa_earthdata",
            "system_prompt": NASA_EARTHDATA_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_nasa_earthdata=True,
        include_image_generation=True,
        nasa_earthdata_plugin=plugin,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
    )


def for_gee_data_catalogs(
    iface: Any,
    project: Any = None,
    *,
    plugin: Any | None = None,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to the QGIS GEE Data Catalogs plugin runtime.

    The factory exposes native GEE Data Catalogs tools and, by default, the
    general QGIS map/project tools used for navigation and layer management.
    """
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "gee_data_catalogs",
            "system_prompt": GEE_DATA_CATALOGS_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_gee_data_catalogs=True,
        include_image_generation=True,
        gee_data_catalogs_plugin=plugin,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
        exclude_tool_names={"set_layer_symbology"} if include_qgis else set(),
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
    )


def for_vantor(
    iface: Any,
    project: Any = None,
    *,
    plugin: Any | None = None,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to the QGIS Vantor plugin runtime.

    The factory exposes native Vantor Open Data STAC tools and, by default,
    the general QGIS map/project tools used for navigation and layer
    management.
    """
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "vantor",
            "system_prompt": VANTOR_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_vantor=True,
        include_image_generation=True,
        vantor_plugin=plugin,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
    )


def for_timelapse(
    iface: Any,
    project: Any = None,
    *,
    plugin: Any | None = None,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to the QGIS Timelapse plugin runtime.

    The factory exposes native Timelapse tools and, by default, the general
    QGIS map/project tools used for inspection and navigation.
    """
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "timelapse",
            "system_prompt": TIMELAPSE_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_timelapse=True,
        include_image_generation=True,
        timelapse_plugin=plugin,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
    )


def for_hypercoast(
    iface: Any,
    project: Any = None,
    *,
    plugin: Any | None = None,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to the QGIS HyperCoast plugin runtime.

    The factory exposes native HyperCoast search, download, and visualization
    tools and, by default, the general QGIS map/project tools used for
    inspection and navigation.
    """
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "hypercoast",
            "system_prompt": HYPERCOAST_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_hypercoast=True,
        include_image_generation=True,
        hypercoast_plugin=plugin,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
    )


def for_whitebox(
    iface: Any,
    project: Any = None,
    *,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to QGIS with WhiteboxTools analysis support.

    The factory exposes a routed WhiteboxTools broker surface and, by default,
    the general QGIS map/project tools used for inspection and navigation.
    """
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "whitebox",
            "system_prompt": WHITEBOX_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_whitebox=True,
        include_image_generation=True,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
    )


def for_stac(
    iface: Any = None,
    project: Any = None,
    *,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to STAC catalog workflows and optional QGIS loading."""
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "stac",
            "system_prompt": STAC_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_stac=True,
        include_image_generation=True,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
        exclude_tool_names={"run_pyqgis_script"},
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=iface is not None,
    )


def for_geoai(
    iface: Any,
    project: Any = None,
    *,
    plugin: Any | None = None,
    config: GeoAgentConfig | None = None,
    model: Any | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    fast: bool = False,
    confirm: ConfirmCallback | None = None,
    extra_tools: Optional[list[Any]] = None,
    include_qgis: bool = True,
    permission_profile: str | None = None,
) -> GeoAgent:
    """Bind an agent to QGIS with GeoAI SamGeo segmentation support.

    The factory exposes GeoAI plugin-backed SamGeo text-prompt segmentation
    and, by default, the general QGIS map/project tools used for inspection
    and navigation.
    """
    ctx = GeoAgentContext(
        qgis_iface=iface,
        qgis_project=project,
        metadata={
            "integration": "geoai",
            "system_prompt": GEOAI_SYSTEM_PROMPT,
        },
    )
    tools, registry = assemble_tools(
        context=ctx,
        include_qgis=include_qgis,
        include_geoai=True,
        include_image_generation=True,
        geoai_plugin=plugin,
        extra_tools=extra_tools,
        fast=fast,
        permission_profile=permission_profile,
    )
    cfg = config or GeoAgentConfig()
    if provider is not None:
        cfg = cfg.model_copy(update={"provider": provider})
    if model_id is not None:
        cfg = cfg.model_copy(update={"model": model_id})
    return GeoAgent(
        context=ctx,
        config=cfg,
        tools=tools,
        registry=registry,
        model=model,
        provider=provider,
        model_id=model_id,
        fast=fast,
        confirm=confirm,
        qgis_safe_mode=True,
    )


__all__ = [
    "assemble_tools",
    "create_agent",
    "for_anymap",
    "for_gee_data_catalogs",
    "for_geoai",
    "for_hypercoast",
    "for_kadas",
    "for_leafmap",
    "for_nasa_earthdata",
    "for_nasa_opera",
    "for_qgis",
    "for_stac",
    "for_timelapse",
    "for_vantor",
    "for_whitebox",
    "register_all_tools",
]
