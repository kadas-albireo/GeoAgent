"""KADAS-native map-annotation tools (markers, shapes, text).

Vanilla QGIS has no concept of KADAS' interactive annotations. KADAS builds
these on top of QGIS' stock :class:`QgsAnnotationLayer` using its own item
subclasses in ``kadas.kadasgui`` (``KadasPinAnnotationItem``,
``KadasCircleAnnotationItem``, ``KadasRectangleAnnotationItem``) plus QGIS'
stock ``QgsAnnotationPointTextItem`` / ``QgsAnnotationPolygonItem`` for text and
polygons. The shared QGIS tool surface (:mod:`geoagent.tools.qgis`) therefore
can't place a marker or draw an annotation; on KADAS the agent would otherwise
have to hand-write KADAS Python through ``run_pyqgis_script`` and hope it knows
the API.

.. note::
   The old ``KadasItemLayer`` / ``Kadas*Item`` plugin-layer API is **deprecated**
   and is deliberately *not* used here. Annotations now live on a stock
   :class:`QgsAnnotationLayer`; the layer itself has no KADAS subclass, and
   KADAS-specific behaviour is provided by free-standing helpers
   (``KadasAnnotationLayerHelpers``) and the item subclasses above.

These tools expose that KADAS-native surface directly so the agent can *use
KADAS' own annotations* rather than reverse-engineer them:

    * ``add_map_marker`` / ``add_text_annotation`` — point markers & labels
    * ``add_map_circle`` / ``add_map_rectangle`` / ``add_map_polygon`` — shapes
    * ``clear_annotations`` — remove the agent's annotation layer (destructive)
    * ``list_kadas_annotation_layers`` / ``get_kadas_layer_items`` — read annotations

All the agent's own items are collected on a single reusable
:class:`QgsAnnotationLayer` named ``GeoAgent Annotations`` in EPSG:3857 (a metric
CRS, so circle radii are metres). Inputs are WGS84 lon/lat (the convention used
in user-facing prompts) and transformed to the layer CRS.

The module is import-safe outside KADAS/QGIS: ``kadas`` and ``qgis`` are
imported lazily inside the GUI tool bodies, never at module load, so the module
(and its unit tests) import cleanly in plain CI. Item construction is written
defensively because it can only be exercised against a live KADAS runtime;
failures return a structured error instead of raising.
"""

from __future__ import annotations

from typing import Any, Optional

from geoagent.core.decorators import geo_tool
from geoagent.tools._qt_marshal import run_on_qt_gui_thread

# The single annotation layer the agent owns. Reused across calls and the layer
# that ``clear_annotations`` removes. EPSG:3857 keeps radii/sizes in metres.
ANNOTATION_LAYER_NAME = "GeoAgent Annotations"
_LAYER_CRS = "EPSG:3857"

# Shape defaults. Translucent by design: an opaque fill hides the basemap the
# annotation is meant to point at.
_DEFAULT_FILL = "#3388ff"
_DEFAULT_OUTLINE = "#1f5fbf"
_DEFAULT_OPACITY = 0.35
_DEFAULT_OUTLINE_WIDTH = 0.6


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
        from qgis.core import (  # type: ignore[import-not-found]
            QgsCoordinateReferenceSystem,
        )

        return QgsCoordinateReferenceSystem(authid)

    def _authid(crs: Any) -> Optional[str]:
        """Return a CRS auth id (e.g. ``EPSG:3857``) or ``None``."""
        try:
            return crs.authid() or None
        except Exception:
            return None

    def _annotation_layer_cls() -> Any:
        from qgis.core import QgsAnnotationLayer  # type: ignore[import-not-found]

        return QgsAnnotationLayer

    def _get_or_create_layer() -> Any:
        """Return the reusable ``GeoAgent Annotations`` :class:`QgsAnnotationLayer`.

        Prefers ``KadasAnnotationLayerHelpers.createLayer`` so the layer carries
        the KADAS parametric-annotation metadata (and saves/loads correctly),
        falling back to a bare ``QgsAnnotationLayer`` where the helper is
        unavailable (plain QGIS / tests).
        """
        annotation_cls = _annotation_layer_cls()
        proj = _project()
        for layer in proj.mapLayers().values():
            if (
                isinstance(layer, annotation_cls)
                and layer.name() == ANNOTATION_LAYER_NAME
            ):
                return layer

        layer = None
        try:
            from kadas.kadasgui import (  # type: ignore[import-not-found]
                KadasAnnotationLayerHelpers,
            )

            layer = KadasAnnotationLayerHelpers.createLayer(
                ANNOTATION_LAYER_NAME, _crs(_LAYER_CRS)
            )
        except Exception:
            layer = None
        if layer is None:
            options = annotation_cls.LayerOptions(proj.transformContext())
            layer = annotation_cls(ANNOTATION_LAYER_NAME, options)
            layer.setCrs(_crs(_LAYER_CRS))
        proj.addMapLayer(layer)
        return layer

    def _to_layer_xy(lon: float, lat: float) -> tuple[float, float]:
        """Transform a WGS84 lon/lat to the annotation layer CRS (EPSG:3857)."""
        from qgis.core import (  # type: ignore[import-not-found]
            QgsCoordinateTransform,
            QgsPointXY,
            QgsProject,
        )

        transform = QgsCoordinateTransform(
            _crs("EPSG:4326"), _crs(_LAYER_CRS), QgsProject.instance()
        )
        pt = transform.transform(QgsPointXY(float(lon), float(lat)))
        return pt.x(), pt.y()

    def _polygon_geometry(ring_xy: list[tuple[float, float]]) -> Any:
        """Build a QgsPolygon abstract geometry from a planar (layer-CRS) ring."""
        from qgis.core import (  # type: ignore[import-not-found]
            QgsLineString,
            QgsPoint,
            QgsPolygon,
        )

        line = QgsLineString([QgsPoint(x, y) for x, y in ring_xy])
        polygon = QgsPolygon()
        polygon.setExteriorRing(line)
        return polygon

    # Every Kadas*AnnotationItem subclasses a stock QGIS annotation item
    # (Circle/Rectangle -> QgsAnnotationPolygonItem, Pin/GpxWaypoint ->
    # QgsAnnotationMarkerItem, GpxRoute -> QgsAnnotationLineItem), so styling is
    # plain QGIS setSymbol()/setFormat() rather than any KADAS-private API.
    def _fill_symbol(
        fill_color: str, outline_color: str, outline_width: float, opacity: float
    ) -> Any:
        from qgis.core import QgsFillSymbol  # type: ignore[import-not-found]

        symbol = QgsFillSymbol.createSimple(
            {
                "color": str(fill_color),
                "outline_color": str(outline_color),
                "outline_width": str(float(outline_width)),
            }
        )
        symbol.setOpacity(max(0.0, min(1.0, float(opacity))))
        return symbol

    def _style_polygon_item(
        item: Any,
        fill_color: str,
        outline_color: str,
        outline_width: float,
        opacity: float,
    ) -> None:
        item.setSymbol(_fill_symbol(fill_color, outline_color, outline_width, opacity))

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
                    KadasPinAnnotationItem,
                )
                from qgis.core import QgsPoint  # type: ignore[import-not-found]

                layer = _get_or_create_layer()
                x, y = _to_layer_xy(lon, lat)
                item = KadasPinAnnotationItem(QgsPoint(x, y))
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
    def add_text_annotation(
        lon: float,
        lat: float,
        text: str,
        color: str = "#000000",
        size: float = 10.0,
        bold: bool = False,
        italic: bool = False,
        font_family: Optional[str] = None,
    ) -> dict[str, Any]:
        """Place a styled text label on the KADAS canvas at a WGS84 coordinate.

        Args:
            lon: Longitude (WGS84).
            lat: Latitude (WGS84).
            text: The label text to display.
            color: Text colour as ``"#rrggbb"`` or a colour name (e.g. ``"red"``).
            size: Text size in points.
            bold: Render the label bold.
            italic: Render the label italic.
            font_family: Optional font family name; the QGIS default when unset.

        Returns:
            ``{"success", "lon", "lat", "text"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsAnnotationPointTextItem,
                    QgsPointXY,
                    QgsTextFormat,
                )
                from qgis.PyQt.QtGui import (  # type: ignore[import-not-found]
                    QColor,
                )

                layer = _get_or_create_layer()
                x, y = _to_layer_xy(lon, lat)
                item = QgsAnnotationPointTextItem(str(text), QgsPointXY(x, y))

                # QgsAnnotationPointTextItem is a stock QGIS item, so its text
                # style is a plain QgsTextFormat -- no KADAS-private API needed.
                text_format = QgsTextFormat()
                text_format.setColor(QColor(str(color)))
                text_format.setSize(float(size))
                if font_family:
                    text_format.setFamily(str(font_family))
                text_format.setForcedBold(bool(bold))
                text_format.setForcedItalic(bool(italic))
                item.setFormat(text_format)

                layer.addItem(item)
                _refresh()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "lon": lon, "lat": lat, "text": text}

        return _on_gui(_run)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def add_map_circle(
        lon: float,
        lat: float,
        radius_m: float,
        fill_color: str = _DEFAULT_FILL,
        outline_color: str = _DEFAULT_OUTLINE,
        opacity: float = _DEFAULT_OPACITY,
        outline_width: float = _DEFAULT_OUTLINE_WIDTH,
    ) -> dict[str, Any]:
        """Draw a circle of a given radius (metres) centred on a WGS84 point.

        Uses KADAS' native parametric ``KadasCircleAnnotationItem``. The radius is
        applied in the EPSG:3857 layer CRS, so (as with KADAS' own circle tool)
        it is web-Mercator metres — accurate near the centre latitude.

        Args:
            lon: Centre longitude (WGS84).
            lat: Centre latitude (WGS84).
            radius_m: Circle radius in metres.
            fill_color: Fill colour as ``"#rrggbb"`` or a colour name.
            outline_color: Outline colour as ``"#rrggbb"`` or a colour name.
            opacity: Fill opacity, 0.0 (invisible) to 1.0 (opaque).
            outline_width: Outline width in millimetres.

        Returns:
            ``{"success", "lon", "lat", "radius_m"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import (  # type: ignore[import-not-found]
                    KadasCircleAnnotationItem,
                )
                from qgis.core import QgsPointXY  # type: ignore[import-not-found]

                cx, cy = _to_layer_xy(lon, lat)
                center = QgsPointXY(cx, cy)
                ring_point = QgsPointXY(cx + float(radius_m), cy)

                layer = _get_or_create_layer()
                item = KadasCircleAnnotationItem(center, ring_point)
                _style_polygon_item(
                    item, fill_color, outline_color, outline_width, opacity
                )
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

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def add_map_rectangle(
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        fill_color: str = _DEFAULT_FILL,
        outline_color: str = _DEFAULT_OUTLINE,
        opacity: float = _DEFAULT_OPACITY,
        outline_width: float = _DEFAULT_OUTLINE_WIDTH,
    ) -> dict[str, Any]:
        """Draw a rectangle annotation over a WGS84 bounding box.

        Args:
            min_lon: West longitude (WGS84).
            min_lat: South latitude (WGS84).
            max_lon: East longitude (WGS84).
            max_lat: North latitude (WGS84).
            fill_color: Fill colour as ``"#rrggbb"`` or a colour name.
            outline_color: Outline colour as ``"#rrggbb"`` or a colour name.
            opacity: Fill opacity, 0.0 (invisible) to 1.0 (opaque).
            outline_width: Outline width in millimetres.

        Returns:
            ``{"success", "bbox"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasgui import (  # type: ignore[import-not-found]
                    KadasRectangleAnnotationItem,
                )
                from qgis.core import QgsPointXY  # type: ignore[import-not-found]
                from qgis.PyQt.QtCore import QSizeF  # type: ignore[import-not-found]

                minx, miny = _to_layer_xy(min_lon, min_lat)
                maxx, maxy = _to_layer_xy(max_lon, max_lat)
                center = QgsPointXY((minx + maxx) / 2.0, (miny + maxy) / 2.0)
                size = QSizeF(abs(maxx - minx), abs(maxy - miny))

                layer = _get_or_create_layer()
                item = KadasRectangleAnnotationItem(center, size, 0.0)
                _style_polygon_item(
                    item, fill_color, outline_color, outline_width, opacity
                )
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
        coordinates: list[list[float]],
        label: Optional[str] = None,
        fill_color: str = _DEFAULT_FILL,
        outline_color: str = _DEFAULT_OUTLINE,
        opacity: float = _DEFAULT_OPACITY,
        outline_width: float = _DEFAULT_OUTLINE_WIDTH,
    ) -> dict[str, Any]:
        """Draw a polygon annotation from a list of WGS84 ``[lon, lat]`` points.

        Uses QGIS' stock ``QgsAnnotationPolygonItem`` (KADAS has no polygon
        subclass — only a controller for interactive editing).

        Args:
            coordinates: Ordered ``[[lon, lat], ...]`` vertices (WGS84). The ring
                is closed automatically.
            label: Optional text label placed at the polygon centroid.
            fill_color: Fill colour as ``"#rrggbb"`` or a colour name.
            outline_color: Outline colour as ``"#rrggbb"`` or a colour name.
            opacity: Fill opacity, 0.0 (invisible) to 1.0 (opaque).
            outline_width: Outline width in millimetres.

        Returns:
            ``{"success", "vertices", "label"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsAnnotationPointTextItem,
                    QgsAnnotationPolygonItem,
                    QgsPointXY,
                )

                lonlat = [
                    (float(p[0]), float(p[1])) for p in coordinates if len(p) >= 2
                ]
                if len(lonlat) < 3:
                    return {
                        "success": False,
                        "error": "A polygon needs at least 3 vertices.",
                    }
                pts = [_to_layer_xy(lon, lat) for lon, lat in lonlat]
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                geom = _polygon_geometry(pts)

                layer = _get_or_create_layer()
                item = QgsAnnotationPolygonItem(geom)
                _style_polygon_item(
                    item, fill_color, outline_color, outline_width, opacity
                )
                layer.addItem(item)
                if label:
                    cx = sum(x for x, _ in pts[:-1]) / (len(pts) - 1)
                    cy = sum(y for _, y in pts[:-1]) / (len(pts) - 1)
                    text = QgsAnnotationPointTextItem(str(label), QgsPointXY(cx, cy))
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
                annotation_cls = _annotation_layer_cls()
                proj = _project()
                removed = 0
                for layer in list(proj.mapLayers().values()):
                    if (
                        isinstance(layer, annotation_cls)
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
    def list_kadas_annotation_layers() -> dict[str, Any]:
        """List annotation layers (Pins, routes, redlining, agent annotations).

        These :class:`QgsAnnotationLayer` layers hold drawable KADAS annotation
        items, not QGIS vector features, so the generic ``list_project_layers``
        only sees their extent. Use this to discover them, then
        ``get_kadas_layer_items`` to read the individual items and coordinates.

        Returns:
            ``{"success", "count", "layers": [{"name", "item_count", "crs"}]}``.
        """

        def _run() -> dict[str, Any]:
            try:
                annotation_cls = _annotation_layer_cls()
                proj = _project()
                out: list[dict[str, Any]] = []
                for layer in proj.mapLayers().values():
                    if not isinstance(layer, annotation_cls):
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

    def _item_layer_xy(item: Any) -> Optional[tuple[float, float]]:
        """Return an item's representative point in the layer CRS, or ``None``.

        Covers every annotation item type: ``center()`` (circle/rectangle),
        ``point()`` (point-text), and ``geometry()`` which returns a point for
        marker/pin items and a polygon (→ centroid) for shapes.
        """
        getter = getattr(item, "center", None)
        if callable(getter):
            try:
                pt: Any = getter()
                return pt.x(), pt.y()
            except Exception:
                pass
        getter = getattr(item, "point", None)
        if callable(getter):
            try:
                pt = getter()
                return pt.x(), pt.y()
            except Exception:
                pass
        getter = getattr(item, "geometry", None)
        if callable(getter):
            try:
                geom: Any = getter()
                if hasattr(geom, "x") and hasattr(geom, "y"):
                    return geom.x(), geom.y()
                centroid: Any = geom.centroid()
                return centroid.x(), centroid.y()
            except Exception:
                pass
        return None

    # -- KADAS core/analysis wrappers (SIP-binding-backed) -------------------
    # These expose powerful KADAS C++ APIs that were previously reachable only
    # by hand-written run_pyqgis_script. They live in ``kadas.kadascore`` /
    # ``kadas.kadasanalysis`` (see /home/aloha/OPENGIS/kadas-albireo2 SIP
    # bindings: kadascoordinateformat, kadaslatlontoutm, kadascoordinateutils,
    # kadaslineofsight). Import is lazy so the module stays CI-safe.

    _COORD_FORMATS = (
        "Default",
        "DegMinSec",
        "DegMin",
        "DecDeg",
        "UTM",
        "MGRS",
    )

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def convert_coordinates(
        lon: float,
        lat: float,
        target_format: str = "MGRS",
        target_epsg: str = "EPSG:4326",
    ) -> dict[str, Any]:
        """Convert a WGS84 lon/lat into KADAS coordinate strings (MGRS/UTM/DMS…).

        Uses KADAS' own ``KadasCoordinateFormat`` (the exact formatter the KADAS
        coordinate display uses) plus ``KadasLatLonToUTM`` for structured
        UTM/MGRS parts, so results match what KADAS shows in its status bar.

        Args:
            lon: Longitude (WGS84).
            lat: Latitude (WGS84).
            target_format: One of ``Default``, ``DegMinSec``, ``DegMin``,
                ``DecDeg``, ``UTM``, ``MGRS`` (case-insensitive).
            target_epsg: Display CRS for the ``Default``/``DecDeg`` formats
                (e.g. ``EPSG:2056`` for Swiss LV95). Ignored for UTM/MGRS.

        Returns:
            ``{"success", "requested", "formatted", "all_formats", "utm",
            "mgrs"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadascore import (  # type: ignore[import-not-found]
                    KadasCoordinateFormat,
                    KadasLatLonToUTM,
                )
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsCoordinateReferenceSystem,
                    QgsPointXY,
                )

                wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                point = QgsPointXY(float(lon), float(lat))

                by_name = {
                    name.lower(): getattr(KadasCoordinateFormat.Format, name)
                    for name in _COORD_FORMATS
                }
                # tolerant aliases
                by_name.setdefault("dms", by_name["degminsec"])
                by_name.setdefault("dm", by_name["degmin"])
                by_name.setdefault("dd", by_name["decdeg"])

                requested = str(target_format).strip().lower()
                if requested not in by_name:
                    return {
                        "success": False,
                        "error": (
                            f"Unknown format {target_format!r}. Use one of: "
                            + ", ".join(_COORD_FORMATS)
                        ),
                    }

                def _fmt(fmt: Any, epsg: str) -> str:
                    return KadasCoordinateFormat.getDisplayString(
                        point, wgs84, fmt, epsg, True
                    )

                formatted = _fmt(by_name[requested], target_epsg)
                all_formats = {
                    name: _fmt(getattr(KadasCoordinateFormat.Format, name), target_epsg)
                    for name in _COORD_FORMATS
                }

                utm = KadasLatLonToUTM.LL2UTM(point)
                mgrs = KadasLatLonToUTM.UTM2MGRS(utm)
                utm_out = {
                    "easting": utm.easting,
                    "northing": utm.northing,
                    "zone_number": utm.zoneNumber,
                    "zone_letter": utm.zoneLetter,
                }
                mgrs_out = {
                    "easting": mgrs.easting,
                    "northing": mgrs.northing,
                    "zone_number": mgrs.zoneNumber,
                    "zone_letter": mgrs.zoneLetter,
                    "square_id": mgrs.letter100kID,
                }
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "requested": target_format,
                "formatted": formatted,
                "all_formats": all_formats,
                "utm": utm_out,
                "mgrs": mgrs_out,
            }

        return _on_gui(_run)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def get_elevation_at(lon: float, lat: float) -> dict[str, Any]:
        """Return the terrain elevation (metres) at a WGS84 point.

        Wraps KADAS' native ``KadasCoordinateUtils.getHeightAtPos``, which reads
        the elevation from KADAS' configured terrain/DEM service — the same value
        the KADAS coordinate display and height-profile tools use.

        Args:
            lon: Longitude (WGS84).
            lat: Latitude (WGS84).

        Returns:
            ``{"success", "lon", "lat", "elevation_m"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadascore import (  # type: ignore[import-not-found]
                    KadasCoordinateUtils,
                )
                from qgis.core import (  # type: ignore[import-not-found]
                    Qgis,
                    QgsCoordinateReferenceSystem,
                    QgsPointXY,
                )

                wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                point = QgsPointXY(float(lon), float(lat))
                height = KadasCoordinateUtils.getHeightAtPos(
                    point, wgs84, Qgis.DistanceUnit.Meters
                )
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "lon": lon,
                "lat": lat,
                "elevation_m": round(float(height), 2),
            }

        return _on_gui(_run)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def check_line_of_sight(
        observer_lon: float,
        observer_lat: float,
        target_lon: float,
        target_lat: float,
        observer_height_m: float = 2.0,
        target_height_m: float = 0.0,
        terrain_samples: int = 100,
    ) -> dict[str, Any]:
        """Test whether a target is visible from an observer over the terrain.

        Wraps KADAS' native ``KadasLineOfSight.computeTargetVisibility`` — the
        engine behind the KADAS line-of-sight map tool. Heights are metres above
        ground (relative to the terrain surface at each point).

        Args:
            observer_lon: Observer longitude (WGS84).
            observer_lat: Observer latitude (WGS84).
            target_lon: Target longitude (WGS84).
            target_lat: Target latitude (WGS84).
            observer_height_m: Observer eye height above ground (metres).
            target_height_m: Target height above ground (metres).
            terrain_samples: Number of terrain samples along the sight line.

        Returns:
            ``{"success", "visible", ...}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasanalysis import (  # type: ignore[import-not-found]
                    KadasLineOfSight,
                )
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsCoordinateReferenceSystem,
                    QgsPoint,
                )

                wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                # z carries the height; observer/targetPosAbsolute=False means the
                # height is interpreted as relative to the terrain surface.
                observer = QgsPoint(
                    float(observer_lon), float(observer_lat), float(observer_height_m)
                )
                target = QgsPoint(
                    float(target_lon), float(target_lat), float(target_height_m)
                )
                visible = KadasLineOfSight.computeTargetVisibility(
                    observer, target, wgs84, int(terrain_samples), False, False
                )
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "visible": bool(visible),
                "observer": [observer_lon, observer_lat, observer_height_m],
                "target": [target_lon, target_lat, target_height_m],
            }

        return _on_gui(_run)

    @geo_tool(category="kadas", available_in=("full", "fast"))
    def get_kadas_layer_items(layer_name: str, limit: int = 200) -> dict[str, Any]:
        """Read the individual items in an annotation layer, with WGS84 coords.

        Resolves the limitation that a :class:`QgsAnnotationLayer` (e.g. the Pins
        layer) only exposes a bounding box to generic tools: this enumerates each
        item (markers, shapes, text) with its type, label, and **per-item
        coordinates** transformed to WGS84 lon/lat, plus the native layer-CRS
        coordinate and (for shapes) the geometry WKT.

        Args:
            layer_name: Name of the annotation layer (e.g. "Pins").
            limit: Maximum number of items to return.

        Returns:
            ``{"success", "layer", "item_count", "returned",
            "items": [{"id", "type", "label?", "lon", "lat", "native", ...}]}``.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsCoordinateReferenceSystem,
                    QgsCoordinateTransform,
                    QgsPointXY,
                    QgsProject,
                )

                annotation_cls = _annotation_layer_cls()
                proj = _project()
                layer = None
                for lyr in proj.mapLayers().values():
                    if isinstance(lyr, annotation_cls) and lyr.name() == layer_name:
                        layer = lyr
                        break
                if layer is None:
                    return {
                        "success": False,
                        "error": f"No annotation layer named {layer_name!r}.",
                    }

                wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                src = layer.crs()
                transform = QgsCoordinateTransform(src, wgs84, QgsProject.instance())

                items = layer.items()
                records: list[dict[str, Any]] = []
                for item_id, item in list(items.items())[: max(1, int(limit))]:
                    rec: dict[str, Any] = {"id": str(item_id)}
                    try:
                        rec["type"] = item.type()
                    except Exception:
                        rec["type"] = type(item).__name__
                    # label: KadasPinAnnotationItem.name() / point-text .text()
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
                    xy = _item_layer_xy(item)
                    if xy is not None:
                        try:
                            pt = transform.transform(QgsPointXY(xy[0], xy[1]))
                            rec["lon"] = round(pt.x(), 7)
                            rec["lat"] = round(pt.y(), 7)
                            rec["native"] = {
                                "x": xy[0],
                                "y": xy[1],
                                "crs": _authid(src),
                            }
                        except Exception:
                            pass
                    # geometry WKT (native CRS) for shapes
                    geom_getter = getattr(item, "geometry", None)
                    if callable(geom_getter):
                        try:
                            geom: Any = geom_getter()
                            if geom is not None and hasattr(geom, "asWkt"):
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
        list_kadas_annotation_layers,
        get_kadas_layer_items,
        convert_coordinates,
        get_elevation_at,
        check_line_of_sight,
    ]


__all__ = ["kadas_tools", "ANNOTATION_LAYER_NAME"]
