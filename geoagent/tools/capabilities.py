"""Native KADAS/QGIS capability discovery, GPKG round-trip, and log querying.

This module gives the agent *self-awareness* of the running KADAS/QGIS instance.
The guiding principle is **discovery over reimplementation**: rather than wrap
every KADAS/QGIS plugin in bespoke tool code (which rots on every upgrade and
couples the agent to fragile GUI internals), the agent *discovers* what plugins
and Processing algorithms exist at runtime and either drives them (Processing,
GPKG) or explains to the user how to use them (GUI-only plugins like print).

* ``list_qgis_capabilities`` — high-level overview: active plugins, Processing
  providers + algorithm counts, and whether the KADAS Python modules import.
* ``list_processing_algorithms`` / ``describe_processing_algorithm`` — enumerate
  every Processing algorithm (including ones contributed by *imported* plugins)
  with its id, and describe a single algorithm's parameters, so the LLM can
  build a valid ``parameters`` dict and run it via ``run_processing_algorithm``.
* ``list_plugins`` / ``describe_plugin`` — read each plugin's ``metadata.txt``
  and introspect the loaded instance's ``QAction``/``QMenu``/``QShortcut``
  attributes to surface its user-facing commands (label, menu, shortcut). This
  is how the agent tells a user *how to use* a GUI plugin (print, ephem, …)
  rather than executing it headlessly.
* ``list_kadas_actions`` / ``trigger_kadas_action`` — the native command bridge.
  Every KADAS command (File/Map ops, map tools, plugin actions) is a named
  ``QAction`` on the main window, reachable via
  ``KadasPluginInterface.findAction``; these two tools enumerate and trigger them
  generically, so the agent runs KADAS's *own* commands instead of hand-written
  wrappers. Triggering runs the command's GUI (dialogs open for the user to
  complete); use the dedicated headless tools when a path/parameter must be
  passed programmatically.
* ``export_gpkg`` / ``import_gpkg`` — a *genuine* KADAS-native GeoPackage
  round-trip that reuses the ``kadas_gpkg`` plugin's own worker classes
  (embedding the full QGIS project + resources into the ``.gpkg``), driven with
  a headless progress stub instead of the plugin's dialog.
* ``query_agent_logs`` — read back and filter GeoAgent's own JSONL execution /
  "Training AI" feedback logs (see :mod:`geoagent.core.telemetry`).

Everything is in-process: ``qgis`` and the KADAS plugin modules are imported
lazily inside the tool bodies so the module (and its unit tests) import cleanly
in plain CI.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from geoagent.core.decorators import geo_tool
from geoagent.tools._qt_marshal import run_on_qt_gui_thread


class _NoOpSignal:
    """Stand-in for a Qt signal whose ``connect`` we can safely ignore."""

    def connect(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _HeadlessProgress:
    """Minimal ``QProgressDialog``-compatible stub for headless GPKG export.

    ``KadasGpkgExportBase.write_layers`` drives a ``QProgressDialog`` (range,
    label, value, cancel signal). None of that is needed when the agent runs the
    export non-interactively, so this stub satisfies the interface as no-ops.
    """

    def __init__(self) -> None:
        self._value = 0
        self._maximum = 100
        self.canceled = _NoOpSignal()

    def wasCanceled(self) -> bool:
        return False

    def setRange(self, _lo: int, hi: int) -> None:
        self._maximum = hi

    def setMaximum(self, hi: int) -> None:
        self._maximum = hi

    def setAutoReset(self, *_args: Any) -> None:
        return None

    def setLabelText(self, *_args: Any) -> None:
        return None

    def setValue(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value

    def maximum(self) -> int:
        return self._maximum

    def show(self) -> None:
        return None

    def hide(self) -> None:
        return None


def _kadas_gpkg_classes() -> tuple[Any, Any]:
    """Return the (KadasGpkgExport, KadasGpkgImport) plugin classes, or (None, None).

    The ``kadas_gpkg`` plugin ships under KADAS' ``share/python/plugins`` and is
    importable in a running KADAS (QGIS puts that directory on ``sys.path`` and
    the plugin is loaded at startup). We reuse its worker classes directly rather
    than reimplement the full-project GeoPackage archive format.
    """
    try:
        import importlib

        export_mod = importlib.import_module("kadas_gpkg.kadas_gpkg_export")
        import_mod = importlib.import_module("kadas_gpkg.kadas_gpkg_import")
        return export_mod.KadasGpkgExport, import_mod.KadasGpkgImport
    except Exception:
        return None, None


def _strip_unselected_layers(doc: Any, keep_ids: set) -> None:
    """Remove ``maplayer`` / layer-tree entries whose id is not in ``keep_ids``.

    Mirrors the plugin's ``__removeUnselectedProjectLayers`` but keyed on an
    explicit keep-set, so a subset export embeds a project referencing only the
    exported layers. Operates on an lxml element tree in place.
    """

    def _strip_tree(group: Any) -> None:
        for lyr in list(group.iterfind("layer-tree-layer")):
            if lyr.attrib.get("id") not in keep_ids:
                group.remove(lyr)
        for sub in list(group.iterfind("layer-tree-group")):
            _strip_tree(sub)
            if not sub.findall("layer-tree-group") and not sub.findall(
                "layer-tree-layer"
            ):
                group.remove(sub)

    projectlayers = doc.find("projectlayers")
    if projectlayers is not None:
        for maplayer in list(projectlayers.iterfind("maplayer")):
            id_el = maplayer.find("id")
            if id_el is not None and id_el.text not in keep_ids:
                projectlayers.remove(maplayer)
    for group in doc.iterfind("layer-tree-group"):
        _strip_tree(group)


def _plugin_commands(instance: Any) -> list[dict[str, Any]]:
    """Discover a loaded plugin's user-facing commands via attribute introspection.

    KADAS/QGIS plugins keep references to the ``QAction`` / ``QMenu`` /
    ``QShortcut`` objects they register as instance attributes (they must, or Qt
    garbage-collects them). Walking ``vars(instance)`` therefore recovers the
    plugin's commands with their label, menu, and keyboard shortcut — the "how to
    use it" the agent needs to guide the user.
    """
    cmds: list[dict[str, Any]] = []
    try:
        from qgis.PyQt.QtWidgets import (  # type: ignore[import-not-found]
            QAction,
            QMenu,
            QShortcut,
        )
    except Exception:
        return cmds

    for attr, val in vars(instance).items():
        try:
            if isinstance(val, QAction):
                cmds.append(
                    {
                        "label": val.text(),
                        "tooltip": val.toolTip(),
                        "shortcut": val.shortcut().toString(),
                    }
                )
            elif isinstance(val, QMenu):
                for act in val.actions():
                    cmds.append(
                        {
                            "label": act.text(),
                            "menu": val.title() or attr,
                            "shortcut": act.shortcut().toString(),
                        }
                    )
            elif isinstance(val, QShortcut):
                cmds.append({"label": attr, "shortcut": val.key().toString()})
        except Exception:
            continue
    # Drop empty separators and de-duplicate on (label, shortcut).
    seen = set()
    out: list[dict[str, Any]] = []
    for c in cmds:
        if not c.get("label"):
            continue
        key = (c.get("label"), c.get("shortcut"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _action_text(text: str) -> str:
    """Strip Qt mnemonic ampersands from a QAction's display text."""
    if not text:
        return ""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def _ogr_driver_from_ext(path: str) -> str:
    """Map a file extension to an OGR vector driver name (empty if unknown)."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return {
        "kml": "KML",
        "kmz": "LIBKML",
        "geojson": "GeoJSON",
        "json": "GeoJSON",
        "shp": "ESRI Shapefile",
        "gpkg": "GPKG",
        "gml": "GML",
        "csv": "CSV",
        "gpx": "GPX",
        "tab": "MapInfo File",
        "sqlite": "SQLite",
    }.get(ext, "")


def capability_tools(iface: Any = None, project: Optional[Any] = None) -> list[Any]:
    """Build the capability/awareness tool set bound to a live ``iface``.

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

    @geo_tool(category="capabilities", available_in=("full", "fast"))
    def list_qgis_capabilities() -> dict[str, Any]:
        """Discover the tools KADAS/QGIS currently exposes at runtime.

        Inspects the live registries so the agent knows what is actually
        available before acting: the active QGIS/KADAS plugins, the loaded
        Processing providers and how many algorithms each offers, and whether
        the KADAS Python modules (``kadas.kadascore`` / ``kadasgui`` /
        ``kadasanalysis``) are importable (i.e. whether the KADAS-native
        annotation, coordinate and line-of-sight tools will work here).

        Returns:
            ``{"success", "active_plugins", "processing_providers":
            [{"id", "name", "algorithm_count"}], "algorithm_count",
            "kadas_modules": {name: bool}}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            out: dict[str, Any] = {"success": True}
            try:
                import qgis.utils  # type: ignore[import-not-found]

                out["active_plugins"] = sorted(
                    getattr(qgis.utils, "active_plugins", []) or []
                )
            except Exception as exc:
                out["active_plugins"] = []
                out["plugins_error"] = f"{type(exc).__name__}: {exc}"

            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsApplication,
                )

                registry = QgsApplication.processingRegistry()
                providers = []
                total = 0
                for prov in registry.providers():
                    try:
                        algs = list(prov.algorithms())
                    except Exception:
                        algs = []
                    total += len(algs)
                    providers.append(
                        {
                            "id": prov.id(),
                            "name": prov.name(),
                            "algorithm_count": len(algs),
                        }
                    )
                out["processing_providers"] = providers
                out["algorithm_count"] = total
            except Exception as exc:
                out["processing_error"] = f"{type(exc).__name__}: {exc}"

            modules = {}
            for name in ("kadas.kadascore", "kadas.kadasgui", "kadas.kadasanalysis"):
                try:
                    __import__(name)
                    modules[name] = True
                except Exception:
                    modules[name] = False
            out["kadas_modules"] = modules
            return out

        return _on_gui(_run)

    @geo_tool(category="capabilities", available_in=("full", "fast"))
    def list_processing_algorithms(
        filter_text: str = "", provider: str = ""
    ) -> dict[str, Any]:
        """List available QGIS/KADAS Processing algorithms (incl. imported plugins).

        Enumerates every algorithm in the live Processing registry so the agent
        can discover — at runtime — what an imported plugin actually contributes,
        not just how many algorithms it has. Pair with
        ``describe_processing_algorithm`` to get an algorithm's parameters, then
        run it with ``run_processing_algorithm``.

        Args:
            filter_text: Case-insensitive substring matched against each
                algorithm's id and display name. Empty returns everything.
            provider: Optional provider id filter (e.g. ``"native"``, ``"gdal"``,
                ``"qgis"``, or an imported plugin's provider id).

        Returns:
            ``{"success", "count", "algorithms": [{"id", "name", "group",
            "provider"}]}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsApplication,
                )

                needle = str(filter_text or "").lower()
                prov_filter = str(provider or "").lower()
                registry = QgsApplication.processingRegistry()
                algos: list[dict[str, Any]] = []
                for alg in registry.algorithms():
                    try:
                        alg_id = alg.id()
                        name = alg.displayName()
                        prov_id = alg.provider().id() if alg.provider() else ""
                    except Exception:
                        continue
                    if prov_filter and prov_filter != prov_id.lower():
                        continue
                    if (
                        needle
                        and needle not in alg_id.lower()
                        and needle not in name.lower()
                    ):
                        continue
                    algos.append(
                        {
                            "id": alg_id,
                            "name": name,
                            "group": alg.group() if hasattr(alg, "group") else "",
                            "provider": prov_id,
                        }
                    )
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            algos.sort(key=lambda a: a["id"])
            return {"success": True, "count": len(algos), "algorithms": algos}

        return _on_gui(_run)

    @geo_tool(category="capabilities", available_in=("full", "fast"))
    def describe_processing_algorithm(algorithm_id: str) -> dict[str, Any]:
        """Describe a Processing algorithm's parameters and outputs.

        Returns the parameter schema for a single algorithm (discovered via
        ``list_processing_algorithms``) so the LLM can assemble a valid
        ``parameters`` dict for ``run_processing_algorithm``.

        Args:
            algorithm_id: Fully-qualified algorithm id, e.g. ``"native:buffer"``.

        Returns:
            ``{"success", "id", "name", "group", "parameters": [{"name", "type",
            "description", "optional", "default"}], "outputs": [...]}`` or a
            structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsApplication,
                )

                registry = QgsApplication.processingRegistry()
                alg = registry.algorithmById(str(algorithm_id))
                if alg is None:
                    return {
                        "success": False,
                        "error": f"No algorithm with id {algorithm_id!r}.",
                    }
                params: list[dict[str, Any]] = []
                for pdef in alg.parameterDefinitions():
                    try:
                        optional = bool(pdef.flags() & pdef.FlagOptional)
                    except Exception:
                        optional = False
                    params.append(
                        {
                            "name": pdef.name(),
                            "type": pdef.type(),
                            "description": pdef.description(),
                            "optional": optional,
                            "default": pdef.defaultValue(),
                        }
                    )
                outputs: list[dict[str, Any]] = []
                try:
                    for odef in alg.outputDefinitions():
                        outputs.append(
                            {
                                "name": odef.name(),
                                "type": odef.type(),
                                "description": odef.description(),
                            }
                        )
                except Exception:
                    pass
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "id": alg.id(),
                "name": alg.displayName(),
                "group": alg.group() if hasattr(alg, "group") else "",
                "parameters": params,
                "outputs": outputs,
            }

        return _on_gui(_run)

    @geo_tool(category="capabilities", available_in=("full", "fast"))
    def list_plugins(active_only: bool = False) -> dict[str, Any]:
        """List installed KADAS/QGIS plugins with metadata.

        Reads each plugin's ``metadata.txt`` (name, version, description) via
        ``qgis.utils`` so the agent knows what plugins exist — including ones the
        user imported. Use ``describe_plugin`` for a plugin's commands and how to
        run them.

        Args:
            active_only: When True, only currently-loaded (active) plugins.

        Returns:
            ``{"success", "count", "plugins": [{"name", "title", "version",
            "description", "active"}]}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                import qgis.utils as qutils  # type: ignore[import-not-found]

                active = set(getattr(qutils, "active_plugins", []) or [])
                available = set(getattr(qutils, "available_plugins", []) or [])
                names = sorted(active) if active_only else sorted(available | active)
                plugins: list[dict[str, Any]] = []
                for name in names:

                    def _meta(key: str, _n: str = name) -> str:
                        try:
                            return qutils.pluginMetadata(_n, key) or ""
                        except Exception:
                            return ""

                    plugins.append(
                        {
                            "name": name,
                            "title": _meta("name"),
                            "version": _meta("version"),
                            "description": _meta("description"),
                            "active": name in active,
                        }
                    )
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "count": len(plugins), "plugins": plugins}

        return _on_gui(_run)

    @geo_tool(category="capabilities", available_in=("full", "fast"))
    def describe_plugin(name: str) -> dict[str, Any]:
        """Describe a plugin: metadata, its commands, and how to run them.

        Combines the plugin's ``metadata.txt`` with runtime introspection of the
        loaded plugin instance's registered ``QAction`` / ``QMenu`` /
        ``QShortcut`` objects, yielding the user-facing commands with their menu
        location and keyboard shortcut. This lets the agent tell the user *how to
        use* a GUI plugin (e.g. print, ephem) instead of executing it headlessly.
        A README/help snippet is included when present.

        Args:
            name: Plugin folder name, e.g. ``"kadas_print"`` (see ``list_plugins``).

        Returns:
            ``{"success", "name", "metadata", "active", "commands": [{"label",
            "menu", "shortcut"}], "readme"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                import sys

                import qgis.utils as qutils  # type: ignore[import-not-found]

                def _meta(key: str) -> str:
                    try:
                        return qutils.pluginMetadata(name, key) or ""
                    except Exception:
                        return ""

                metadata = {
                    "title": _meta("name"),
                    "version": _meta("version"),
                    "description": _meta("description"),
                    "about": _meta("about"),
                    "tags": _meta("tags"),
                    "homepage": _meta("homepage"),
                }
                instance = (getattr(qutils, "plugins", {}) or {}).get(name)
                active = instance is not None
                commands = _plugin_commands(instance) if instance is not None else []

                readme = ""
                if instance is not None:
                    try:
                        mod = sys.modules.get(type(instance).__module__)
                        plugin_dir = os.path.dirname(getattr(mod, "__file__", "") or "")
                        for fname in ("README.md", "readme.md", "README.txt"):
                            candidate = os.path.join(plugin_dir, fname)
                            if plugin_dir and os.path.isfile(candidate):
                                with open(candidate, encoding="utf-8") as fh:
                                    readme = fh.read(2000).strip()
                                break
                    except Exception:
                        readme = ""
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "name": name,
                "metadata": metadata,
                "active": active,
                "commands": commands,
                "readme": readme,
            }

        return _on_gui(_run)

    @geo_tool(category="capabilities", available_in=("full", "fast"))
    def list_kadas_actions(
        filter_text: str = "", enabled_only: bool = False
    ) -> dict[str, Any]:
        """List KADAS's own commands (QActions) discovered from the main window.

        KADAS exposes every command — File/Map operations, map tools, and plugin
        actions — as a named ``QAction`` on the main window (the registry behind
        ``KadasPluginInterface.findAction``). This enumerates them so the agent
        can discover a native KADAS command and run it with
        ``trigger_kadas_action`` instead of scripting a workaround. Imported
        plugins' actions appear here automatically once registered.

        Args:
            filter_text: Case-insensitive substring matched against each action's
                object name and menu text. Empty returns everything.
            enabled_only: When True, only currently-enabled actions.

        Returns:
            ``{"success", "count", "actions": [{"name", "text", "tooltip",
            "enabled", "visible", "checkable", "checked", "shortcut"}]}`` or a
            structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.PyQt.QtWidgets import (  # type: ignore[import-not-found]
                    QAction,
                )

                mw = iface.mainWindow() if hasattr(iface, "mainWindow") else None
                if mw is None:
                    return {"success": False, "error": "No main window available."}
                needle = str(filter_text or "").lower()
                seen: set = set()
                actions: list[dict[str, Any]] = []
                for act in mw.findChildren(QAction):
                    name = act.objectName()
                    if not name or name in seen:
                        # Unnamed actions cannot be triggered by name.
                        continue
                    seen.add(name)
                    if enabled_only and not act.isEnabled():
                        continue
                    text = act.text() or ""
                    if (
                        needle
                        and needle not in name.lower()
                        and needle not in text.lower()
                    ):
                        continue
                    actions.append(
                        {
                            "name": name,
                            "text": _action_text(text),
                            "tooltip": act.toolTip(),
                            "enabled": act.isEnabled(),
                            "visible": act.isVisible(),
                            "checkable": act.isCheckable(),
                            "checked": act.isChecked(),
                            "shortcut": act.shortcut().toString(),
                        }
                    )
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            actions.sort(key=lambda a: a["name"])
            return {"success": True, "count": len(actions), "actions": actions}

        return _on_gui(_run)

    @geo_tool(category="capabilities", requires_confirmation=True)
    def trigger_kadas_action(name: str) -> dict[str, Any]:
        """Run a native KADAS command by name (as if the user clicked it).

        Triggers the named ``QAction`` via ``KadasPluginInterface.findAction`` —
        e.g. ``"mActionSaveMapExtent"`` (Save Map), ``"mActionCopy"`` (Copy Map),
        ``"mActionNew"`` / ``"mActionOpen"`` / ``"mActionSave"``,
        ``"mActionPrint"``. Discover names with ``list_kadas_actions``.

        Because this runs the command's GUI, actions that need input (a save path,
        print options) will open their dialog for the user to complete — this tool
        does not pass parameters. For fully headless, parametrised operations use
        the dedicated tools (``open_project``, ``save_project``, ``export_layer``,
        ``export_gpkg``).

        Args:
            name: The action's object name, e.g. ``"mActionCopy"``.

        Returns:
            ``{"success", "name", "triggered"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                action = None
                if hasattr(iface, "findAction"):
                    try:
                        action = iface.findAction(name)
                    except Exception:
                        action = None
                if action is None:
                    from qgis.PyQt.QtWidgets import (  # type: ignore[import-not-found]
                        QAction,
                    )

                    mw = iface.mainWindow() if hasattr(iface, "mainWindow") else None
                    action = mw.findChild(QAction, name) if mw is not None else None
                if action is None:
                    return {
                        "success": False,
                        "error": (
                            f"No KADAS action named {name!r}. Use "
                            "list_kadas_actions to discover valid names."
                        ),
                    }
                if not action.isEnabled():
                    return {
                        "success": False,
                        "error": f"Action {name!r} is currently disabled.",
                    }
                action.trigger()
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"success": True, "name": name, "triggered": True}

        return _on_gui(_run)

    @geo_tool(category="capabilities", requires_confirmation=True, long_running=True)
    def export_layer(
        layer_name: str, output_path: str, driver: str = ""
    ) -> dict[str, Any]:
        """Export a project *vector* layer to a file (KML, KMZ, GeoJSON, SHP, …).

        Native OGR write via :class:`QgsVectorFileWriter`; the output driver is
        inferred from the file extension unless ``driver`` is given. Covers the
        "export layer as <format>" cases (``.kml``, ``.kmz``, ``.geojson``,
        ``.shp``, ``.gml``, ``.csv``, ``.gpx``, single-layer ``.gpkg``). For a
        full KADAS project archive use ``export_gpkg`` instead.

        Note: KADAS *redlining* is a ``QgsAnnotationLayer``, not a vector layer,
        so it cannot be exported with this tool (it returns a clear error).

        Args:
            layer_name: Name of the project vector layer to export.
            output_path: Destination file path; the extension picks the format.
            driver: Optional explicit OGR driver name (e.g. ``"KML"``,
                ``"LIBKML"``, ``"GeoJSON"``, ``"ESRI Shapefile"``).

        Returns:
            ``{"success", "path", "driver", "features"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsVectorFileWriter,
                    QgsVectorLayer,
                )

                proj = _project()
                out = os.path.abspath(os.path.expanduser(str(output_path)))
                candidates = [
                    lyr for lyr in proj.mapLayers().values() if lyr.name() == layer_name
                ]
                if not candidates:
                    return {
                        "success": False,
                        "error": f"No layer named {layer_name!r}.",
                    }
                layer = candidates[0]
                if not isinstance(layer, QgsVectorLayer):
                    return {
                        "success": False,
                        "error": (
                            f"{layer_name!r} is not a vector layer "
                            f"({type(layer).__name__}); annotation/redlining "
                            "layers are not supported by export_layer."
                        ),
                    }
                drv = driver or _ogr_driver_from_ext(out)
                if not drv:
                    return {
                        "success": False,
                        "error": f"Cannot infer an OGR driver for {out!r}; pass `driver`.",
                    }
                os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = drv
                options.fileEncoding = "utf-8"
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, out, proj.transformContext(), options
                )
                error_code = result[0] if isinstance(result, tuple) else result
                if int(getattr(error_code, "value", error_code)) != 0:
                    message = (
                        result[1]
                        if isinstance(result, tuple) and len(result) > 1
                        else str(error_code)
                    )
                    return {"success": False, "error": str(message)}
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": True,
                "path": out,
                "driver": drv,
                "features": layer.featureCount(),
            }

        return _on_gui(_run)

    @geo_tool(category="capabilities", requires_confirmation=True, long_running=True)
    def export_gpkg(
        output_path: str,
        layer_names: Optional[list[str]] = None,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        """Export the project to a KADAS-native GeoPackage (full-project archive).

        Reuses the KADAS ``kadas_gpkg`` plugin's own export classes to produce a
        true KADAS GeoPackage: the vector/raster layers **plus** the whole QGIS
        project and its resources are embedded in the ``.gpkg`` (the qgpkg
        format), so ``import_gpkg`` can restore styling and layout — unlike a
        plain per-layer OGR dump. Requires the ``kadas_gpkg`` plugin (a real
        KADAS runtime).

        Args:
            output_path: Destination ``.gpkg`` file path.
            layer_names: Names of project layers to export. When omitted, every
                layer is exported.
            overwrite: Overwrite ``output_path`` if it already exists.

        Returns:
            ``{"success", "path", "written", "messages"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            import shutil
            import sqlite3

            KadasGpkgExport, _ = _kadas_gpkg_classes()
            if KadasGpkgExport is None:
                return {
                    "success": False,
                    "error": "kadas_gpkg plugin not available (not a KADAS runtime).",
                }
            try:
                from lxml import etree as ET  # type: ignore[import-not-found]
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsMapLayer,
                    QgsPathResolver,
                )
                from qgis.PyQt.QtCore import (  # type: ignore[import-not-found]
                    QTemporaryDir,
                )

                out = os.path.abspath(os.path.expanduser(str(output_path)))
                if os.path.exists(out) and not overwrite:
                    return {"success": False, "error": f"{out!r} already exists."}

                proj = _project()
                all_layers = list(proj.mapLayers().items())
                if layer_names:
                    wanted = set(layer_names)
                    selected = [lid for lid, lyr in all_layers if lyr.name() in wanted]
                else:
                    selected = [lid for lid, _lyr in all_layers]
                if not selected:
                    return {"success": False, "error": "No matching layers to export."}

                tmpdir = QTemporaryDir()
                gpkg_writefile = tmpdir.filePath(os.path.basename(out) or "export.gpkg")

                export = KadasGpkgExport(iface)
                conn = sqlite3.connect(gpkg_writefile)
                cursor = conn.cursor()
                export.init_gpkg(cursor)
                export.init_gpkg_qgis(cursor)
                conn.commit()
                conn.close()

                layer_sources: set = set()
                for _lid, lyr in all_layers:
                    layer_sources.add(lyr.source())
                    if lyr.providerType() == "ogr":
                        layer_sources.add(lyr.source().split("|")[0])
                layer_sources = list(layer_sources)

                added_layer_ids: list[str] = []
                added_layers_by_source: dict[str, str] = {}
                messages: list[str] = []
                pdialog = _HeadlessProgress()
                export.write_layers(
                    selected,
                    gpkg_writefile,
                    pdialog,
                    added_layer_ids,
                    added_layers_by_source,
                    messages,
                    False,  # pyramids
                    None,  # filterExtent
                    None,  # filterExtentCrs
                    None,  # rasterExportScale
                )

                # Embed the project XML + resources (mirrors KadasGpkgExport).
                prev_filename = proj.fileName()
                prev_dirty = proj.isDirty()
                tmpfile = tmpdir.filePath("gpkg_project.qgs")
                proj.setFileName(tmpfile)
                additional_resources: dict[str, str] = {}
                writer_id = QgsPathResolver.setPathWriter(
                    lambda path: export.rewriteProjectPaths(
                        path,
                        out,
                        added_layers_by_source,
                        layer_sources,
                        additional_resources,
                    )
                )
                proj.write()
                QgsPathResolver.removePathWriter(writer_id)
                proj.setFileName(prev_filename if prev_filename else "")
                proj.setDirty(prev_dirty)

                parser = ET.XMLParser(strip_cdata=False)
                doc = ET.parse(tmpfile, parser=parser)
                projectlayers = doc.find("projectlayers")
                if projectlayers is not None:
                    for projectlayerEl in projectlayers:
                        lid_el = projectlayerEl.find("id")
                        if lid_el is None or lid_el.text not in added_layer_ids:
                            continue
                        layer = proj.mapLayer(lid_el.text)
                        prov = projectlayerEl.find("provider")
                        if prov is None or layer is None:
                            continue
                        if layer.type() == QgsMapLayer.VectorLayer:
                            prov.text = "ogr"
                        elif layer.type() == QgsMapLayer.RasterLayer:
                            prov.text = "gdal"
                if layer_names:
                    _strip_unselected_layers(doc, set(selected))

                conn = sqlite3.connect(gpkg_writefile)
                cursor = conn.cursor()
                for path, resource_id in additional_resources.items():
                    export.add_resource(cursor, path, resource_id)
                export.write_project(cursor, ET.tostring(doc.getroot()))
                conn.commit()
                conn.close()

                if os.path.exists(out):
                    os.remove(out)
                shutil.move(gpkg_writefile, out)
                written = [
                    proj.mapLayer(lid).name()
                    for lid in added_layer_ids
                    if proj.mapLayer(lid)
                ]
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "success": bool(added_layer_ids),
                "path": out,
                "written": written,
                "messages": messages,
            }

        return _on_gui(_run)

    @geo_tool(category="capabilities", requires_confirmation=True)
    def import_gpkg(
        path: str, layer_names: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Import layers from a KADAS-native GeoPackage into the current project.

        Reuses the KADAS ``kadas_gpkg`` plugin's import logic: if the ``.gpkg``
        embeds a QGIS project (a KADAS GeoPackage), its layers are restored with
        styling and resources; otherwise the ``.gpkg`` is loaded as plain OGR/
        GDAL sublayers. Adds to the current project (does not replace it).

        Args:
            path: Source ``.gpkg`` file path.
            layer_names: Restrict to layers whose name matches. When omitted, all
                layers are imported.

        Returns:
            ``{"success", "path", "imported", "failed"}`` or a structured error.
        """

        def _run() -> dict[str, Any]:
            import sqlite3

            _, KadasGpkgImport = _kadas_gpkg_classes()
            gpkg = os.path.abspath(os.path.expanduser(str(path)))
            if not os.path.isfile(gpkg):
                return {"success": False, "error": f"File not found: {gpkg!r}."}
            imported: list[str] = []
            failed: list[str] = []
            conn = None
            try:
                from qgis.core import (  # type: ignore[import-not-found]
                    QgsPathResolver,
                    QgsProject,
                    QgsProviderRegistry,
                    QgsProviderSublayerDetails,
                    QgsReadWriteContext,
                )
                from qgis.PyQt.QtXml import (  # type: ignore[import-not-found]
                    QDomDocument,
                )

                importer = (
                    KadasGpkgImport(iface) if KadasGpkgImport is not None else None
                )
                xml = None
                cursor = None
                if importer is not None:
                    conn = sqlite3.connect(gpkg)
                    cursor = conn.cursor()
                    xml = importer.read_project(cursor)

                proj = _project()
                if not xml:
                    # Plain GeoPackage: load OGR/GDAL sublayers directly.
                    if conn is not None:
                        conn.close()
                        conn = None
                    details = QgsProviderRegistry.instance().querySublayers(gpkg)
                    options = QgsProviderSublayerDetails.LayerOptions(
                        proj.transformContext()
                    )
                    wanted = set(layer_names) if layer_names else None
                    for detail in details:
                        if wanted is not None and detail.name() not in wanted:
                            continue
                        try:
                            lyr = detail.toLayer(options)
                            if lyr is not None and lyr.isValid():
                                proj.addMapLayer(lyr)
                                imported.append(detail.name())
                            else:
                                failed.append(detail.name())
                        except Exception:
                            failed.append(detail.name())
                    return {
                        "success": bool(imported),
                        "path": gpkg,
                        "imported": imported,
                        "failed": failed,
                    }

                # KADAS GeoPackage with embedded project: restore layers.
                doc = QDomDocument()
                doc.setContent(xml)
                extracted_resources: dict[str, str] = {}
                preprocessor_id = QgsPathResolver.setPathPreprocessor(
                    lambda p: importer.gpkgResourceToAttachment(
                        p, cursor, gpkg, extracted_resources
                    )
                )
                context = QgsReadWriteContext()
                context.setPathResolver(QgsProject.instance().pathResolver())
                context.setProjectTranslator(QgsProject.instance())
                context.setTransformContext(QgsProject.instance().transformContext())
                maplayers = doc.elementsByTagName("maplayer")
                wanted = set(layer_names) if layer_names else None
                for i in range(0, maplayers.size()):
                    maplayer = maplayers.at(i)
                    try:
                        layername = maplayer.firstChildElement("layername").text()
                    except Exception:
                        layername = ""
                    if wanted is not None and layername not in wanted:
                        continue
                    if importer.addProjectLayer(maplayer.toElement(), context):
                        imported.append(layername)
                    else:
                        failed.append(layername)
                QgsPathResolver.removePathPreprocessor(preprocessor_id)
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            finally:
                if conn is not None:
                    conn.close()
            return {
                "success": bool(imported),
                "path": gpkg,
                "imported": imported,
                "failed": failed,
            }

        return _on_gui(_run)

    @geo_tool(category="capabilities", available_in=("full", "fast"))
    def query_agent_logs(
        kind: str = "all", contains: str = "", limit: int = 50
    ) -> dict[str, Any]:
        """Query GeoAgent's JSONL execution/feedback logs (system log querying).

        Reads back the agent's own log files — the execution trace
        (``agent_execution.log``: turns, tool calls, tool results, errors) and
        the "Training AI" feedback log (``agent_feedback.log``) — filters them,
        and returns the most recent matching entries. Use this to answer "what
        did the last run do", "what errored", or "show the failed feedback".

        Args:
            kind: ``all``, ``execution``, ``feedback``, or a specific trace kind
                such as ``tool_call``, ``tool_result``, ``error``, ``turn_end``.
            contains: Case-insensitive substring filter over each entry's text.
            limit: Maximum number of (most recent) entries to return.

        Returns:
            ``{"success", "count", "entries": [ ... ], "sources": [...]}`` or a
            structured error.
        """
        from geoagent.core.telemetry import (
            default_feedback_path,
            default_log_path,
        )

        want = str(kind or "all").strip().lower()
        needle = str(contains or "").lower()
        cap = max(1, int(limit))

        sources: list[str] = []
        if want in ("all", "execution") or want not in ("feedback",):
            sources.append(str(default_log_path()))
        if want in ("all", "feedback"):
            sources.append(str(default_feedback_path()))
        # Deduplicate while preserving order.
        sources = list(dict.fromkeys(sources))

        entries: list[dict[str, Any]] = []
        specific_kind = want not in ("all", "execution", "feedback")
        for src in sources:
            try:
                with open(src, encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except Exception:
                            continue
                        if specific_kind and str(event.get("kind", "")).lower() != want:
                            continue
                        if (
                            needle
                            and needle not in json.dumps(event, default=str).lower()
                        ):
                            continue
                        entries.append(event)
            except FileNotFoundError:
                continue
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}

        # Most recent first, then cap.
        entries.sort(key=lambda e: e.get("time", 0), reverse=True)
        entries = entries[:cap]
        return {
            "success": True,
            "count": len(entries),
            "entries": entries,
            "sources": sources,
        }

    return [
        list_qgis_capabilities,
        list_processing_algorithms,
        describe_processing_algorithm,
        list_plugins,
        describe_plugin,
        list_kadas_actions,
        trigger_kadas_action,
        export_layer,
        export_gpkg,
        import_gpkg,
        query_agent_logs,
    ]


__all__ = ["capability_tools"]
