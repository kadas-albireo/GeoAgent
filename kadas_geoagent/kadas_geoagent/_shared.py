"""Resolve the shared OpenGeoAgent dock package for reuse in KADAS.

Architecture: ``geoagent`` (the agent core) is a shared pip dependency, and
the host-agnostic chat/settings UI lives in the ``open_geoagent`` package that
ships with the QGIS OpenGeoAgent plugin. KADAS GeoAgent is a *sibling* wrapper
that reuses both rather than forking the ~6k lines of dock UI.

The dock widgets take an ``iface`` in their constructor and -- as verified
against the source -- only call ``activeLayer``, ``setActiveLayer``,
``mapCanvas``, ``mainWindow`` and ``messageBar`` on it, all of which the
:class:`~kadas_geoagent.kadas_iface_adapter.KadasIfaceAdapter` provides. So the
same widgets run unchanged under KADAS once handed the adapter.

This module makes ``open_geoagent`` importable. In a deployed KADAS install,
the cleanest setup is for ``open_geoagent`` to be on the Python path already
(installed as a package, or both plugins present). As a fallback we look for a
sibling OpenGeoAgent plugin checkout and add its package root to ``sys.path``.
"""

from __future__ import annotations

import glob
import importlib
import os
import sys
from typing import Optional

# Environment override for non-standard layouts: point this at the directory
# that *contains* the ``open_geoagent`` package. Takes priority over discovery.
_ENV_OVERRIDE = "KADAS_GEOAGENT_OPENGEOAGENT_PATH"

# How many directory levels to walk up from this file when searching the
# monorepo for the shared package. Bounds the scan so we never crawl from "/".
_MAX_WALK_UP = 8


def _candidate_roots() -> list[str]:
    """Return directories that may contain the ``open_geoagent`` package.

    Discovery is *location-independent*: rather than assuming a fixed monorepo
    depth (which breaks the moment the plugin is nested differently, or launched
    via VS Code / a bare shell instead of run-kadas.sh), we walk up the
    directory tree from this file and, at each ancestor, look for the package
    directly under it or under any immediate child (e.g. a sibling
    ``qgis_geoagent`` plugin folder). This works regardless of how Kadas was
    started, because it depends only on where the plugin lives on disk.
    """
    roots: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        path = os.path.abspath(path)
        if path not in seen:
            seen.add(path)
            roots.append(path)

    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        add(override)

    # realpath (not abspath) so a symlinked plugin resolves back to its real
    # location in the monorepo, where the sibling open_geoagent checkout lives.
    ancestor = os.path.dirname(os.path.realpath(__file__))
    for _ in range(_MAX_WALK_UP):
        # The package may sit directly under this ancestor ...
        add(ancestor)
        # ... or one level down, e.g. <ancestor>/qgis_geoagent/open_geoagent.
        for match in glob.glob(os.path.join(ancestor, "*", "open_geoagent", "__init__.py")):
            add(os.path.dirname(os.path.dirname(match)))
        parent = os.path.dirname(ancestor)
        if parent == ancestor:  # reached filesystem root
            break
        ancestor = parent

    return roots


def ensure_open_geoagent_importable() -> Optional[str]:
    """Make the ``open_geoagent`` package importable; return its path or None.

    Returns:
        The resolved package directory if found, otherwise ``None`` (the
        caller should surface a "missing shared package" message).
    """
    try:
        module = importlib.import_module("open_geoagent")
        return os.path.dirname(getattr(module, "__file__", "")) or None
    except Exception:
        pass

    for root in _candidate_roots():
        package_init = os.path.join(root, "open_geoagent", "__init__.py")
        if os.path.isfile(package_init):
            if root not in sys.path:
                sys.path.insert(0, root)
            try:
                importlib.import_module("open_geoagent")
                return os.path.join(root, "open_geoagent")
            except Exception:
                continue
    return None
