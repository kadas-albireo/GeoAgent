"""KADAS-native map-item tools (markers, shapes, text annotations).

Vanilla QGIS has no concept of KADAS' drawable *map items* — the
``Kadas*Item`` classes in ``kadas.kadasgui`` (markers, circles, rectangles,
polygons, lines, text) that live on a ``KadasItemLayer`` and are what KADAS
users create through the redlining / annotation tools. The shared QGIS tool
surface (:mod:`geoagent.tools.qgis`) therefore can't place a marker or draw an
annotation; on KADAS the agent would otherwise have to hand-write KADAS Python
through ``run_pyqgis_script`` and hope it knows the API.

These tools expose that KADAS-native surface directly so the agent can *use
KADAS' own tools* rather than reverse-engineer them:

    * ``add_map_marker`` / ``add_text_annotation`` — point markers & labels
    * ``add_map_circle`` / ``add_map_rectangle`` / ``add_map_polygon`` — shapes
    * ``clear_annotations`` — remove the agent's annotation layer (destructive)

All items are collected on a single reusable ``KadasItemLayer`` named
``GeoAgent Annotations``. Inputs are WGS84 lon/lat (the convention used in
user-facing prompts); circle radius is in metres.

The module is import-safe outside KADAS/QGIS: ``kadas`` and ``qgis`` are
imported lazily inside the GUI tool bodies, never at module load, so the module
(and its unit tests) import cleanly in plain CI. The map-item construction is
written defensively because it can only be exercised against a live KADAS
runtime; failures return a structured error instead of raising.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from geoagent.core.decorators import geo_tool
from geoagent.tools._qt_marshal import run_on_qt_gui_thread

# The single annotation layer the agent owns. Reused across calls and the unit
# that ``clear_annotations`` empties.
ANNOTATION_LAYER_NAME = "GeoAgent Annotations"


def _circle_ring(
    cx: float, cy: float, radius: float, segments: int = 64
) -> list[tuple[float, float]]:
    """Return a closed ring approximating a circle in projected (metre) units.

    Pure geometry helper (no QGIS) so it is unit-testable: given a centre and
    radius in the same planar units, it returns ``segments`` points plus a
    repeated first point to close the ring.
    """
    seg = max(8, int(segments))
    ring = [
        (
            cx + radius * math.cos(2.0 * math.pi * i / seg),
            cy + radius * math.sin(2.0 * math.pi * i / seg),
        )
        for i in range(seg)
    ]
    ring.append(ring[0])
    return ring


def kadas_tools(iface: Any = None, project: Optional[Any] = None) -> list[Any]:
    """Build the KADAS-native annotation tool set bound to a live ``iface``.

    Args:
        iface: A KADAS/QGIS ``iface`` (or :class:`KadasIfaceAdapter`). ``None``
            returns an empty list, mirroring :func:`geoagent.tools.qgis.qgis_tools`.
        project: Optional ``QgsProject``; falls back to ``QgsProject.instance()``.

    Returns:
        A list of Strands tool objects (empty when ``iface`` is ``None``).
    """
    if iface is None:
        return []

    def _on_gui(func: Any) -> Any:
        """Run a callable on the Qt GUI thread."""
        return run_on_qt_gui_thread(func)

    def _project() -> Any:
        """Return the configured project or resolve it from the iface."""
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

    def _crs(authid: str) -> Any:
        from qgis.core import QgsCoordinateReferenceSystem  # type: ignore[import-not-found]

        return QgsCoordinateReferenceSystem(authid)

    def _authid(crs: Any) -> Optional[str]:
        """Return a CRS auth id (e.g. ``EPSG:3857``) or ``None``."""
        try:
            return crs.authid() or None
        except Exception:
            return None

    def _get_or_create_layer() -> Any:
        """Return the reusable ``GeoAgent Annotations`` KadasItemLayer."""
        from kadas.kadasgui import KadasItemLayer  # type: ignore[import-not-found]

        proj = _project()
        for layer in proj.mapLayers().values():
            if (
                isinstance(layer, KadasItemLayer)
                and layer.name() == ANNOTATION_LAYER_NAME
            ):
                return layer
        layer = KadasItemLayer(ANNOTATION_LAYER_NAME, _crs("EPSG:3857"))
        proj.addMapLayer(layer)
        return layer

    def _refresh() -> None:
        try:
            canvas = iface.mapCanvas()
            if hasattr(canvas, "refresh"):
                canvas.refresh()
        except Exception:
            pass

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def add_map_marker(
        lon: float, lat: float, label: Optional[str] = None
    ) -> dict[str, Any]:
        """Drop a point marker on the KADAS canvas at a WGS84 coordinate.

        Args:
            lon: Longitude (WGS84).
            lat: Latitude (WGS84).
            label: Optional marker name shown in the layer / item.

        Returns:
            ``{"success", "lon", "lat", "label"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import (  # type: ignore[import-not-found]
                    KadasItemPos,
                    KadasPointItem,
                )

                layer = _get_or_create_layer()
                item = KadasPointItem(_crs("EPSG:4326"))
                item.setPosition(KadasItemPos(float(lon), float(lat)))
                if label:
                    try:
                        item.setName(str(label))
                    except Exception:
                        pass
                layer.addItem(item)
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "lon": lon, "lat": lat, "label": label}

        return _on_gui(_run)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def add_text_annotation(lon: float, lat: float, text: str) -> dict[str, Any]:
        """Place a text label on the KADAS canvas at a WGS84 coordinate.

        Args:
            lon: Longitude (WGS84).
            lat: Latitude (WGS84).
            text: The label text to display.

        Returns:
            ``{"success", "lon", "lat", "text"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import (  # type: ignore[import-not-found]
                    KadasItemPos,
                    KadasTextItem,
                )

                layer = _get_or_create_layer()
                item = KadasTextItem(_crs("EPSG:4326"))
                item.setPosition(KadasItemPos(float(lon), float(lat)))
                item.setText(str(text))
                layer.addItem(item)
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "lon": lon, "lat": lat, "text": text}

        return _on_gui(_run)

    def _polygon_geometry(ring_xy: list[tuple[float, float]]) -> Any:
        """Build a QgsPolygon abstract geometry from a planar ring."""
        from qgis.core import (  # type: ignore[import-not-found]
            QgsLineString,
            QgsPoint,
            QgsPolygon,
        )

        line = QgsLineString([QgsPoint(x, y) for x, y in ring_xy])
        polygon = QgsPolygon()
        polygon.setExteriorRing(line)
        return polygon

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def add_map_circle(
        lon: float, lat: float, radius_m: float
    ) -> dict[str, Any]:
        """Draw a circle of a given radius (metres) centred on a WGS84 point.

        Args:
            lon: Centre longitude (WGS84).
            lat: Centre latitude (WGS84).
            radius_m: Circle radius in metres.

        Returns:
            ``{"success", "lon", "lat", "radius_m"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsCoordinateTransform,
                    QgsPointXY,
                    QgsProject,
                )

                # Work in Web Mercator metres so the radius is metric.
                transform = QgsCoordinateTransform(
                    _crs("EPSG:4326"), _crs("EPSG:3857"), QgsProject.instance()
                )
                centre = transform.transform(QgsPointXY(float(lon), float(lat)))
                ring = _circle_ring(centre.x(), centre.y(), float(radius_m))
                geom = _polygon_geometry(ring)

                layer = _get_or_create_layer()
                item = _circle_or_polygon_item(_crs("EPSG:3857"))
                item.addPartFromGeometry(geom)
                layer.addItem(item)
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "lon": lon,
                "lat": lat,
                "radius_m": radius_m,
            }

        return _on_gui(_run)

    def _circle_or_polygon_item(crs3857: Any) -> Any:
        """Prefer a native KadasCircleItem; fall back to a polygon item."""
        from kadas.kadasgui import (  # type: ignore[import-not-found]
            KadasCircleItem,
            KadasPolygonItem,
        )

        try:
            return KadasCircleItem(crs3857)
        except Exception:
            return KadasPolygonItem(crs3857)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def add_map_rectangle(
        min_lon: float, min_lat: float, max_lon: float, max_lat: float
    ) -> dict[str, Any]:
        """Draw a rectangle annotation over a WGS84 bounding box.

        Args:
            min_lon: West longitude (WGS84).
            min_lat: South latitude (WGS84).
            max_lon: East longitude (WGS84).
            max_lat: North latitude (WGS84).

        Returns:
            ``{"success", "bbox"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import (  # type: ignore[import-not-found]
                    KadasRectangleItem,
                )

                ring = [
                    (float(min_lon), float(min_lat)),
                    (float(max_lon), float(min_lat)),
                    (float(max_lon), float(max_lat)),
                    (float(min_lon), float(max_lat)),
                    (float(min_lon), float(min_lat)),
                ]
                geom = _polygon_geometry(ring)
                layer = _get_or_create_layer()
                try:
                    item = KadasRectangleItem(_crs("EPSG:4326"))
                except Exception:
                    item = _circle_or_polygon_item(_crs("EPSG:4326"))
                item.addPartFromGeometry(geom)
                layer.addItem(item)
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "bbox": [min_lon, min_lat, max_lon, max_lat],
            }

        return _on_gui(_run)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def add_map_polygon(
        coordinates: list[list[float]], label: Optional[str] = None
    ) -> dict[str, Any]:
        """Draw a polygon annotation from a list of WGS84 ``[lon, lat]`` points.

        Args:
            coordinates: Ordered ``[[lon, lat], ...]`` vertices (WGS84). The ring
                is closed automatically.
            label: Optional text label placed at the polygon centroid.

        Returns:
            ``{"success", "vertices", "label"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import (  # type: ignore[import-not-found]
                    KadasItemPos,
                    KadasPolygonItem,
                    KadasTextItem,
                )

                pts = [(float(p[0]), float(p[1])) for p in coordinates if len(p) >= 2]
                if len(pts) < 3:
                    return {
                        "success": False,
                        "error": "A polygon needs at least 3 vertices.",
                    }
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                geom = _polygon_geometry(pts)
                layer = _get_or_create_layer()
                item = KadasPolygonItem(_crs("EPSG:4326"))
                item.addPartFromGeometry(geom)
                layer.addItem(item)
                if label:
                    cx = sum(x for x, _ in pts[:-1]) / (len(pts) - 1)
                    cy = sum(y for _, y in pts[:-1]) / (len(pts) - 1)
                    text = KadasTextItem(_crs("EPSG:4326"))
                    text.setPosition(KadasItemPos(cx, cy))
                    text.setText(str(label))
                    layer.addItem(text)
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "vertices": len(pts) - 1, "label": label}

        return _on_gui(_run)

    @geo_tool(category="kadas", destructive=True)
    def clear_annotations() -> dict[str, Any]:
        """Remove the agent's ``GeoAgent Annotations`` layer and its items.

        Returns:
            ``{"success", "removed"}`` — ``removed`` is the number of annotation
            layers cleared.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import KadasItemLayer  # type: ignore[import-not-found]

                proj = _project()
                removed = 0
                for layer in list(proj.mapLayers().values()):
                    if (
                        isinstance(layer, KadasItemLayer)
                        and layer.name() == ANNOTATION_LAYER_NAME
                    ):
                        try:
                            proj.removeMapLayer(layer.id())
                        except Exception:
                            proj.removeMapLayer(layer)
                        removed += 1
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "removed": removed}

        return _on_gui(_run)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def list_kadas_item_layers() -> dict[str, Any]:
        """List KADAS-native item layers (Pins, GPX, annotations) in the project.

        These ``KadasItemLayer`` plugin layers hold drawable map items, not QGIS
        vector features, so the generic ``list_project_layers`` only sees their
        extent. Use this to discover them, then ``get_kadas_layer_items`` to read
        the individual items and their coordinates.

        Returns:
            ``{"success", "count", "layers": [{"name", "item_count", "crs"}]}``.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import KadasItemLayer  # type: ignore[import-not-found]

                proj = _project()
                out: list[dict[str, Any]] = []
                for layer in proj.mapLayers().values():
                    if not isinstance(layer, KadasItemLayer):
                        continue
                    try:
                        count = len(layer.items())
                    except Exception:
                        count = None
                    out.append(
                        {
                            "name": layer.name(),
                            "item_count": count,
                            "crs": _authid(layer.crs()),
                        }
                    )
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "count": len(out), "layers": out}

        return _on_gui(_run)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def get_kadas_layer_items(
        layer_name: str, limit: int = 200
    ) -> dict[str, Any]:
        """Read the individual items in a KADAS item layer, with WGS84 coords.

        Resolves the limitation that a ``KadasItemLayer`` (e.g. the Pins layer)
        only exposes a bounding box to generic tools: this enumerates each
        item (markers, shapes, text) with its type, label, and **per-item
        coordinates** transformed to WGS84 lon/lat, plus the native coordinate
        and (for shapes) the geometry WKT.

        Args:
            layer_name: Name of the KADAS item layer (e.g. "Pins").
            limit: Maximum number of items to return.

        Returns:
            ``{"success", "layer", "item_count", "returned",
            "items": [{"id", "type", "label?", "lon", "lat", "native", ...}]}``.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import KadasItemLayer  # type: ignore[import-not-found]
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsCoordinateReferenceSystem,
                    QgsCoordinateTransform,
                    QgsPointXY,
                    QgsProject,
                )

                proj = _project()
                layer = None
                for lyr in proj.mapLayers().values():
                    if isinstance(lyr, KadasItemLayer) and lyr.name() == layer_name:
                        layer = lyr
                        break
                if layer is None:
                    return {
                        "success": False,
                        "error": f"No KADAS item layer named {layer_name!r}.",
                    }

                wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                tcache: dict[str, Any] = {}

                def _to_wgs84(x: float, y: float, src: Any) -> tuple[float, float]:
                    key = _authid(src) or "src"
                    tr = tcache.get(key)
                    if tr is None:
                        tr = QgsCoordinateTransform(src, wgs84, QgsProject.instance())
                        tcache[key] = tr
                    pt = tr.transform(QgsPointXY(x, y))
                    return pt.x(), pt.y()

                items = layer.items()
                records: list[dict[str, Any]] = []
                for item_id, item in list(items.items())[: max(1, int(limit))]:
                    rec: dict[str, Any] = {"id": int(item_id)}
                    try:
                        rec["type"] = item.itemName()
                    except Exception:
                        rec["type"] = type(item).__name__
                    # label: KadasSymbolItem.name() / KadasTextItem.text()
                    for attr in ("name", "text"):
                        getter = getattr(item, attr, None)
                        if callable(getter):
                            try:
                                val = getter()
                            except Exception:
                                val = None
                            if val:
                                rec["label"] = str(val)
                                break
                    # per-item position -> WGS84 (works for every item type)
                    try:
                        pos = item.position()
                        src = item.crs()
                        lon, lat = _to_wgs84(pos.x(), pos.y(), src)
                        rec["lon"] = round(lon, 7)
                        rec["lat"] = round(lat, 7)
                        rec["native"] = {
                            "x": pos.x(),
                            "y": pos.y(),
                            "crs": _authid(src),
                        }
                    except Exception:
                        pass
                    # geometry WKT (native CRS) for shapes
                    geom_getter = getattr(item, "geometry", None)
                    if callable(geom_getter):
                        try:
                            geom = geom_getter()
                            if geom is not None:
                                rec["geometry_wkt"] = geom.asWkt(2)[:500]
                        except Exception:
                            pass
                    records.append(rec)
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "layer": layer_name,
                "item_count": len(items),
                "returned": len(records),
                "items": records,
            }

        return _on_gui(_run)

    return [
        add_map_marker,
        add_text_annotation,
        add_map_circle,
        add_map_rectangle,
        add_map_polygon,
        clear_annotations,
        list_kadas_item_layers,
        get_kadas_layer_items,
    ]


__all__ = ["kadas_tools", "ANNOTATION_LAYER_NAME"]
