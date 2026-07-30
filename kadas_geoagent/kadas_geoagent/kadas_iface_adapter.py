"""Adapter that presents a ``QgisInterface``-style surface over KADAS.

GeoAgent's QGIS tools (``geoagent/tools/qgis.py``) and the shared chat dock
were written against the vanilla QGIS ``QgisInterface`` (``iface``). KADAS
Albireo 2 hands plugins a :class:`kadas.kadasgui.KadasPluginInterface`
instead. That class mirrors the *navigation* surface GeoAgent relies on --
``mapCanvas()``, ``mainWindow()``, ``messageBar()`` and ``addAction()`` -- but
it does **not** provide the layer-management helpers that ``QgisInterface``
adds on top of QGIS core:

    addVectorLayer / addRasterLayer / activeLayer / setActiveLayer /
    zoomToActiveLayer / showAttributeTable

This adapter implements that missing surface against ``QgsProject`` and the
map canvas (both shared, unchanged, between QGIS and KADAS) and delegates
everything else to the wrapped KADAS interface. The result is an object that
``geoagent.for_qgis(...)`` and ``ChatDockWidget(iface, ...)`` can consume
without any changes to the shared GeoAgent core.

The module is import-safe outside QGIS/KADAS: it never imports ``qgis`` at
module load time. QGIS classes are imported lazily inside method bodies so the
adapter (and its unit tests) can be imported in plain CI.
"""

from __future__ import annotations

from typing import Any, Optional

# Methods that genuinely live on KadasPluginInterface and should pass straight
# through to it. Anything not handled explicitly below is delegated via
# __getattr__, but listing the core ones documents the contract.
_PASSTHROUGH = frozenset(
    {
        "mapCanvas",
        "mainWindow",
        "messageBar",
        "addAction",
        "removeAction",
        "layerTreeView",
        "layerTreeCanvasBridge",
    }
)


class KadasIfaceAdapter:
    """Wrap a ``KadasPluginInterface`` to look like a QGIS ``iface``.

    Args:
        kadas_iface: The interface object KADAS passes to ``classFactory``.
            Typically already cast via
            ``KadasPluginInterface.cast(iface)``.
    """

    def __init__(self, kadas_iface: Any) -> None:
        self._kiface = kadas_iface

    # -- Underlying interface access -------------------------------------

    @property
    def kadas_iface(self) -> Any:
        """Return the wrapped KADAS interface (for KADAS-specific calls)."""
        return self._kiface

    def __getattr__(self, name: str) -> Any:
        """Delegate any unhandled attribute to the wrapped KADAS interface.

        This keeps the adapter transparent for the parts of the API that
        KADAS already provides (canvas, main window, message bar, actions,
        and KADAS-only extensions). ``__getattr__`` only runs for attributes
        not found normally, so the explicit shims below always win.
        """
        return getattr(self._kiface, name)

    # -- Project resolution ----------------------------------------------

    def project(self) -> Any:
        """Return the active project.

        ``QgisInterface.project()`` does not exist in every QGIS build and is
        absent from ``KadasPluginInterface``; GeoAgent already falls back to
        ``QgsProject.instance()``. We expose it explicitly for parity so the
        agent's preferred ``iface.project()`` path resolves on KADAS too.
        """
        from qgis.core import QgsProject

        return QgsProject.instance()

    # -- Active layer ----------------------------------------------------

    def activeLayer(self) -> Any:
        """Return the canvas' current layer.

        KADAS does not expose ``activeLayer()`` on its plugin interface. The
        map canvas' "current layer" is the closest faithful equivalent and is
        what the layer tree selection drives.
        """
        canvas = self._kiface.mapCanvas()
        current = getattr(canvas, "currentLayer", None)
        return current() if callable(current) else None

    def setActiveLayer(self, layer: Any) -> None:
        """Set the canvas' current layer (KADAS lacks ``setActiveLayer``)."""
        canvas = self._kiface.mapCanvas()
        setter = getattr(canvas, "setCurrentLayer", None)
        if callable(setter):
            setter(layer)

    # -- Layer loading ---------------------------------------------------

    def addVectorLayer(
        self, path: str, base_name: str, provider_key: str = "ogr"
    ) -> Any:
        """Create a vector layer, register it, and return it (or ``None``).

        Mirrors ``QgisInterface.addVectorLayer``: invalid layers are not added
        and yield ``None`` so GeoAgent reports a load failure.
        """
        from qgis.core import QgsProject, QgsVectorLayer

        layer = QgsVectorLayer(path, base_name, provider_key)
        if not layer.isValid():
            return None
        QgsProject.instance().addMapLayer(layer)
        return layer

    def addRasterLayer(
        self, uri: str, base_name: str, provider_key: Optional[str] = None
    ) -> Any:
        """Create a raster layer, register it, and return it (or ``None``).

        Supports both the file form ``addRasterLayer(path, name)`` and the
        provider form ``addRasterLayer(uri, name, "wms")`` GeoAgent uses for
        XYZ/WMS sources.

        For provider-backed sources (WMS/WMTS), prefer KADAS's native
        ``addRasterLayerQuiet`` so the layer is created through the exact code
        path a manual swisstopo geocatalog click runs (``kApp->addRasterLayer``
        in KADAS). This keeps agent-loaded catalog layers byte-identical to
        manually loaded ones. Falls back to the plain ``QgsRasterLayer`` path
        for file sources and when the native method is unavailable (e.g. tests).
        """
        from qgis.core import QgsProject, QgsRasterLayer

        if provider_key and hasattr(self._kiface, "addRasterLayerQuiet"):
            try:
                layer = self._kiface.addRasterLayerQuiet(
                    uri, base_name, provider_key
                )
            except Exception:
                layer = None
            if layer is not None and (
                not hasattr(layer, "isValid") or layer.isValid()
            ):
                return layer

        if provider_key:
            layer = QgsRasterLayer(uri, base_name, provider_key)
        else:
            layer = QgsRasterLayer(uri, base_name)
        if not layer.isValid():
            return None
        QgsProject.instance().addMapLayer(layer)
        return layer

    # -- Navigation ------------------------------------------------------

    def zoomToActiveLayer(self) -> None:
        """Zoom the canvas to the extent of the current layer.

        KADAS lacks ``zoomToActiveLayer``; GeoAgent also computes extents
        directly, so this is the canvas-refresh fallback path.
        """
        layer = self.activeLayer()
        if layer is None:
            return
        extent = getattr(layer, "extent", None)
        if not callable(extent):
            return
        canvas = self._kiface.mapCanvas()
        canvas.setExtent(extent())
        if hasattr(canvas, "refresh"):
            canvas.refresh()

    # Note: showAttributeTable is intentionally NOT defined. GeoAgent guards
    # the call with ``hasattr(iface, "showAttributeTable")``. If the wrapped
    # KADAS interface ever gains it, __getattr__ will surface it; otherwise
    # the agent skips the attribute-table step gracefully.
