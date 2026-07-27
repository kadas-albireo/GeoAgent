"""Tests for the KADAS terrain/measurement tool surface."""

from __future__ import annotations

import ast
from pathlib import Path

from geoagent.testing import MockQGISIface, MockQGISProject
from geoagent.tools import kadas_terrain
from geoagent.tools.kadas_terrain import kadas_terrain_tools

EXPECTED = {
    "set_heightmap_layer",
    "get_heightmap_layer",
    "compute_hillshade",
    "compute_slope",
    "compute_viewshed",
    "measure_distance_bearing",
    "measure_polygon_area",
}


def _names(tools):
    return {getattr(t, "tool_name", getattr(t, "__name__", "")) for t in tools}


def test_module_has_no_top_level_qgis_or_kadas_import():
    """Only tool *bodies* may import qgis/kadas; module level must stay clean.

    Checked with AST rather than ``"qgis" not in sys.modules``: the plugin test
    suite stubs a ``qgis`` package into ``sys.modules``, so a sys.modules probe
    is order-dependent and passes or fails depending on which suites ran first.
    The AST states the actual invariant and never skips.
    """
    tree = ast.parse(Path(kadas_terrain.__file__).read_text(encoding="utf-8"))
    offenders = []
    for node in tree.body:  # module level only -- nested imports are fine
        if isinstance(node, ast.Import):
            offenders += [
                a.name for a in node.names if a.name.split(".")[0] in {"qgis", "kadas"}
            ]
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in {"qgis", "kadas"}:
                offenders.append(node.module or "")
    assert not offenders, f"top-level QGIS/KADAS imports: {offenders}"


def test_factory_returns_empty_without_a_host():
    assert kadas_terrain_tools() == []


def test_factory_exposes_the_expected_tools():
    tools = kadas_terrain_tools(MockQGISIface(), MockQGISProject())
    assert _names(tools) == EXPECTED


def _by_name(tools):
    return {getattr(t, "tool_name", getattr(t, "__name__", "")): t for t in tools}


def test_raster_producers_are_gated_and_marked_long_running():
    """Whole-DTM passes are slow and write files, so they must be gated."""
    tools = _by_name(kadas_terrain_tools(MockQGISIface(), MockQGISProject()))
    for name in ("compute_hillshade", "compute_slope", "compute_viewshed"):
        meta = tools[name]._geoagent_meta
        assert meta.requires_confirmation, name
        assert meta.long_running, name


def test_read_only_tools_are_not_gated():
    tools = _by_name(kadas_terrain_tools(MockQGISIface(), MockQGISProject()))
    for name in ("get_heightmap_layer", "measure_distance_bearing"):
        meta = tools[name]._geoagent_meta
        assert not meta.requires_confirmation, name
        assert not meta.destructive, name


def test_set_heightmap_layer_rejects_unknown_layer():
    tools = {
        getattr(t, "tool_name", t.__name__): t
        for t in kadas_terrain_tools(MockQGISIface(), MockQGISProject())
    }
    result = tools["set_heightmap_layer"]("no-such-layer")
    assert result["success"] is False
    assert "no-such-layer" in result["error"]
