"""KADAS-configured data sources: geocatalog, place search, and a source manifest.

KADAS decides where its data comes from through its own configuration, not
through anything GeoAgent knows: ``kadas/geodatacatalogs`` lists the catalog
providers (geoadmin, ArcGIS REST/portal, VBS, possibly a bundled file),
``search/*url`` picks the online or the offline (localhost) search service
depending on ``kadas/isOffline``, and the project names its heightmap. A
deployment customises all of this through its ``settings_full.ini``.

These tools therefore never hold an endpoint. They drive KADAS' own live
objects so the agent sees exactly what the user sees:

    * ``search_catalog`` / ``load_catalog_layer`` — walk the live catalog panel
      (``mCatalogBrowser``) and load an entry by emitting its ``layerSelected``
      signal, the same path a click in the panel takes (URI adjustment,
      sublayers, auth, proxy all handled by KADAS).
    * ``search_location`` / ``locate_and_zoom`` — run KADAS' own locator
      filters, local first: loaded layers, pins, Swiss locations, world
      locations. The location filters switch to the offline service themselves.
    * ``describe_data_sources`` — a short manifest (mode, catalog providers,
      search endpoints, heightmap, local datasets) with hosts but no URLs, so
      the model knows where data comes from without being able to build
      requests from it.

The catalog widget name, item roles, ``layerSelected`` signal and filter
classes are identical in KADAS 2.3 and KADAS 3, so there is a single code path.

Import-safe outside KADAS/QGIS: ``qgis``/``kadas`` are imported lazily inside
the tool bodies.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import parse_qsl, urlparse

from geoagent.core.decorators import geo_tool
from geoagent.tools._qt_marshal import run_on_qt_gui_thread

CATALOG_WIDGET_NAME = "mCatalogBrowser"
# KadasCatalogBrowser::CatalogItem roles, offsets from Qt::UserRole.
_URI_ROLE_OFFSET = 1
_METADATA_URL_ROLE_OFFSET = 2
_SUBLAYERS_ROLE_OFFSET = 3
# Separator of the human-readable catalog id: "<category> > <sub> > <title>".
CATALOG_ID_SEP = " > "

# KADAS locator filters in the order they are consulted: local first.
PLACE_SOURCES: tuple[tuple[str, str], ...] = (
    ("local_data", "KadasLocalDataSearchFilter"),
    ("pins", "KadasPinSearchProvider"),
    ("swiss_locations", "KadasLocationSearchFilter"),
    ("world_locations", "KadasWorldLocationSearchProvider"),
)
_SEARCH_TIMEOUT_MS = 15000

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_FILE_PROVIDERS = {"ogr", "gdal", "spatialite", "delimitedtext", "mbtiles"}


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested without QGIS)
# --------------------------------------------------------------------------- #


def endpoint_kind(url: str) -> str:
    """Classify a configured endpoint without exposing it.

    Returns ``"local file"`` for file paths (KADAS resolves relative catalog
    paths against its data dir), ``"local service"`` for loopback hosts,
    ``"remote (<host>)"`` otherwise, and ``"not configured"`` for an empty value.
    """
    url = (url or "").strip()
    if not url:
        return "not configured"
    parsed = urlparse(url)
    # A one-letter scheme is a Windows drive ("C:/data/catalog.json").
    if parsed.scheme in ("", "file") or len(parsed.scheme) == 1:
        return "local file"
    host = parsed.hostname or ""
    if host in _LOCAL_HOSTS:
        return "local service"
    return f"remote ({host})"


def parse_catalog_config(raw: str) -> list[dict[str, str]]:
    """Parse ``kadas/geodatacatalogs`` (``type=..&url=..`` entries joined by ``;;``)."""
    providers = []
    for entry in (raw or "").strip().strip('"').split(";;"):
        if not entry.strip():
            continue
        params = dict(parse_qsl(entry.strip(), keep_blank_values=True))
        providers.append(
            {
                "type": params.get("type", "unknown"),
                "location": endpoint_kind(params.get("url", "")),
            }
        )
    return providers


def parse_bool_setting(value: Any) -> bool:
    """QgsSettings returns a bool or the string ``"true"``/``"false"``."""
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def match_catalog_entries(
    entries: list[dict[str, Any]], query: str, limit: int
) -> list[dict[str, Any]]:
    """Rank catalog leaves whose title/category contain every query token.

    A token found in the title scores higher than one found only in the
    category path, so "swissimage" ranks the SWISSIMAGE layers above layers
    that merely sit in an "Imagery" folder.
    """
    tokens = [t for t in query.lower().split() if t]
    if not tokens:
        return []
    scored = []
    for order, entry in enumerate(entries):
        title = str(entry["title"]).lower()
        path = str(entry["category"]).lower()
        if not all(t in title or t in path for t in tokens):
            continue
        score = sum(2 if t in title else 1 for t in tokens)
        if title == query.lower().strip():
            score += 10
        scored.append((-score, order, entry))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [entry for _score, _order, entry in scored[: max(1, limit)]]


def uri_source_kind(provider_key: str, uri: str) -> str:
    """``"local"`` for file-backed or loopback sources, else ``"remote"``."""
    if provider_key in _FILE_PROVIDERS and "://" not in uri:
        return "local"
    params = dict(parse_qsl(uri, keep_blank_values=True))
    url = params.get("url", "")
    if url and endpoint_kind(url) in ("local file", "local service"):
        return "local"
    return "remote"


# --------------------------------------------------------------------------- #
# Tool factory
# --------------------------------------------------------------------------- #


def kadas_sources_tools(iface: Any = None, project: Optional[Any] = None) -> list[Any]:
    """Build the KADAS data-source tools bound to a live KADAS ``iface``.

    Args:
        iface: The KADAS ``iface`` (or ``KadasIfaceAdapter``). It must expose
            ``findObject`` and ``mapCanvas``.
        project: Optional ``QgsProject``; falls back to ``QgsProject.instance()``.
    """

    def _project() -> Any:
        if project is not None:
            return project
        from qgis.core import QgsProject  # type: ignore[import-not-found]

        return QgsProject.instance()

    def _user_role() -> int:
        from qgis.PyQt.QtCore import Qt  # type: ignore[import-not-found]

        role = getattr(Qt, "UserRole", None)  # Qt5
        return role if role is not None else Qt.ItemDataRole.UserRole  # Qt6

    def _catalog_browser() -> Any:
        from qgis.PyQt import sip  # type: ignore[import-not-found]
        from kadas.kadasgui import KadasCatalogBrowser  # type: ignore[import-not-found]

        widget = iface.findObject(CATALOG_WIDGET_NAME)
        if widget is None:
            raise RuntimeError("KADAS catalog panel (mCatalogBrowser) not found.")
        return sip.cast(widget, KadasCatalogBrowser)

    def _catalog_model(browser: Any) -> Any:
        from qgis.PyQt.QtCore import QSortFilterProxyModel  # type: ignore[import-not-found]
        from qgis.PyQt.QtWidgets import QTreeView  # type: ignore[import-not-found]

        model = browser.findChild(QTreeView).model()
        # Bypass the panel's text filter so a user's typed filter can't hide items.
        if isinstance(model, QSortFilterProxyModel):
            return model.sourceModel()
        return model

    def _catalog_leaves(model: Any) -> list[dict[str, Any]]:
        from qgis.core import QgsMimeDataUtils  # type: ignore[import-not-found]

        uri_role = _user_role() + _URI_ROLE_OFFSET
        leaves: list[dict[str, Any]] = []

        def walk(parent: Any, path: list[str]) -> None:
            for row in range(model.rowCount(parent)):
                index = model.index(row, 0, parent)
                title = str(model.data(index) or "")
                if model.rowCount(index):
                    walk(index, path + [title])
                    continue
                encoded = model.data(index, uri_role)
                if not encoded:  # e.g. the disabled "Offline" placeholder
                    continue
                uri = QgsMimeDataUtils.Uri(encoded)
                leaves.append(
                    {
                        "catalog_id": CATALOG_ID_SEP.join(path + [title]),
                        "title": title,
                        "category": CATALOG_ID_SEP.join(path),
                        "service": uri.providerKey,
                        "layer_type": uri.layerType,
                        "source": uri_source_kind(uri.providerKey, uri.uri),
                        "_index": index,
                    }
                )

        from qgis.PyQt.QtCore import QModelIndex  # type: ignore[import-not-found]

        walk(QModelIndex(), [])
        return leaves

    def _public(entry: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in entry.items() if not k.startswith("_")}

    def _locator_result_data(result: Any) -> dict[str, Any]:
        # QGIS 4 exposes userData as a property; QGIS 3 (KADAS 2) as a method.
        data = result.userData() if callable(result.userData) else result.userData
        return dict(data or {})

    def _to_wgs84(geometry_or_point: Any, crs: Any) -> Any:
        from qgis.core import (  # type: ignore[import-not-found]
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
        )

        transform = QgsCoordinateTransform(
            crs, QgsCoordinateReferenceSystem("EPSG:4326"), _project()
        )
        return transform.transform(geometry_or_point)

    def _place_from_result(source: str, result: Any) -> dict[str, Any]:
        from qgis.core import (  # type: ignore[import-not-found]
            QgsCoordinateReferenceSystem,
            QgsPointXY,
        )

        data = _locator_result_data(result)
        place: dict[str, Any] = {
            "label": result.displayString,
            "source": source,
            "group": result.group,
        }
        if source == "local_data":
            layer = _project().mapLayer(data.get("layer_id", ""))
            feature = layer.getFeature(data["feature_id"]) if layer else None
            if feature is None or not feature.isValid() or not feature.hasGeometry():
                return place
            geom = feature.geometry()
            centroid = _to_wgs84(geom.centroid().asPoint(), layer.crs())
            bbox = _to_wgs84(geom.boundingBox(), layer.crs())
            place["layer"] = layer.name()
            place.update(lon=centroid.x(), lat=centroid.y())
            place["bbox"] = [
                bbox.xMinimum(),
                bbox.yMinimum(),
                bbox.xMaximum(),
                bbox.yMaximum(),
            ]
            return place
        pos = data.get("pos")
        if pos is not None:
            point = QgsPointXY(pos)
            if source == "pins":
                point = _to_wgs84(
                    point, QgsCoordinateReferenceSystem(data.get("crs", ""))
                )
            place.update(lon=point.x(), lat=point.y())
        bbox = data.get("bbox")
        if bbox is not None and not bbox.isEmpty():
            place["bbox"] = [
                bbox.xMinimum(),
                bbox.yMinimum(),
                bbox.xMaximum(),
                bbox.yMaximum(),
            ]
        return place

    def _run_filter(class_name: str, query: str) -> tuple[Any, list[Any]]:
        """Run one KADAS locator filter and wait for its results (GUI thread)."""
        import kadas.kadasgui as kadasgui  # type: ignore[import-not-found]
        from qgis.core import QgsLocator, QgsLocatorContext  # type: ignore[import-not-found]
        from qgis.PyQt.QtCore import QEventLoop, QTimer  # type: ignore[import-not-found]

        locator_filter = getattr(kadasgui, class_name)(iface.mapCanvas())
        locator = QgsLocator()
        locator.registerFilter(locator_filter)
        results: list[Any] = []
        locator.foundResult.connect(results.append)
        loop = QEventLoop()
        locator.finished.connect(loop.quit)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(_SEARCH_TIMEOUT_MS)
        locator.fetchResults(query, QgsLocatorContext())
        loop.exec()
        timeout.stop()
        if locator.isRunning():
            locator.cancel()
        # Keep the locator alive with the filter: it owns the filter.
        return (locator, locator_filter), results

    def _search(query: str, limit: int, source: Optional[str]) -> dict[str, Any]:
        known = [name for name, _cls in PLACE_SOURCES]
        if source is not None and source not in known:
            return {
                "success": False,
                "error": f"Unknown source {source!r}; use one of {known}.",
            }
        tried = []
        for name, class_name in PLACE_SOURCES:
            if source is not None and name != source:
                continue
            tried.append(name)
            handles, results = _run_filter(class_name, query)
            # Rank like the KADAS search box: municipalities/places above
            # gazetteer entries. Stable, so the service order breaks ties.
            results.sort(key=lambda r: -getattr(r, "groupScore", 0))
            if results:
                return {
                    "handles": handles,
                    "results": results[: max(1, limit)],
                    "source": name,
                    "sources_tried": tried,
                }
        return {"handles": None, "results": [], "source": None, "sources_tried": tried}

    @geo_tool(category="kadas_sources", available_in=("full", "fast"))
    def describe_data_sources() -> dict[str, Any]:
        """Describe where this KADAS installation gets its data from.

        Reads KADAS' own configuration (not a hardcoded list): online/offline
        mode, the configured catalog providers, which place-search service is
        active, the project heightmap, and which loaded layers are local files.
        Call it when you need to know whether data is local or remote, or to
        explain to the user where a result came from. It returns hosts, never
        URLs: always use the dedicated tools to reach data.
        """

        def _run() -> dict[str, Any]:
            from qgis.core import QgsSettings  # type: ignore[import-not-found]

            settings = QgsSettings()
            offline = parse_bool_setting(settings.value("kadas/isOffline", False))
            suffix = "offline" if offline else ""
            swiss = settings.value(f"search/location{suffix}searchurl", "")
            world = settings.value(f"search/worldlocation{suffix}searchurl", "")

            try:
                catalog_entries = len(
                    _catalog_leaves(_catalog_model(_catalog_browser()))
                )
            except Exception as exc:
                catalog_entries = f"unavailable: {exc}"

            proj = _project()
            heightmap_id = proj.readEntry("Heightmap", "layer")[0]
            heightmap = proj.mapLayer(heightmap_id) if heightmap_id else None
            local_layers, remote_layers = [], 0
            for layer in proj.mapLayers().values():
                kind = uri_source_kind(layer.providerType(), layer.source())
                if kind == "local":
                    local_layers.append(layer.name())
                else:
                    remote_layers += 1

            return {
                "success": True,
                "mode": "offline" if offline else "online",
                "mode_note": "Detected by KADAS at startup (reachability check).",
                "catalog": {
                    "providers": parse_catalog_config(
                        str(settings.value("kadas/geodatacatalogs", ""))
                    ),
                    "entries": catalog_entries,
                },
                "place_search_order": [
                    "local_data: attributes of loaded vector layers",
                    "pins: KADAS pins",
                    f"swiss_locations: {endpoint_kind(str(swiss))}",
                    f"world_locations: {endpoint_kind(str(world))}",
                ],
                "heightmap": (
                    {
                        "layer": heightmap.name(),
                        "source": uri_source_kind(
                            heightmap.providerType(), heightmap.source()
                        ),
                    }
                    if heightmap is not None
                    else None
                ),
                "local_layers": local_layers[:30],
                "remote_layer_count": remote_layers,
            }

        return run_on_qt_gui_thread(_run)

    @geo_tool(category="kadas_sources", available_in=("full", "fast"))
    def search_catalog(query: str, limit: int = 10) -> dict[str, Any]:
        """Search the KADAS geocatalog, exactly as the user's catalog panel shows it.

        Matches the query words against layer titles and their category path in
        whatever catalogs this KADAS is configured with (local or remote). Use
        it to find a layer for a topic ("swissimage", "hydrography tlm",
        "national map"), then load the result with ``load_catalog_layer``.

        Args:
            query: Words to match, e.g. "swissimage" or "tlm forest".
            limit: Maximum number of entries to return.

        Returns:
            ``{"success", "count", "entries": [{"catalog_id", "title",
            "category", "service", "layer_type", "source"}]}``. ``source`` is
            ``local`` or ``remote``.
        """

        def _run() -> dict[str, Any]:
            leaves = _catalog_leaves(_catalog_model(_catalog_browser()))
            if not leaves:
                return {
                    "success": False,
                    "error": "The KADAS catalog is empty: its providers are "
                    "unreachable or still loading.",
                }
            matches = match_catalog_entries(leaves, query, limit)
            return {
                "success": True,
                "count": len(matches),
                "entries": [_public(entry) for entry in matches],
            }

        return run_on_qt_gui_thread(_run)

    # No requires_confirmation: adding a catalog layer is benign and reversible,
    # and gating it would make "Inspect only" strip the loader (see geoadmin.py).
    @geo_tool(category="kadas_sources", available_in=("full", "fast"))
    def load_catalog_layer(catalog_id: str) -> dict[str, Any]:
        """Load a KADAS geocatalog entry, the same way a click in the catalog panel does.

        Args:
            catalog_id: The ``catalog_id`` returned by ``search_catalog``.

        Returns:
            ``{"success", "catalog_id", "loaded": [{"name", "valid"}]}``.
        """

        def _run() -> dict[str, Any]:
            from qgis.core import QgsMimeDataUtils  # type: ignore[import-not-found]

            browser = _catalog_browser()
            model = _catalog_model(browser)
            entry = next(
                (e for e in _catalog_leaves(model) if e["catalog_id"] == catalog_id),
                None,
            )
            if entry is None:
                return {
                    "success": False,
                    "error": f"No catalog entry {catalog_id!r}; call search_catalog first.",
                }
            index = entry["_index"]
            role = _user_role()
            proj = _project()
            before = set(proj.mapLayers())
            browser.layerSelected.emit(
                QgsMimeDataUtils.Uri(model.data(index, role + _URI_ROLE_OFFSET)),
                model.data(index, role + _METADATA_URL_ROLE_OFFSET) or "",
                model.data(index, role + _SUBLAYERS_ROLE_OFFSET) or [],
            )
            added = [proj.mapLayer(i) for i in set(proj.mapLayers()) - before]
            if not added:
                return {
                    "success": False,
                    "error": "KADAS added no layer for this entry.",
                }
            return {
                "success": True,
                "catalog_id": catalog_id,
                "loaded": [{"name": l.name(), "valid": l.isValid()} for l in added],
            }

        return run_on_qt_gui_thread(_run)

    @geo_tool(category="kadas_sources", available_in=("full", "fast"))
    def search_location(
        query: str, limit: int = 5, source: Optional[str] = None
    ) -> dict[str, Any]:
        """Find a place with KADAS' own search, local data first.

        Sources are consulted in order and the first one with matches wins:
        ``local_data`` (attributes of loaded vector layers), ``pins``,
        ``swiss_locations`` and ``world_locations`` (KADAS' configured
        location services, which switch to the offline service when KADAS is
        offline). Pass ``source`` to query only one of them, e.g.
        ``source="swiss_locations"`` when local hits are not the place meant.

        Args:
            query: Place or feature name, e.g. "Zürich" or "Thunplatz, Bern".
            limit: Maximum number of matches to return.
            source: Optional single source to query.

        Returns:
            ``{"success", "source", "sources_tried", "count", "locations":
            [{"label", "source", "group", "lon", "lat", "bbox"?}]}`` in WGS84.
        """

        def _run() -> dict[str, Any]:
            found = _search(query, limit, source)
            if "error" in found:
                return found
            locations = [
                _place_from_result(found["source"], r) for r in found["results"]
            ]
            return {
                "success": bool(locations),
                "source": found["source"],
                "sources_tried": found["sources_tried"],
                "count": len(locations),
                "locations": locations,
                **({} if locations else {"error": f"No match for {query!r}."}),
            }

        return run_on_qt_gui_thread(_run)

    @geo_tool(category="kadas_sources", available_in=("full", "fast"))
    def locate_and_zoom(query: str, source: Optional[str] = None) -> dict[str, Any]:
        """Find a place with KADAS' own search (local data first) and zoom to it.

        Uses the same sources and order as ``search_location`` and then lets
        KADAS zoom to its top-ranked match exactly as if the user had picked it
        in the search box. For ambiguous names (a "Matterhorn" query ranks a
        gondola lift above the peak), call ``search_location``, pick the right
        match, and zoom to its bbox with ``zoom_to_extent``.

        Args:
            query: Place or feature name, e.g. "Matterhorn".
            source: Optional single source to query (see ``search_location``).

        Returns:
            ``{"success", "source", "sources_tried", "location"}``.
        """

        def _run() -> dict[str, Any]:
            found = _search(query, 1, source)
            if "error" in found:
                return found
            if not found["results"]:
                return {
                    "success": False,
                    "sources_tried": found["sources_tried"],
                    "error": f"No match for {query!r}.",
                }
            _locator, locator_filter = found["handles"]
            result = found["results"][0]
            location = _place_from_result(found["source"], result)
            locator_filter.triggerResult(result)
            return {
                "success": True,
                "source": found["source"],
                "sources_tried": found["sources_tried"],
                "location": location,
            }

        return run_on_qt_gui_thread(_run)

    return [
        describe_data_sources,
        search_catalog,
        load_catalog_layer,
        search_location,
        locate_and_zoom,
    ]
