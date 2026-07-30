# -*- coding: utf-8 -*-
"""KADAS GeoAgent plugin.

KADAS Albireo 2 wrapper around the shared GeoAgent core and the
host-agnostic OpenGeoAgent chat/settings dock widgets. The plugin casts the
KADAS interface, adapts it to the QGIS ``iface`` surface GeoAgent expects
(see :mod:`kadas_geoagent.kadas_iface_adapter`), and registers its actions in
the KADAS ribbon.
"""


def classFactory(iface):
    """Load the KadasGeoAgent plugin class.

    Args:
        iface: The interface instance passed by KADAS. It is cast to
            ``KadasPluginInterface`` inside the plugin.
    """
    from .kadas_geoagent import KadasGeoAgent

    return KadasGeoAgent(iface)
