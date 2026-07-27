"""Tools for the swisstopo ``geo.admin.ch`` catalog and location search.

KADAS Albireo 2 does not ship a fixed layer list; it browses the live swisstopo
``geoadmin`` catalog (configured in ``settings_full.ini`` as
``geodatacatalogs=…/ech/CatalogServer``) and resolves place names through the
geoadmin ``SearchServer`` (``locationsearchurl``). The vanilla QGIS tool surface
in :mod:`geoagent.tools.qgis` knows nothing about either, so on KADAS the agent
otherwise has to guess ``layerBodId``s or fall back to ``run_pyqgis_script``.

These tools close that gap with three capabilities, all driven by the public
``api3.geo.admin.ch`` REST API:

    * **catalog search** — resolve a topic ("electric stations") to a concrete
      ``layerBodId`` (:func:`search_geoadmin_catalog`),
    * **layer loading** — add a catalog layer to the project as a WMS raster,
      identical to the KADAS geocatalog (``load_geoadmin_layer``),
    * **location search / geocoding** — resolve a place name to coordinates and
      optionally recentre the canvas (``search_location`` / ``locate_and_zoom``).

The module is import-safe outside QGIS/KADAS: it never imports ``qgis`` at module
load time. QGIS classes are imported lazily inside the GUI tool bodies so the
module (and its unit tests) import cleanly in plain CI. All HTTP is HTTPS-only,
pinned to the geoadmin host.
"""

from __future__ import annotations

import json
import re
import time as _time
from typing import Any, Optional
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from geoagent.core.decorators import geo_tool
from geoagent.tools._qt_marshal import run_on_qt_gui_thread

# --------------------------------------------------------------------------- #
# Endpoints (the same host KADAS' settings_full.ini points at)
# --------------------------------------------------------------------------- #

GEOADMIN_HOST = "api3.geo.admin.ch"
# Per-topic layer configuration: a flat dict keyed by layerBodId carrying the
# label, service type (wmts/wms/aggregate), tile format and timestamps. The
# ``ech`` topic mirrors the KADAS catalog tree.
LAYERS_CONFIG_URL = f"https://{GEOADMIN_HOST}/rest/services/ech/MapServer/layersConfig"
# Place-name search (the geoadmin SearchServer behind KadasLocationSearchProvider).
SEARCH_URL = f"https://{GEOADMIN_HOST}/rest/services/api/SearchServer"
# swisstopo WMS endpoint — the service the KADAS geocatalog actually loads from.
# A manual catalog click produces a WMS GetMap layer against this host (see
# KadasGeoAdminRestCatalogProvider / KadasMainWindow::addCatalogLayer in
# kadas-albireo2). Loading via WMS (rather than WMTS/XYZ tiles) is bbox-based and
# projection-correct, so it cannot fall into the LV95-vs-WebMercator tiling-scheme
# trap that silently blanks XYZ layers on the swisstopo /2056/ endpoint.
WMS_HOST = "wms.geo.admin.ch"
WMS_GETCAPABILITIES_URL = (
    f"https://{WMS_HOST}/?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities&lang=en"
)

HTTP_TIMEOUT = 30
_USER_AGENT = "GeoAgent-Geoadmin/1.0"

# Curated topic → bodId hints for the recurring KADAS test prompts (JUNE_24.md
# §A.3). These bias catalog search so common asks resolve in one hop even when
# the raw layer labels do not contain the user's wording.
CURATED_TOPICS: dict[str, str] = {
    "swissimage": "ch.swisstopo.swissimage-product",
    "aerial": "ch.swisstopo.swissimage-product",
    "aerial photo": "ch.swisstopo.swissimage-product",
    "orthophoto": "ch.swisstopo.swissimage-product",
    "satellite": "ch.swisstopo.swissimage-product",
    "national map": "ch.swisstopo.pixelkarte-farbe",
    "swisstopo vt": "ch.swisstopo.pixelkarte-farbe",
    "landeskarte": "ch.swisstopo.pixelkarte-farbe",
    "hillshade": "ch.swisstopo.swissalti3d-reliefschattierung",
    "relief": "ch.swisstopo.swissalti3d-reliefschattierung",
    "cadastre": "ch.kantone.cadastralwebmap-farbe",
    "cadastral": "ch.kantone.cadastralwebmap-farbe",
    "property boundaries": "ch.kantone.cadastralwebmap-farbe",
    "parcel": "ch.kantone.cadastralwebmap-farbe",
    "electric": "ch.bfe.sachplan-uebertragungsleitungen_kraft",
    "electrical": "ch.bfe.sachplan-uebertragungsleitungen_kraft",
    "power line": "ch.bfe.sachplan-uebertragungsleitungen_kraft",
    "transmission": "ch.bfe.sachplan-uebertragungsleitungen_kraft",
}

# Module-level layersConfig cache (TTL bounded) so catalog search/info do not
# re-fetch the full topic config on every call.
_LAYERS_CACHE: dict[str, Any] = {"data": None, "fetched_at": 0.0}
_LAYERS_CACHE_TTL = 3600.0  # seconds

_TAG_RE = re.compile(r"<[^>]+>")
_BOX2D_RE = re.compile(
    r"BOX\(\s*([-\d.eE]+)\s+([-\d.eE]+)\s*,\s*([-\d.eE]+)\s+([-\d.eE]+)\s*\)"
)


# --------------------------------------------------------------------------- #
# HTTP helpers (HTTPS-only, geoadmin host pinned)
# --------------------------------------------------------------------------- #


def _fetch_json(url: str) -> Any:
    """Fetch and parse JSON from the geoadmin REST API (HTTPS-only)."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or parsed.hostname != GEOADMIN_HOST:
        raise ValueError(f"Refusing non-geoadmin or non-HTTPS URL: {url!r}")
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=HTTP_TIMEOUT) as response:  # nosec B310 - pinned HTTPS
        return json.loads(response.read().decode("utf-8"))


def _layers_config(*, force: bool = False) -> dict[str, Any]:
    """Return the cached ``ech`` layersConfig dict (bodId → metadata)."""
    now = _time.time()
    cached = _LAYERS_CACHE["data"]
    if (
        not force
        and isinstance(cached, dict)
        and (now - float(_LAYERS_CACHE["fetched_at"])) < _LAYERS_CACHE_TTL
    ):
        return cached
    data = _fetch_json(
        f"{LAYERS_CONFIG_URL}?{urlencode({'lang': 'en'})}"
    )  # TODO: need to extend this for multilingual support
    if not isinstance(data, dict):
        data = {}
    _LAYERS_CACHE["data"] = data
    _LAYERS_CACHE["fetched_at"] = now
    return data


def _strip_tags(text: Any) -> str:
    """Strip HTML tags swisstopo wraps around labels and collapse whitespace."""
    return _TAG_RE.sub("", str(text or "")).strip()


def _layer_record(bod_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Project a layersConfig entry into a compact catalog record."""
    return {
        "bod_id": bod_id,
        "label": _strip_tags(cfg.get("label")) or bod_id,
        "type": str(cfg.get("type") or "").lower(),
        "format": str(cfg.get("format") or "") or None,
        "background": bool(cfg.get("background", False)),
    }


# --------------------------------------------------------------------------- #
# Catalog search / loading
# --------------------------------------------------------------------------- #


def _score_layer(tokens: list[str], bod_id: str, label: str) -> int:
    """Rank a layer against query tokens by substring/token overlap."""
    haystack = f"{bod_id} {label}".lower()
    score = 0
    for tok in tokens:
        if not tok:
            continue
        if tok in haystack:
            score += 2
        if tok in label.lower():
            score += 1
    return score


def _search_catalog(query: str, limit: int) -> list[dict[str, Any]]:
    """Return ranked catalog records matching ``query`` (worker, no GUI)."""
    config = _layers_config()
    q = str(query or "").strip().lower()
    tokens = [t for t in re.split(r"\W+", q) if t]

    scored: list[tuple[int, dict[str, Any]]] = []
    for bod_id, cfg in config.items():
        if not isinstance(cfg, dict):
            continue
        rec = _layer_record(bod_id, cfg)
        score = _score_layer(tokens, bod_id, rec["label"])
        # Curated topic hints add a strong bias for the known prompts.
        for phrase, curated_id in CURATED_TOPICS.items():
            if phrase in q and curated_id == bod_id:
                score += 5
        if score > 0:
            scored.append((score, rec))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["label"]))
    return [rec for _, rec in scored[: max(1, int(limit))]]


def _wms_layer_uri(bod_id: str, crs: str = "EPSG:2056", fmt: str = "image/png") -> str:
    """Build a QGIS WMS provider URI identical to the KADAS geocatalog's.

    Mirrors ``KadasCatalogProvider::parseWMSLayerCapabilities`` +
    ``KadasMainWindow::addCatalogLayer`` in kadas-albireo2: a WMS GetMap source
    against ``wms.geo.admin.ch`` carrying the layer ``bodId``, the project CRS
    (the catalog picks the supported CRS matching the canvas) and PNG. The result
    is byte-compatible with a manually loaded catalog layer and renders correctly
    because WMS is bbox-based — no tile grid / CRS mismatch is possible.

    Args:
        bod_id: The geoadmin ``layerBodId`` (becomes the WMS ``layers`` value).
        crs: The CRS authid to request (the active project CRS; LV95 by default).
        fmt: The WMS image format (swisstopo serves ``image/png`` for overlays).

    Returns:
        A QGIS ``wms`` provider URI string.
    """
    return (
        "contextualWMSLegend=0&featureCount=10&dpiMode=7&authCfg="
        "&IgnoreReportedLayerExtents=1"
        f"&crs={crs}&format={fmt}&layers={bod_id}&styles="
        f"&url={WMS_GETCAPABILITIES_URL}"
    )


# Matches a swisstopo WMTS/XYZ tile URL and captures its layerBodId, e.g.
# https://wmts.geo.admin.ch/1.0.0/ch.bag.radonkarte/default/current/3857/{z}/{x}/{y}.png
_SWISSTOPO_TILE_RE = re.compile(
    r"^https?://[^/]*geo\.admin\.ch/1\.0\.0/(ch\.[^/]+)/", re.IGNORECASE
)


def swisstopo_bodid_from_tile_url(url: str) -> Optional[str]:
    """Return the swisstopo ``layerBodId`` if ``url`` is a geo.admin.ch tile URL.

    swisstopo tile URLs look like
    ``https://wmts.geo.admin.ch/1.0.0/<bodId>/default/<time>/<crs>/{z}/{x}/{y}.png``.
    Loaded as XYZ they mis-render (the swisstopo tile grid/CRS is not the global
    Web-Mercator XYZ scheme), so callers should reroute to the official WMS
    source via :func:`_wms_layer_uri`. Returns ``None`` for non-swisstopo URLs
    (e.g. OpenStreetMap), which load correctly as XYZ.

    Args:
        url: A tile URL template to inspect.

    Returns:
        The ``ch.*`` layerBodId, or ``None`` when ``url`` is not swisstopo.
    """
    if not url:
        return None
    match = _SWISSTOPO_TILE_RE.match(str(url).strip())
    return match.group(1) if match else None


def _project_crs(project: Any, default: str = "EPSG:2056") -> str:
    """Return the project's CRS authid, defaulting to LV95 on any failure.

    Matches ``addCatalogLayer``'s behaviour of requesting the WMS layer in the
    CRS of the current project/canvas (the KADAS default project is EPSG:2056).
    """
    try:
        authid = project.crs().authid()
        if authid:
            return str(authid)
    except Exception:
        pass
    return default


# --------------------------------------------------------------------------- #
# Location search (geocoding)
# --------------------------------------------------------------------------- #


def _parse_box2d(value: Any) -> Optional[list[float]]:
    """Parse a PostGIS ``BOX(minx miny,maxx maxy)`` string into a bbox list."""
    match = _BOX2D_RE.search(str(value or ""))
    if not match:
        return None
    minx, miny, maxx, maxy = (float(g) for g in match.groups())
    return [minx, miny, maxx, maxy]


def _query_locations(query: str, limit: int) -> list[dict[str, Any]]:
    """Return ranked geoadmin location matches in WGS84 (worker, no GUI)."""
    params = {
        "type": "locations",
        "searchText": str(query or "").strip(),
        "lang": "en",
        "sr": "4326",
        "limit": str(max(1, int(limit))),
    }
    data = _fetch_json(f"{SEARCH_URL}?{urlencode(params)}")
    results = data.get("results", []) if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    for entry in results:
        attrs = entry.get("attrs", {}) if isinstance(entry, dict) else {}
        try:
            lon = float(attrs["lon"])
            lat = float(attrs["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(
            {
                "label": _strip_tags(attrs.get("label")),
                "lon": lon,
                "lat": lat,
                "bbox": _parse_box2d(attrs.get("geom_st_box2d")),
                "origin": attrs.get("origin"),
            }
        )
    return out


class _PointLike:
    """Minimal x()/y() point for canvas centring when QGIS is unavailable."""

    def __init__(self, x: float, y: float) -> None:
        self._x, self._y = x, y

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


# --------------------------------------------------------------------------- #
# Tool factory
# --------------------------------------------------------------------------- #


def geoadmin_tools(iface: Any = None, project: Optional[Any] = None) -> list[Any]:
    """Build the geoadmin catalog/search tool set.

    The catalog- and location-*search* tools are pure REST and are always
    returned (useful even headless). The *loading* and *zoom* tools require a
    live ``iface`` and are only included when one is supplied.

    Args:
        iface: A QGIS/KADAS ``iface`` (or adapter). ``None`` returns just the
            search tools.
        project: Optional ``QgsProject``; falls back to ``QgsProject.instance()``.

    Returns:
        A list of Strands tool objects.
    """

    def _on_gui(func: Any) -> Any:
        """Run a callable on the Qt GUI thread."""
        return run_on_qt_gui_thread(func)

    def _project() -> Any:
        """Return the configured project or resolve it from the iface."""
        if project is not None:
            return project
        if iface is not None and hasattr(iface, "project"):
            try:
                proj = iface.project()
                if proj is not None:
                    return proj
            except Exception:
                pass
        from qgis.core import QgsProject  # type: ignore[import-not-found]

        return QgsProject.instance()

    @geo_tool(category="geoadmin", available_in=("full", "fast"))
    def search_geoadmin_catalog(query: str, limit: int = 10) -> dict[str, Any]:
        """Search the swisstopo geoadmin catalog for layers matching a topic.

        Resolves a natural-language topic (e.g. "aerial photos", "electric
        stations", "property boundaries") to concrete ``layerBodId``s that can
        be loaded with ``load_geoadmin_layer``.

        Args:
            query: Free-text topic or place subject to search for.
            limit: Maximum number of catalog layers to return.

        Returns:
            ``{"success", "count", "layers": [{"bod_id", "label", "type", ...}]}``.
        """
        try:
            layers = _search_catalog(query, limit)
        except Exception as exc:  # network / parse failure
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"success": True, "count": len(layers), "layers": layers}

    @geo_tool(category="geoadmin", available_in=("full", "fast"))
    def get_geoadmin_layer_info(bod_id: str) -> dict[str, Any]:
        """Return metadata for a geoadmin layer by its ``layerBodId``.

        Args:
            bod_id: The geoadmin ``layerBodId`` (e.g.
                ``ch.swisstopo.swissimage-product``).

        Returns:
            ``{"success", "bod_id", "label", "type", "format", "loadable"}`` or
            an error when the id is unknown.
        """
        try:
            cfg = _layers_config().get(bod_id)
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        if not isinstance(cfg, dict):
            return {"success": False, "error": f"Unknown layerBodId {bod_id!r}."}
        rec = _layer_record(bod_id, cfg)
        rec["success"] = True
        rec["loadable"] = rec["type"] in {"wmts", "aggregate"}
        return rec

    @geo_tool(category="geoadmin", available_in=("full", "fast"))
    def search_location(query: str, limit: int = 5) -> dict[str, Any]:
        """Geocode a place name via the geoadmin location SearchServer.

        Resolves names such as "Matterhorn", "Basel main station", or
        "Thunplatz, Bern" to WGS84 coordinates and a bounding box. Pair with
        the QGIS ``set_center`` / ``zoom_to_extent`` tools, or use
        ``locate_and_zoom`` for a one-shot recentre.

        Args:
            query: The place name to resolve.
            limit: Maximum number of matches to return.

        Returns:
            ``{"success", "count", "locations": [{"label", "lon", "lat", "bbox"}]}``.
        """
        try:
            locations = _query_locations(query, limit)
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"success": True, "count": len(locations), "locations": locations}

    tools: list[Any] = [
        search_geoadmin_catalog,
        get_geoadmin_layer_info,
        search_location,
    ]

    if iface is None:
        return tools

    # No requires_confirmation: adding a catalog layer is benign and reversible,
    # exactly like add_xyz_tile_layer / add_raster_layer (which carry no
    # confirmation flag). Flagging it for confirmation made the "Inspect only"
    # permission profile strip load_geoadmin_layer while leaving the generic
    # (broken-for-swisstopo) tile loaders available — so the agent fell back to
    # add_xyz_tile_layer and produced blank layers, or had no loader at all.

    # TODO: This function needs to be cleaned up
    @geo_tool(
        category="geoadmin",
        available_in=("full", "fast"),
    )
    def load_geoadmin_layer(bod_id: str, name: Optional[str] = None) -> dict[str, Any]:
        """Load a geoadmin catalog layer into the project as a WMS raster.

        Loads the layer the same way a manual KADAS geocatalog click does: a
        bbox-based WMS GetMap source from ``wms.geo.admin.ch`` in the active
        project CRS. Always use this for swisstopo catalog topics — never
        hand-build WMTS/XYZ tile URLs, which mis-render on the swisstopo grid.

        Args:
            bod_id: The geoadmin ``layerBodId`` to load (resolve names first
                with ``search_geoadmin_catalog``).
            name: Optional display name; defaults to the catalog label.

        Returns:
            ``{"success", "bod_id", "name", "uri", "crs", "loaded"}``. ``crs`` is
            the project CRS the WMS layer was requested in (LV95 by default).
        """

        def _run() -> dict[str, Any]:
            try:
                cfg = _layers_config().get(bod_id)
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            if not isinstance(cfg, dict):
                return {"success": False, "error": f"Unknown layerBodId {bod_id!r}."}

            display = name or _strip_tags(cfg.get("label")) or bod_id
            # Load via the swisstopo WMS service exactly as the KADAS geocatalog
            # does on a manual click: a bbox-based WMS GetMap layer in the project
            # CRS. WMS is projection-correct, so it avoids the XYZ/WMTS
            # tiling-scheme trap (LV95 endpoint requested with Web-Mercator tile
            # indices) that silently blanked agent-loaded layers.
            crs = _project_crs(_project())
            uri = _wms_layer_uri(bod_id, crs=crs)

            # Prefer the host iface's add: the KADAS adapter routes this to the
            # native addRasterLayerQuiet (the same kApp->addRasterLayer path the
            # geocatalog uses). Fall back to constructing the layer directly.
            layer: Any | None = None
            try:
                layer = iface.addRasterLayer(uri, display, "wms")
            except TypeError:
                try:
                    layer = iface.addRasterLayer(uri, display)
                except Exception:
                    layer = None
            except Exception:
                layer = None

            if layer is None or (hasattr(layer, "isValid") and not layer.isValid()):
                try:
                    from qgis.core import (  # type: ignore[import-not-found]
                        QgsRasterLayer,
                    )

                    candidate = QgsRasterLayer(uri, display, "wms")
                    if candidate is not None and (
                        not hasattr(candidate, "isValid") or candidate.isValid()
                    ):
                        _project().addMapLayer(candidate)
                        layer = candidate
                except ImportError:
                    pass

            if layer is None or (hasattr(layer, "isValid") and not layer.isValid()):
                return {
                    "success": False,
                    "bod_id": bod_id,
                    "uri": uri,
                    "error": f"QGIS could not load WMS layer {bod_id!r}.",
                }
            if hasattr(iface, "setActiveLayer"):
                try:
                    iface.setActiveLayer(layer)
                except Exception:
                    pass
            try:
                canvas = iface.mapCanvas()
                if hasattr(canvas, "refresh"):
                    canvas.refresh()
            except Exception:
                pass
            return {
                "success": True,
                "bod_id": bod_id,
                "name": display,
                "uri": uri,
                "crs": crs,
                "loaded": True,
            }

        return _on_gui(_run)

    @geo_tool(category="geoadmin", available_in=("full", "fast"))
    def locate_and_zoom(query: str, scale: Optional[float] = None) -> dict[str, Any]:
        """Geocode a place name and recentre the canvas on it.

        Args:
            query: Place name to resolve (e.g. "Matterhorn").
            scale: Optional map scale denominator to apply after centring.

        Returns:
            ``{"success", "label", "lon", "lat"}`` or an error when nothing
            matched.
        """

        def _run() -> dict[str, Any]:
            try:
                locations = _query_locations(query, 1)
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            if not locations:
                return {"success": False, "error": f"No location matched {query!r}."}
            loc = locations[0]
            canvas = iface.mapCanvas()

            point = None
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsCoordinateReferenceSystem,
                    QgsCoordinateTransform,
                    QgsPointXY,
                    QgsProject,
                )

                dst = canvas.mapSettings().destinationCrs()
                transform = QgsCoordinateTransform(
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                    dst,
                    QgsProject.instance(),
                )
                point = transform.transform(QgsPointXY(loc["lon"], loc["lat"]))
            except Exception:
                point = None

            if point is not None and hasattr(canvas, "setCenter"):
                canvas.setCenter(point)
            elif loc.get("bbox") and hasattr(canvas, "setExtent"):
                canvas.setExtent(tuple(loc["bbox"]))
            elif hasattr(canvas, "setCenter"):
                canvas.setCenter(_PointLike(loc["lon"], loc["lat"]))

            if scale is not None and hasattr(canvas, "zoomScale"):
                canvas.zoomScale(float(scale))
            if hasattr(canvas, "refresh"):
                canvas.refresh()
            return {
                "success": True,
                "label": loc["label"],
                "lon": loc["lon"],
                "lat": loc["lat"],
            }

        return _on_gui(_run)

    tools.extend([load_geoadmin_layer, locate_and_zoom])
    return tools


__all__ = ["geoadmin_tools"]
