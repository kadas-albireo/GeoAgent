"""Sandboxed access to files outside the project directory.

The agent normally works inside the live QGIS/KADAS project. Task work often
needs reference data that lives *elsewhere* on disk (a shared network GIS mount,
a downloads folder, a field-survey directory). Handing the agent a raw
``run_command``/``open()`` to roam the filesystem is unsafe, so this module
exposes a **boundary-crossing but sandboxed** file surface instead.

How the boundary crossing works under the hood
----------------------------------------------
1. The host configures one or more *allowed roots* — absolute directories the
   agent may read. Roots come from (in order) an explicit ``roots=`` argument to
   :func:`external_files_tools`, then the ``GEOAGENT_EXTERNAL_ROOTS`` environment
   variable (``os.pathsep``-separated). Nothing is exposed if neither is set.
2. Every path the agent supplies is joined against a root and then
   **fully resolved** with :func:`os.path.realpath` (which collapses ``..`` and
   follows symlinks). The resolved path must still sit inside one of the allowed
   roots — checked with :func:`os.path.commonpath`, not string ``startswith``,
   so ``/data/../etc`` or a symlink pointing outside the root is rejected.
3. Only reads are ever performed (listing, globbing, reading text). There is no
   write/delete surface and no shell — the boundary is read-only by construction.

This keeps the useful capability ("look at that folder over there") while making
it impossible for the model to escape the roots the human explicitly opened.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from geoagent.core.decorators import geo_tool

# Files larger than this are truncated when read, to keep tool results bounded.
_MAX_READ_BYTES = 200_000

# Extensions treated as spatial datasets by ``find_spatial_data``. These are the
# formats KADAS/QGIS can open natively through the OGR/GDAL providers; the tool
# never parses them itself (no shapefile/geojson library), it hands the path to
# QGIS' own provider registry.
_SPATIAL_EXTS = (
    ".shp",
    ".gpkg",
    ".geojson",
    ".json",
    ".kml",
    ".kmz",
    ".gml",
    ".tab",
    ".fgb",
    ".gpx",
    ".sqlite",
    ".csv",
)


def resolve_roots(roots: Optional[list[str | os.PathLike[str]]] = None) -> list[Path]:
    """Return the configured allowed roots as resolved absolute directories.

    Merges an explicit ``roots`` list with ``GEOAGENT_EXTERNAL_ROOTS`` (an
    ``os.pathsep``-separated env var). Non-existent or non-directory entries are
    dropped, and duplicates are collapsed.
    """
    raw: list[str | os.PathLike[str]] = list(roots or [])
    env = os.environ.get("GEOAGENT_EXTERNAL_ROOTS", "")
    if env:
        raw.extend(part for part in env.split(os.pathsep) if part)

    resolved: list[Path] = []
    seen: set[str] = set()
    for entry in raw:
        try:
            path = Path(os.path.realpath(os.path.expanduser(str(entry))))
        except Exception:
            continue
        key = str(path)
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        resolved.append(path)
    return resolved


def _contained_in(path: Path, root: Path) -> bool:
    """Return True when ``path`` is ``root`` or lives beneath it (realpath-based)."""
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        # Different drives (Windows) -> not contained.
        return False


def _resolve_within_roots(
    user_path: str, roots: list[Path]
) -> tuple[Optional[Path], Optional[Path]]:
    """Resolve ``user_path`` and return ``(resolved, matching_root)`` if allowed.

    ``user_path`` may be absolute (must fall inside a root) or relative (joined
    against each root until one contains it). Returns ``(None, None)`` when no
    root contains the resolved target.
    """
    candidate = os.path.expanduser(str(user_path or ""))
    for root in roots:
        if os.path.isabs(candidate):
            base = candidate
        else:
            base = os.path.join(str(root), candidate)
        resolved = Path(os.path.realpath(base))
        if _contained_in(resolved, root):
            return resolved, root
    return None, None


def _inspect_spatial_file(path: Path) -> dict[str, Any]:
    """Inspect one spatial file via QGIS' native provider registry.

    Uses :meth:`QgsProviderRegistry.querySublayers` for cheap metadata
    (name/geometry/feature count) and, per sublayer, a short-lived
    :class:`QgsVectorLayer` to read the CRS and field names. QGIS is imported
    lazily so this module stays import-safe in plain CI; when QGIS is absent the
    file is reported with an ``inspect_error`` note instead of raising.
    """
    record: dict[str, Any] = {"path": str(path), "name": path.name}
    try:
        from qgis.core import (  # type: ignore[import-not-found]
            QgsProviderRegistry,
            QgsVectorLayer,
            QgsWkbTypes,
        )
    except Exception as exc:  # pragma: no cover - exercised only outside QGIS
        record["inspect_error"] = f"{type(exc).__name__}: {exc}"
        return record

    try:
        details = QgsProviderRegistry.instance().querySublayers(str(path))
        sublayers: list[dict[str, Any]] = []
        for detail in details:
            info: dict[str, Any] = {}
            for attr in ("name", "driverName", "providerKey"):
                getter = getattr(detail, attr, None)
                if callable(getter):
                    try:
                        info[attr] = getter()
                    except Exception:
                        pass
            try:
                info["geometry"] = QgsWkbTypes.displayString(detail.wkbType())
            except Exception:
                pass
            try:
                count = detail.featureCount()
                info["feature_count"] = None if count < 0 else int(count)
            except Exception:
                pass
            # A short-lived layer gives CRS + field names without loading data.
            try:
                uri = detail.uri()
                provider = info.get("providerKey", "ogr")
                layer = QgsVectorLayer(uri, info.get("name", path.stem), provider)
                if layer is not None and layer.isValid():
                    info["crs"] = layer.crs().authid() or None
                    info["fields"] = [f.name() for f in layer.fields()][:50]
            except Exception:
                pass
            sublayers.append(info)
        record["sublayers"] = sublayers
        if not sublayers:
            record["inspect_error"] = "No readable sublayers (unsupported/empty)."
    except Exception as exc:
        record["inspect_error"] = f"{type(exc).__name__}: {exc}"
    return record


def external_files_tools(
    roots: Optional[list[str | os.PathLike[str]]] = None,
) -> list[Any]:
    """Build the sandboxed external-file tool set.

    Args:
        roots: Explicit allowed root directories. Combined with
            ``GEOAGENT_EXTERNAL_ROOTS``. When no roots resolve, an empty tool
            list is returned so the capability is simply absent.

    Returns:
        A list of Strands tool objects (empty when no roots are configured).
    """
    allowed = resolve_roots(roots)
    if not allowed:
        return []

    @geo_tool(category="external_files", available_in=("full", "fast"))
    def list_external_roots() -> dict[str, Any]:
        """List the external folders the agent is allowed to read.

        Returns:
            ``{"success", "roots": [str, ...]}``.
        """
        return {"success": True, "roots": [str(r) for r in allowed]}

    @geo_tool(category="external_files", available_in=("full", "fast"))
    def scan_external_folder(
        subpath: str = "",
        pattern: str = "*",
        recursive: bool = False,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List entries in a configured external folder (sandboxed).

        Args:
            subpath: Folder to list, relative to a root (or an absolute path that
                resolves inside a root). Empty lists the roots themselves.
            pattern: Glob pattern to match names, e.g. ``*.tif`` or ``*.gpkg``.
            recursive: Recurse into subfolders when True.
            max_results: Cap on the number of entries returned.

        Returns:
            ``{"success", "base", "entries": [{"name", "path", "is_dir",
            "size"}], "truncated"}`` or a structured error.
        """
        target, root = _resolve_within_roots(subpath or ".", allowed)
        if target is None:
            return {
                "success": False,
                "error": (f"Path {subpath!r} is outside the allowed external roots."),
            }
        if not target.exists():
            return {"success": False, "error": f"Path does not exist: {target}"}
        if not target.is_dir():
            return {"success": False, "error": f"Not a directory: {target}"}

        globber = target.rglob if recursive else target.glob
        entries: list[dict[str, Any]] = []
        truncated = False
        try:
            for item in globber(pattern):
                # Defence in depth: a matched symlink must also stay in the root.
                real = Path(os.path.realpath(item))
                if not _contained_in(real, root):
                    continue
                try:
                    is_dir = item.is_dir()
                    size = item.stat().st_size if item.is_file() else None
                except OSError:
                    continue
                entries.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "is_dir": is_dir,
                        "size": size,
                    }
                )
                if len(entries) >= max(1, int(max_results)):
                    truncated = True
                    break
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "success": True,
            "base": str(target),
            "entries": entries,
            "truncated": truncated,
        }

    @geo_tool(category="external_files", available_in=("full", "fast"))
    def read_external_file(
        path: str, max_bytes: int = _MAX_READ_BYTES
    ) -> dict[str, Any]:
        """Read a UTF-8 text file from a configured external folder (sandboxed).

        Args:
            path: File to read, relative to a root or an absolute path that
                resolves inside a root.
            max_bytes: Maximum number of bytes to read (content is truncated
                beyond this).

        Returns:
            ``{"success", "path", "content", "truncated", "size"}`` or a
            structured error.
        """
        target, _root = _resolve_within_roots(path, allowed)
        if target is None:
            return {
                "success": False,
                "error": f"Path {path!r} is outside the allowed external roots.",
            }
        if not target.is_file():
            return {"success": False, "error": f"Not a file: {target}"}
        try:
            size = target.stat().st_size
            cap = max(1, int(max_bytes))
            with target.open("rb") as handle:
                raw = handle.read(cap + 1)
            truncated = len(raw) > cap
            content = raw[:cap].decode("utf-8", errors="replace")
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "success": True,
            "path": str(target),
            "content": content,
            "truncated": truncated,
            "size": size,
        }

    @geo_tool(category="external_files", available_in=("full", "fast"))
    def find_spatial_data(
        subpath: str = "",
        recursive: bool = True,
        max_files: int = 100,
    ) -> dict[str, Any]:
        """Find and inspect spatial datasets under an external folder (dev mode).

        Walks a configured external folder for vector/spatial files
        (``.shp``, ``.gpkg``, ``.geojson``, ``.kml``, ``.gml``, ...) and inspects
        each **natively** through QGIS' own :class:`QgsProviderRegistry`
        (``querySublayers``) — the same discovery KADAS uses when you drag a file
        onto the map — reporting per-sublayer geometry type, feature count, CRS
        and field names. No shapefile/GeoJSON is ever parsed in Python and no
        third-party geometry library is used. Reads only; sandboxed to the
        allowed roots.

        Args:
            subpath: Folder to search, relative to a root (or an absolute path
                that resolves inside a root). Empty searches every root.
            recursive: Recurse into subfolders when True.
            max_files: Cap on the number of spatial files inspected.

        Returns:
            ``{"success", "base", "datasets": [{"path", "driver", "sublayers":
            [{"name", "type", "geometry", "feature_count", "crs", "fields"}]}],
            "truncated"}`` or a structured error. When QGIS is unavailable the
            files are still listed with an ``"inspect_error"`` note per dataset.
        """
        bases = allowed if not subpath else None
        if bases is None:
            target, _root = _resolve_within_roots(subpath, allowed)
            if target is None:
                return {
                    "success": False,
                    "error": (
                        f"Path {subpath!r} is outside the allowed external roots."
                    ),
                }
            if not target.is_dir():
                return {"success": False, "error": f"Not a directory: {target}"}
            bases = [target]

        # Collect candidate spatial files across the base folder(s).
        files: list[Path] = []
        truncated = False
        for base in bases:
            globber = base.rglob if recursive else base.glob
            try:
                for item in globber("*"):
                    real = Path(os.path.realpath(item))
                    if not any(_contained_in(real, r) for r in allowed):
                        continue
                    if item.is_file() and item.suffix.lower() in _SPATIAL_EXTS:
                        files.append(item)
                        if len(files) >= max(1, int(max_files)):
                            truncated = True
                            break
            except Exception as exc:
                return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            if truncated:
                break

        datasets = [_inspect_spatial_file(path) for path in files]
        return {
            "success": True,
            "base": str(bases[0]) if len(bases) == 1 else [str(b) for b in bases],
            "count": len(datasets),
            "datasets": datasets,
            "truncated": truncated,
        }

    return [
        list_external_roots,
        scan_external_folder,
        read_external_file,
        find_spatial_data,
    ]


__all__ = ["external_files_tools", "resolve_roots"]
