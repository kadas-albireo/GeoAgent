# -*- coding: utf-8 -*-
"""KADAS GeoAgent plugin class.

Registers chat and settings actions in the KADAS ribbon (``PLUGIN_MENU`` /
``MAPS_TAB``, mirroring the KADAS MBTiles plugin) and hosts the shared
OpenGeoAgent dock widgets, wiring them to the KADAS interface through
:class:`~kadas_geoagent.kadas_iface_adapter.KadasIfaceAdapter`.
"""

import os

from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtWidgets import QMessageBox

from kadas.kadasgui import KadasPluginInterface

from .kadas_iface_adapter import KadasIfaceAdapter
from ._shared import ensure_open_geoagent_importable

PLUGIN_DIR = os.path.dirname(__file__)


class KadasGeoAgent(QObject):
    """KADAS Albireo 2 plugin exposing GeoAgent through dockable panels."""

    def __init__(self, iface):
        """Initialize the plugin and adapt the KADAS interface.

        Args:
            iface: Interface passed by KADAS; cast to ``KadasPluginInterface``.
        """
        QObject.__init__(self)

        # Keep developer-mode run logs inside this plugin checkout's git-ignored
        # ``runs/`` folder instead of the shared ~/.open_geoagent/logs default,
        # so KADAS run traces never get pushed to the remote. realpath() resolves
        # the KADAS profile symlink back to the source tree where
        # kadas_geoagent/.gitignore lives. setdefault() lets an explicit
        # GEOAGENT_RUN_LOG_DIR override win. The shared RunLogger reads this var.
        _plugin_root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        os.environ.setdefault(
            "GEOAGENT_RUN_LOG_DIR", os.path.join(_plugin_root, "runs")
        )

        # Cast to the KADAS interface (same pattern as kadas_mbtiles), then
        # wrap it so the shared GeoAgent code sees a QGIS-style ``iface``.
        self.kadas_iface = KadasPluginInterface.cast(iface)
        self.iface = KadasIfaceAdapter(self.kadas_iface)

        self._chat_dock = None
        self._settings_dock = None
        self.chat_action = None
        self.settings_action = None

    # -- Lifecycle -------------------------------------------------------

    def initGui(self):
        """Create KADAS ribbon entries for the chat and settings panels."""
        chat_icon = self._icon("icon.svg")
        settings_icon = self._icon("settings.svg")

        self.chat_action = QAction(chat_icon, self.tr("GeoAgent Chat"))
        self.chat_action.setCheckable(True)
        self.chat_action.triggered.connect(self.toggle_chat_dock)

        self.settings_action = QAction(settings_icon, self.tr("GeoAgent Settings"))
        self.settings_action.setCheckable(True)
        self.settings_action.triggered.connect(self.toggle_settings_dock)

        # KADAS ribbon placement (see kadas_mbtiles): add into the plugin
        # menu under the Maps tab.
        self.kadas_iface.addAction(
            self.chat_action,
            self.kadas_iface.PLUGIN_MENU,
            self.kadas_iface.MAPS_TAB,
        )
        self.kadas_iface.addAction(
            self.settings_action,
            self.kadas_iface.PLUGIN_MENU,
            self.kadas_iface.MAPS_TAB,
        )

    def unload(self):
        """Remove docks and ribbon actions."""
        if self._chat_dock is not None:
            self._remove_dock(self._chat_dock)
            self._chat_dock = None
        if self._settings_dock is not None:
            self._remove_dock(self._settings_dock)
            self._settings_dock = None

        for action in (self.chat_action, self.settings_action):
            if action is None:
                continue
            self.kadas_iface.removeAction(
                action,
                self.kadas_iface.PLUGIN_MENU,
                self.kadas_iface.MAPS_TAB,
            )
        self.chat_action = None
        self.settings_action = None

    # -- Chat dock -------------------------------------------------------

    def toggle_chat_dock(self):
        """Show, create, or hide the chat dock (hides settings when shown)."""
        if self._dependencies_missing():
            self._show_settings_dock(dependencies_tab=True)
            self._warn(
                "Install missing dependencies before opening the chat panel."
            )
            return

        # Already open: clicking the ribbon entry again closes it.
        if self._chat_dock is not None and self._chat_dock.isVisible():
            self._chat_dock.hide()
            self._set_checked(self.chat_action, False)
            return

        if self._chat_dock is None:
            widget_cls = self._user_chat_dock_class()
            if widget_cls is None:
                self._set_checked(self.chat_action, False)
                return
            self._chat_dock = widget_cls(self.iface, self.kadas_iface.mainWindow())
            self._chat_dock.setObjectName("KadasGeoAgentChatDock")
            self._add_dock(self._chat_dock)

        self._show_exclusive(
            self._chat_dock,
            self.chat_action,
            self._settings_dock,
            self.settings_action,
        )

    # -- Settings dock ---------------------------------------------------

    def toggle_settings_dock(self):
        """Toggle the settings dock (hides chat when shown)."""
        # Already open: clicking the ribbon entry again closes it.
        if self._settings_dock is not None and self._settings_dock.isVisible():
            self._settings_dock.hide()
            self._set_checked(self.settings_action, False)
            return
        self._show_settings_dock()

    def _show_settings_dock(self, dependencies_tab=False):
        """Ensure the settings dock exists and is the only visible panel."""
        if self._settings_dock is None:
            widget_cls = self._import_dock("settings_dock", "SettingsDockWidget")
            if widget_cls is None:
                self._set_checked(self.settings_action, False)
                return
            self._settings_dock = widget_cls(
                self.iface, self.kadas_iface.mainWindow()
            )
            self._settings_dock.setObjectName("KadasGeoAgentSettingsDock")
            self._add_dock(self._settings_dock)

        self._show_exclusive(
            self._settings_dock,
            self.settings_action,
            self._chat_dock,
            self.chat_action,
        )
        if dependencies_tab and hasattr(
            self._settings_dock, "show_dependencies_tab"
        ):
            self._settings_dock.show_dependencies_tab()

    # -- Helpers ---------------------------------------------------------

    def _icon(self, name):
        """Return a QIcon from the plugin icons dir, or an empty icon."""
        path = os.path.join(PLUGIN_DIR, "icons", name)
        return QIcon(path) if os.path.exists(path) else QIcon()

    def _add_dock(self, dock):
        """Dock a widget on the KADAS main window's right area.

        KadasPluginInterface does not expose ``addDockWidget``; the KADAS main
        window is a QMainWindow, so we add the dock to it directly.
        """
        self.kadas_iface.mainWindow().addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, dock
        )

    def _remove_dock(self, dock):
        """Remove a dock from the KADAS main window and delete it."""
        try:
            self.kadas_iface.mainWindow().removeDockWidget(dock)
        except Exception:
            pass  # nosec B110
        dock.deleteLater()

    def _show_exclusive(self, dock, action, other_dock, other_action):
        """Show ``dock`` as the only visible panel, hiding its sibling.

        Both docks share the right dock area, so showing them together makes
        KADAS tabify/overlap them and the ribbon checkmarks drift out of sync.
        Keeping exactly one visible avoids that.
        """
        if other_dock is not None and other_dock is not dock:
            other_dock.hide()
        self._set_checked(other_action, False)
        dock.show()
        dock.raise_()
        self._set_checked(action, True)

    @staticmethod
    def _set_checked(action, checked):
        """Sync a checkable ribbon action's state with dock visibility."""
        if action is not None:
            action.setChecked(checked)

    def _dependencies_missing(self):
        """Return True when the shared package or its deps are unavailable."""
        if ensure_open_geoagent_importable() is None:
            return True
        try:
            from open_geoagent.deps_manager import all_dependencies_met

            return not all_dependencies_met()
        except Exception:
            return True

    def _user_chat_dock_class(self):
        """Return the KADAS user-mode chat dock class, or None on failure.

        Wraps the shared ``ChatDockWidget`` with a minimal "user mode" front
        end (see :mod:`kadas_geoagent.user_chat_dock`). The shared package must
        be importable first, so this mirrors the guard in :meth:`_import_dock`.
        """
        if ensure_open_geoagent_importable() is None:
            self._error(
                "The shared OpenGeoAgent package was not found.\n\n"
                "Install the OpenGeoAgent plugin alongside KADAS GeoAgent, "
                "or set the KADAS_GEOAGENT_OPENGEOAGENT_PATH environment "
                "variable to the directory containing the 'open_geoagent' "
                "package."
            )
            return None
        try:
            from .user_chat_dock import build_kadas_chat_dock_class

            return build_kadas_chat_dock_class()
        except Exception as exc:
            self._error(f"Failed to load the chat panel:\n{exc}")
            return None

    def _import_dock(self, module_name, class_name):
        """Import a shared OpenGeoAgent dock class, or report failure.

        Args:
            module_name: Submodule under ``open_geoagent.dialogs``.
            class_name: Dock widget class to import.

        Returns:
            The widget class, or ``None`` if the shared package is missing.
        """
        if ensure_open_geoagent_importable() is None:
            self._error(
                "The shared OpenGeoAgent package was not found.\n\n"
                "Install the OpenGeoAgent plugin alongside KADAS GeoAgent, "
                "or set the KADAS_GEOAGENT_OPENGEOAGENT_PATH environment "
                "variable to the directory containing the 'open_geoagent' "
                "package."
            )
            return None
        try:
            import importlib

            module = importlib.import_module(
                f"open_geoagent.dialogs.{module_name}"
            )
            return getattr(module, class_name)
        except Exception as exc:
            self._error(f"Failed to load the {class_name} panel:\n{exc}")
            return None

    def _warn(self, message):
        """Push a warning to the KADAS message bar (best effort)."""
        try:
            self.kadas_iface.messageBar().pushWarning("KADAS GeoAgent", message)
        except Exception:
            pass  # nosec B110

    def _error(self, message):
        """Show a critical dialog parented to the KADAS main window."""
        QMessageBox.critical(
            self.kadas_iface.mainWindow(), "KADAS GeoAgent", message
        )
