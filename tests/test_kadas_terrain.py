"""Tests for the KADAS terrain/measurement tool surface."""

from __future__ import annotations

import sys

from geoagent.testing import MockQGISIface, MockQGISProject
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


def test_module_is_import_safe_without_qgis():
    """The module must import without pulling in qgis (CI has no QGIS)."""
    assert "geoagent.tools.kadas_terrain" in sys.modules
    assert "qgis" not in sys.modules


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
