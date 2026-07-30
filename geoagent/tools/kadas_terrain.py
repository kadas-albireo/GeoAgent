"""KADAS terrain-analysis and measurement tools.

KADAS ships a DTM-backed analysis suite (hillshade, slope, viewshed,
line-of-sight) in ``kadas.kadasanalysis``, plus interactive measure map tools.
Both were previously unreachable by the agent: the analysis filters had no tool
binding at all, and the measure tools are click-driven so the agent could never
drive them.

Two facts make this module possible, both verified against the KADAS sources:

* **The heightmap is a project entry, not a tool argument.** Every KADAS terrain
  tool resolves its raster with ``QgsProject.readEntry("Heightmap", "layer")``
  (see ``kadaslineofsight.cpp``, ``kadasmaptoolslope.cpp``,
  ``kadasheightprofiledialog.cpp``). So ``set_heightmap_layer`` is the
  prerequisite for everything else here, and it is the same switch as the
  layer-tree's "Use as heightmap" context-menu entry.
* **The measure tools are plain ``QgsDistanceArea``.** ``kadasmaptoolmeasure.cpp``
  computes lengths with ``measureLine``, bearings with ``bearing`` and areas with
  ``measurePolygon``. Reimplementing that non-interactively is exact, not an
  approximation, so the agent does not need the click-driven tool.

``KadasNineCellFilter.processRaster`` is a blocking, whole-raster pass, hence the
``long_running``/``requires_confirmation`` metadata on the raster producers.

Import-safe outside KADAS/QGIS: ``kadas`` and ``qgis`` are imported lazily inside
the tool bodies, never at module load.
"""

from __future__ import annotations

from typing import Any, Optional

from geoagent.core.decorators import geo_tool
from geoagent.tools._qt_marshal import run_on_qt_gui_thread

# The KADAS project entry every terrain tool reads to find its DTM.
_HEIGHTMAP_SCOPE = "Heightmap"
_HEIGHTMAP_KEY = "layer"

# KADAS' measure tool defaults to NATO mils for azimuth (6400 to a full turn).
_MIL_NATO_PER_DEGREE = 6400.0 / 360.0


def kadas_terrain_tools(iface: Any = None, project: Optional[Any] = None) -> list[Any]:
    """Build the KADAS terrain/measurement tool set bound to a live ``iface``."""
    if iface is None and project is None:
        return []

    def _on_gui(func: Any) -> Any:
        return run_on_qt_gui_thread(func)

    def _project() -> Any:
        if project is not None:
            return project
        from qgis.core import QgsProject  # type: ignore[import-not-found]

        return QgsProject.instance()

    def _find_layer(layer_name: str) -> Any:
        for layer in _project().mapLayers().values():
            if layer.name() == layer_name:
                return layer
        return None

    def _heightmap_layer() -> Any:
        """Resolve the project's heightmap the same way KADAS' C++ tools do."""
        layer_id, ok = _project().readEntry(_HEIGHTMAP_SCOPE, _HEIGHTMAP_KEY)
        if not ok or not layer_id:
            return None
        return _project().mapLayer(layer_id)

    def _distance_area() -> Any:
        """A QgsDistanceArea configured like KADAS' measure tool: ellipsoidal, metres."""
        from qgis.core import (  # type: ignore[import-not-found]
            Qgis,
            QgsCoordinateReferenceSystem,
            QgsDistanceArea,
        )

        da = QgsDistanceArea()
        da.setSourceCrs(
            QgsCoordinateReferenceSystem("EPSG:4326"), _project().transformContext()
        )
        da.setEllipsoid(_project().ellipsoid() or "WGS84")
        return da, Qgis

    @geo_tool(category="kadas_terrain", available_in=("full", "fast"))
    def set_heightmap_layer(layer_name: str) -> dict[str, Any]:
        """Set which raster layer KADAS uses as the heightmap (DTM).

        This is the prerequisite for every terrain tool: hillshade, slope,
        viewshed, line-of-sight and the height profile all read this one project
        entry. Equivalent to right-clicking a raster in the layer tree and
        choosing "Use as heightmap".

        Args:
            layer_name: Name of an already-loaded raster layer (e.g. "DTM CH 10m").

        Returns:
            ``{"success", "layer_name", "layer_id"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                layer = _find_layer(layer_name)
                if layer is None:
                    return {
                        "success": False,
                        "error": f"No layer named {layer_name!r} is loaded.",
                    }
                _project().writeEntry(_HEIGHTMAP_SCOPE, _HEIGHTMAP_KEY, layer.id())
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "layer_name": layer_name,
                "layer_id": layer.id(),
            }

        return _on_gui(_run)

    @geo_tool(category="kadas_terrain", available_in=("full", "fast"))
    def get_heightmap_layer() -> dict[str, Any]:
        """Report which layer is currently set as the KADAS heightmap (DTM).

        Returns:
            ``{"success", "layer_name", "layer_id"}``; ``layer_name`` is ``None``
            when no heightmap is configured.
        """

        def _run() -> dict[str, Any]:
            try:
                layer = _heightmap_layer()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            if layer is None:
                return {
                    "success": True,
                    "layer_name": None,
                    "layer_id": None,
                    "hint": "Load a DTM raster and call set_heightmap_layer first.",
                }
            return {"success": True, "layer_name": layer.name(), "layer_id": layer.id()}

        return _on_gui(_run)

    @geo_tool(
        category="kadas_terrain",
        requires_confirmation=True,
        long_running=True,
    )
    def compute_hillshade(
        output_path: str,
        light_azimuth: float = 300.0,
        light_angle: float = 40.0,
        z_factor: float = 1.0,
        add_to_map: bool = True,
    ) -> dict[str, Any]:
        """Render a hillshade raster from the project heightmap (KADAS' own filter).

        Uses ``KadasHillshadeFilter``, the same code path as KADAS' Hillshade map
        tool. Runs over the whole heightmap, which is slow on a large DTM.

        Args:
            output_path: Destination GeoTIFF path (``.tif``).
            light_azimuth: Illumination direction in degrees clockwise from north.
            light_angle: Illumination elevation above the horizon, in degrees.
            z_factor: Vertical exaggeration; ``-1`` lets KADAS compute it.
            add_to_map: Load the result as a raster layer when finished.

        Returns:
            ``{"success", "output_path", "layer_name"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasanalysis import (  # type: ignore[import-not-found]
                    KadasHillshadeFilter,
                )

                layer = _heightmap_layer()
                if layer is None:
                    return {
                        "success": False,
                        "error": (
                            "No heightmap is set. Load a DTM raster and call "
                            "set_heightmap_layer first."
                        ),
                    }
                filt = KadasHillshadeFilter(
                    layer,
                    str(output_path),
                    "GTiff",
                    float(light_azimuth),
                    float(light_angle),
                )
                filt.setZFactor(float(z_factor))
                err = ""
                code = filt.processRaster(None, err)
                if code != 0:
                    return {
                        "success": False,
                        "error": f"Hillshade failed (code {code}): {err}",
                    }
                layer_name = None
                if add_to_map:
                    from qgis.core import (  # type: ignore[import-not-found]
                        QgsRasterLayer,
                    )

                    layer_name = "Hillshade"
                    result = QgsRasterLayer(str(output_path), layer_name)
                    if not result.isValid():
                        return {
                            "success": False,
                            "error": f"Wrote {output_path} but it did not load.",
                        }
                    _project().addMapLayer(result)
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "output_path": str(output_path),
                "layer_name": layer_name,
            }

        return _on_gui(_run)

    @geo_tool(
        category="kadas_terrain",
        requires_confirmation=True,
        long_running=True,
    )
    def compute_slope(
        output_path: str, z_factor: float = 1.0, add_to_map: bool = True
    ) -> dict[str, Any]:
        """Compute a slope raster from the project heightmap (KADAS' own filter).

        Uses ``KadasSlopeFilter``, the same code path as KADAS' Slope map tool.
        Output values are slope in degrees.

        Args:
            output_path: Destination GeoTIFF path (``.tif``).
            z_factor: Vertical exaggeration; ``-1`` lets KADAS compute it.
            add_to_map: Load the result as a raster layer when finished.

        Returns:
            ``{"success", "output_path", "layer_name"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasanalysis import (  # type: ignore[import-not-found]
                    KadasSlopeFilter,
                )

                layer = _heightmap_layer()
                if layer is None:
                    return {
                        "success": False,
                        "error": (
                            "No heightmap is set. Load a DTM raster and call "
                            "set_heightmap_layer first."
                        ),
                    }
                filt = KadasSlopeFilter(layer, str(output_path), "GTiff")
                filt.setZFactor(float(z_factor))
                err = ""
                code = filt.processRaster(None, err)
                if code != 0:
                    return {
                        "success": False,
                        "error": f"Slope failed (code {code}): {err}",
                    }
                layer_name = None
                if add_to_map:
                    from qgis.core import (  # type: ignore[import-not-found]
                        QgsRasterLayer,
                    )

                    layer_name = "Slope"
                    result = QgsRasterLayer(str(output_path), layer_name)
                    if not result.isValid():
                        return {
                            "success": False,
                            "error": f"Wrote {output_path} but it did not load.",
                        }
                    _project().addMapLayer(result)
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "output_path": str(output_path),
                "layer_name": layer_name,
            }

        return _on_gui(_run)

    @geo_tool(
        category="kadas_terrain",
        requires_confirmation=True,
        long_running=True,
    )
    def compute_viewshed(
        output_path: str,
        lon: float,
        lat: float,
        radius_m: float,
        observer_height_m: float = 2.0,
        target_height_m: float = 0.0,
        add_to_map: bool = True,
    ) -> dict[str, Any]:
        """Compute a viewshed around an observer, using KADAS' own filter.

        Uses ``KadasViewshedFilter.computeViewshed`` — the same code path as
        KADAS' Viewshed map tool. Heights are relative to the terrain.

        Args:
            output_path: Destination GeoTIFF path (``.tif``).
            lon: Observer longitude (WGS84).
            lat: Observer latitude (WGS84).
            radius_m: Analysis radius in metres.
            observer_height_m: Observer height above ground, in metres.
            target_height_m: Target height above ground, in metres.
            add_to_map: Load the result as a raster layer when finished.

        Returns:
            ``{"success", "output_path", "layer_name"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from kadas.kadasanalysis import (  # type: ignore[import-not-found]
                    KadasViewshedFilter,
                )
                from qgis.core import (  # type: ignore[import-not-found]
                    Qgis,
                    QgsCoordinateReferenceSystem,
                    QgsPointXY,
                )

                layer = _heightmap_layer()
                if layer is None:
                    return {
                        "success": False,
                        "error": (
                            "No heightmap is set. Load a DTM raster and call "
                            "set_heightmap_layer first."
                        ),
                    }
                err = ""
                ok = KadasViewshedFilter.computeViewshed(
                    layer,
                    str(output_path),
                    "GTiff",
                    QgsPointXY(float(lon), float(lat)),
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                    float(observer_height_m),
                    float(target_height_m),
                    True,
                    True,
                    -90.0,
                    90.0,
                    float(radius_m),
                    Qgis.DistanceUnit.Meters,
                    None,
                    err,
                )
                if not ok:
                    return {"success": False, "error": f"Viewshed failed: {err}"}
                layer_name = None
                if add_to_map:
                    from qgis.core import (  # type: ignore[import-not-found]
                        QgsRasterLayer,
                    )

                    layer_name = "Viewshed"
                    result = QgsRasterLayer(str(output_path), layer_name)
                    if not result.isValid():
                        return {
                            "success": False,
                            "error": f"Wrote {output_path} but it did not load.",
                        }
                    _project().addMapLayer(result)
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "output_path": str(output_path),
                "layer_name": layer_name,
            }

        return _on_gui(_run)

    @geo_tool(category="kadas_terrain", available_in=("full", "fast"))
    def measure_distance_bearing(
        from_lon: float, from_lat: float, to_lon: float, to_lat: float
    ) -> dict[str, Any]:
        """Measure ellipsoidal distance and azimuth between two WGS84 points.

        Mirrors KADAS' interactive distance/azimuth measure tool, which uses
        ``QgsDistanceArea.measureLine`` and ``.bearing``. Azimuth is reported in
        degrees and in NATO mils (KADAS' default angle unit).

        Args:
            from_lon: Start longitude (WGS84).
            from_lat: Start latitude (WGS84).
            to_lon: End longitude (WGS84).
            to_lat: End latitude (WGS84).

        Returns:
            ``{"success", "distance_m", "azimuth_degrees", "azimuth_mil_nato"}``.
        """

        def _run() -> dict[str, Any]:
            try:
                import math

                from qgis.core import QgsPointXY  # type: ignore[import-not-found]

                da, _ = _distance_area()
                start = QgsPointXY(float(from_lon), float(from_lat))
                end = QgsPointXY(float(to_lon), float(to_lat))
                distance_m = da.measureLine(start, end)
                azimuth_deg = math.degrees(da.bearing(start, end)) % 360.0
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "distance_m": round(distance_m, 3),
                "azimuth_degrees": round(azimuth_deg, 3),
                "azimuth_mil_nato": round(azimuth_deg * _MIL_NATO_PER_DEGREE, 1),
            }

        return _on_gui(_run)

    @geo_tool(category="kadas_terrain", available_in=("full", "fast"))
    def measure_polygon_area(coordinates: list[list[float]]) -> dict[str, Any]:
        """Measure the ellipsoidal area and perimeter of a WGS84 polygon.

        Mirrors KADAS' interactive area measure tool
        (``QgsDistanceArea.measurePolygon`` / ``.measureLine``).

        Args:
            coordinates: Ordered ``[[lon, lat], ...]`` vertices (WGS84). The ring
                is closed automatically.

        Returns:
            ``{"success", "area_m2", "area_km2", "perimeter_m", "vertices"}``.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.core import QgsPointXY  # type: ignore[import-not-found]

                ring = [
                    QgsPointXY(float(p[0]), float(p[1]))
                    for p in coordinates
                    if len(p) >= 2
                ]
                if len(ring) < 3:
                    return {
                        "success": False,
                        "error": "A polygon needs at least 3 vertices.",
                    }
                da, _ = _distance_area()
                area_m2 = da.measurePolygon(ring)
                closed = ring + [ring[0]] if ring[0] != ring[-1] else ring
                perimeter_m = sum(
                    da.measureLine(closed[i], closed[i + 1])
                    for i in range(len(closed) - 1)
                )
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "area_m2": round(area_m2, 2),
                "area_km2": round(area_m2 / 1_000_000.0, 6),
                "perimeter_m": round(perimeter_m, 3),
                "vertices": len(ring),
            }

        return _on_gui(_run)

    return [
        set_heightmap_layer,
        get_heightmap_layer,
        compute_hillshade,
        compute_slope,
        compute_viewshed,
        measure_distance_bearing,
        measure_polygon_area,
    ]
