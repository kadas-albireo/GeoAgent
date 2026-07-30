"""KADAS-native OpenStreetMap tools (basemap + Overpass vector queries).

Previously the only way the agent could add OSM was to hand-build an XYZ tile
URL (``https://tile.openstreetmap.org/{z}/{x}/{y}.png``) and push it through the
generic ``add_xyz_tile_layer``. That works for a raster backdrop but is fragile
(easy to malform the ``{z}/{x}/{y}`` braces — see the Geoadmin XYZ bug) and
gives the agent *pixels*, never queryable OSM features.

This module replaces that with two purpose-built, fully in-process tools:

* ``add_osm_basemap`` — load the canonical OSM raster basemap through the same
  provider-backed path KADAS uses for every other tile layer (correct,
  well-formed URL and attribution baked in; the agent never composes the URL).
* ``query_osm_features`` — run an Overpass API query and load the result as a
  **native in-memory** :class:`QgsVectorLayer` (points / lines / polygons),
  so the features are real, selectable, styleable QGIS geometries.

Everything runs in-process: the Overpass fetch goes through QGIS' own network
stack (:class:`QgsBlockingNetworkRequest`, which honours KADAS' proxy/auth
settings) with a plain ``urllib`` fallback for headless tests. There is **no**
``curl``/``wget``/``ogr2ogr`` subprocess, no temp files, and no shell.

The module is import-safe outside KADAS/QGIS: ``qgis`` is imported lazily inside
the tool bodies, so it (and its unit tests) import cleanly in plain CI.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from geoagent.core.decorators import geo_tool
from geoagent.tools._qt_marshal import run_on_qt_gui_thread

# Canonical, well-formed OSM raster basemaps. The agent picks a style name; the
# URL template is never LLM-composed (that is exactly what used to break).
OSM_BASEMAPS: dict[str, dict[str, str]] = {
    "standard": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors",
    },
    "humanitarian": {
        "url": "https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors, Humanitarian OSM Team",
    },
    "cyclosm": {
        "url": "https://a.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors, CyclOSM",
    },
}

# Overpass endpoint. Overridable via ``GEOAGENT_OVERPASS_URL`` so deployments
# can point at a mirror or a self-hosted Overpass instance.
OVERPASS_ENDPOINT = os.environ.get(
    "GEOAGENT_OVERPASS_URL", "https://overpass-api.de/api/interpreter"
)


def _build_overpass_query(
    tags: dict[str, str],
    bbox: tuple[float, float, float, float],
    limit: int,
) -> str:
    """Build an Overpass QL query for ``tags`` within ``bbox`` (S,W,N,E order).

    ``bbox`` is passed as ``(min_lon, min_lat, max_lon, max_lat)`` (the WGS84
    convention used elsewhere) and reordered to Overpass' ``(south, west,
    north, east)``.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    area = f"({min_lat},{min_lon},{max_lat},{max_lon})"
    selector = "".join(f'["{k}"="{v}"]' for k, v in tags.items())
    # Query nodes, ways and relations, and emit geometry so ways/relations carry
    # their coordinates inline (``out geom``) rather than bare node references.
    return (
        f"[out:json][timeout:25];"
        f"(node{selector}{area};way{selector}{area};relation{selector}{area};);"
        f"out geom {int(limit)};"
    )


def _fetch_overpass(query: str) -> dict[str, Any]:
    """POST an Overpass query and return the parsed JSON.

    Prefers QGIS' native :class:`QgsBlockingNetworkRequest` (respects KADAS'
    configured network proxy/authentication) and falls back to ``urllib`` when
    QGIS is not importable (headless CI).
    """
    data = query.encode("utf-8")
    try:
        from qgis.core import (  # type: ignore[import-not-found]
            QgsBlockingNetworkRequest,
        )
        from qgis.PyQt.QtCore import QUrl  # type: ignore[import-not-found]
        from qgis.PyQt.QtNetwork import (  # type: ignore[import-not-found]
            QNetworkRequest,
        )

        request = QNetworkRequest(QUrl(OVERPASS_ENDPOINT))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )
        blocking = QgsBlockingNetworkRequest()
        blocking.post(request, data)
        reply = blocking.reply()
        payload = bytes(reply.content())
        return json.loads(payload.decode("utf-8"))
    except ImportError:
        import urllib.request

        req = urllib.request.Request(
            OVERPASS_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))


def _element_geometry(element: dict[str, Any]) -> tuple[Optional[str], Any]:
    """Return ``(geometry_kind, coords)`` for one Overpass element.

    ``geometry_kind`` is ``"point"``, ``"line"`` or ``"polygon"``; ``coords`` is
    ``(lon, lat)`` for a point or a list of ``(lon, lat)`` for a way. Returns
    ``(None, None)`` when the element has no usable geometry.
    """
    etype = element.get("type")
    if etype == "node" and "lat" in element and "lon" in element:
        return "point", (float(element["lon"]), float(element["lat"]))
    geometry = element.get("geometry")
    if isinstance(geometry, list) and geometry:
        ring = [
            (float(pt["lon"]), float(pt["lat"]))
            for pt in geometry
            if "lon" in pt and "lat" in pt
        ]
        if len(ring) < 2:
            return None, None
        # A closed way tagged as an area is a polygon; otherwise a line.
        tags = element.get("tags", {}) or {}
        closed = ring[0] == ring[-1]
        is_area = closed and (
            tags.get("area") == "yes"
            or "building" in tags
            or "landuse" in tags
            or "leisure" in tags
            or "natural" in tags
        )
        return ("polygon" if is_area else "line"), ring
    return None, None


def osm_tools(iface: Any = None, project: Optional[Any] = None) -> list[Any]:
    """Build the KADAS-native OSM tool set bound to a live ``iface``.

    Args:
        iface: A KADAS/QGIS ``iface`` (or adapter). ``None`` returns an empty
            list, mirroring the other tool factories.
        project: Optional ``QgsProject``; falls back to ``QgsProject.instance()``.

    Returns:
        A list of Strands tool objects (empty when ``iface`` is ``None``).
    """
    if iface is None:
        return []

    def _on_gui(func: Any) -> Any:
        return run_on_qt_gui_thread(func)

    def _project() -> Any:
        if project is not None:
            return project
        if hasattr(iface, "project"):
            try:
                proj = iface.project()
                if proj is not None:
                    return proj
            except Exception:
                pass
        from qgis.core import QgsProject  # type: ignore[import-not-found]

        return QgsProject.instance()

    def _refresh() -> None:
        try:
            canvas = iface.mapCanvas()
            if hasattr(canvas, "refresh"):
                canvas.refresh()
        except Exception:
            pass

    @geo_tool(category="osm", available_in=("full", "fast"))
    def add_osm_basemap(style: str = "standard") -> dict[str, Any]:
        """Add an OpenStreetMap raster basemap the KADAS-native way.

        Loads a canonical, well-formed OSM XYZ source (the agent never composes
        the tile URL) through the same provider path KADAS uses for its own tile
        layers, so it actually renders on the KADAS canvas.

        Args:
            style: ``standard`` (default), ``humanitarian`` or ``cyclosm``.

        Returns:
            ``{"success", "name", "style"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            spec = OSM_BASEMAPS.get(str(style).strip().lower())
            if spec is None:
                return {
                    "success": False,
                    "error": (
                        f"Unknown OSM style {style!r}. Use one of: "
                        + ", ".join(sorted(OSM_BASEMAPS))
                    ),
                }
            name = f"OpenStreetMap ({style})"
            # Reuse the shared XYZ URI builder (single source of truth for the
            # brace/CRS handling that the geoadmin brace bug taught us to get
            # right) instead of hand-assembling a second tile URI here.
            from geoagent.tools.qgis import _xyz_tile_uri

            uri = _xyz_tile_uri(
                spec["url"], zmin=0, zmax=19, attribution=spec["attribution"]
            )
            try:
                try:
                    layer = iface.addRasterLayer(uri, name, "wms")
                except TypeError:
                    layer = iface.addRasterLayer(uri, name)
                if layer is None or (hasattr(layer, "isValid") and not layer.isValid()):
                    return {
                        "success": False,
                        "error": "KADAS rejected the OSM tile source.",
                    }
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "name": name, "style": style}

        return _on_gui(_run)

    @geo_tool(category="osm", available_in=("full", "fast"), long_running=True)
    def query_osm_features(
        tags: dict[str, str],
        bbox: list[float],
        limit: int = 500,
    ) -> dict[str, Any]:
        """Query live OSM features via Overpass and load them as native layers.

        Fetches matching OSM elements inside ``bbox`` and builds in-memory
        :class:`QgsVectorLayer` layers (one per geometry type present) — real,
        selectable QGIS features, not tiles. Runs entirely in-process: the
        Overpass call uses QGIS' own network stack, with **no** subprocess.

        Args:
            tags: OSM key/value selectors, e.g. ``{"amenity": "cafe"}`` or
                ``{"highway": "primary"}``. All are AND-combined.
            bbox: WGS84 ``[min_lon, min_lat, max_lon, max_lat]``.
            limit: Maximum number of elements to return.

        Returns:
            ``{"success", "count", "layers": [{"name", "geometry", "features"}],
            "query"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            if not isinstance(tags, dict) or not tags:
                return {
                    "success": False,
                    "error": "Provide at least one OSM tag, e.g. {'amenity': 'cafe'}.",
                }
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                return {
                    "success": False,
                    "error": "bbox must be [min_lon, min_lat, max_lon, max_lat].",
                }
            query = _build_overpass_query(
                {str(k): str(v) for k, v in tags.items()},
                (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                int(limit),
            )
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsFeature,
                    QgsField,
                    QgsGeometry,
                    QgsLineString,
                    QgsPointXY,
                    QgsProject,
                    QgsVectorLayer,
                )
                from qgis.PyQt.QtCore import QVariant  # type: ignore[import-not-found]

                result = _fetch_overpass(query)
                elements = (
                    result.get("elements", []) if isinstance(result, dict) else []
                )

                buckets: dict[str, list[dict[str, Any]]] = {
                    "point": [],
                    "line": [],
                    "polygon": [],
                }
                for element in elements:
                    if not isinstance(element, dict):
                        continue
                    kind, coords = _element_geometry(element)
                    if kind is None:
                        continue
                    buckets[kind].append(
                        {
                            "id": element.get("id"),
                            "coords": coords,
                            "tags": element.get("tags", {}) or {},
                        }
                    )

                proj = _project() or QgsProject.instance()
                label = "+".join(f"{k}={v}" for k, v in tags.items())
                qgis_geom = {
                    "point": "Point",
                    "line": "LineString",
                    "polygon": "Polygon",
                }
                layers_out: list[dict[str, Any]] = []
                for kind, feats in buckets.items():
                    if not feats:
                        continue
                    name = f"OSM {label} ({kind}s)"
                    layer = QgsVectorLayer(
                        f"{qgis_geom[kind]}?crs=EPSG:4326", name, "memory"
                    )
                    dp = layer.dataProvider()
                    dp.addAttributes(
                        [
                            QgsField("osm_id", QVariant.String),
                            QgsField("name", QVariant.String),
                            QgsField("tags", QVariant.String),
                        ]
                    )
                    layer.updateFields()
                    for feat in feats:
                        qf = QgsFeature(layer.fields())
                        coords = feat["coords"]
                        if kind == "point":
                            geom = QgsGeometry.fromPointXY(
                                QgsPointXY(coords[0], coords[1])
                            )
                        else:
                            pts = [QgsPointXY(x, y) for x, y in coords]
                            if kind == "polygon":
                                geom = QgsGeometry.fromPolygonXY([pts])
                            else:
                                geom = QgsGeometry(QgsLineString(pts))
                        qf.setGeometry(geom)
                        ftags = feat["tags"]
                        qf.setAttributes(
                            [
                                str(feat["id"]),
                                str(ftags.get("name", "")),
                                json.dumps(ftags, ensure_ascii=False)[:2000],
                            ]
                        )
                        dp.addFeature(qf)
                    layer.updateExtents()
                    proj.addMapLayer(layer)
                    layers_out.append(
                        {"name": name, "geometry": kind, "features": len(feats)}
                    )
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}

            total = sum(item["features"] for item in layers_out)
            if not layers_out:
                return {
                    "success": True,
                    "count": 0,
                    "layers": [],
                    "query": query,
                    "note": "No OSM features matched the tags in that bbox.",
                }
            return {
                "success": True,
                "count": total,
                "layers": layers_out,
                "query": query,
            }

        return _on_gui(_run)

    return [add_osm_basemap, query_osm_features]


__all__ = ["osm_tools", "OSM_BASEMAPS", "OVERPASS_ENDPOINT"]
