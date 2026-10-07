"""Tests for the KADAS-configured data-source tools.

The tool bodies drive live KADAS objects (catalog panel, locator filters) and are
verified inside KADAS; these cover the QGIS-free helpers and the ``for_kadas``
wiring.
"""

from __future__ import annotations

from geoagent import for_kadas
from geoagent.testing import MockQGISIface, MockQGISProject
from geoagent.tools import kadas_sources as ks


class _MockModel:
    stateful = False

    def converse(self, *args, **kwargs):  # pragma: no cover - not exercised
        raise NotImplementedError


def test_endpoint_kind_hides_urls_but_keeps_locality():
    assert ks.endpoint_kind("") == "not configured"
    assert ks.endpoint_kind("http://localhost:5000/SearchServerCh") == "local service"
    assert ks.endpoint_kind("http://127.0.0.1:8080/x") == "local service"
    assert ks.endpoint_kind("catalog/{lang}.json") == "local file"
    assert ks.endpoint_kind("C:/kadas/catalog.json") == "local file"
    assert ks.endpoint_kind("file:///opt/catalog.json") == "local file"
    assert (
        ks.endpoint_kind("https://api3.geo.admin.ch/rest/services/api/SearchServer")
        == "remote (api3.geo.admin.ch)"
    )


def test_parse_catalog_config_reads_multiple_providers():
    raw = (
        '"type=geoadmin&url=https://api3.geo.admin.ch/rest/services/ech/CatalogServer'
        ';;type=vbs&url=catalog.json"'
    )
    assert ks.parse_catalog_config(raw) == [
        {"type": "geoadmin", "location": "remote (api3.geo.admin.ch)"},
        {"type": "vbs", "location": "local file"},
    ]
    assert ks.parse_catalog_config("") == []


def test_parse_bool_setting_handles_ini_strings():
    assert ks.parse_bool_setting("true") is True
    assert ks.parse_bool_setting("false") is False
    assert ks.parse_bool_setting(True) is True
    assert ks.parse_bool_setting(None) is False


def test_uri_source_kind():
    assert ks.uri_source_kind("gdal", "/data/dtm.tif") == "local"
    assert ks.uri_source_kind("gdal", "/vsicurl/https://x/dtm.tif") == "remote"
    wms = "crs=EPSG:2056&layers=a&url=https://wms.geo.admin.ch/?SERVICE=WMS"
    assert ks.uri_source_kind("wms", wms) == "remote"
    assert (
        ks.uri_source_kind("wms", "layers=a&url=http://localhost:8080/wms") == "local"
    )


def _entry(title, category):
    return {"title": title, "category": category}


def test_match_catalog_entries_prefers_title_hits_and_needs_all_tokens():
    entries = [
        _entry("National Map 1:1 million", "Base Maps"),
        _entry("SWISSIMAGE Journey through time", "Imagery"),
        _entry("Hydrography swissTLM3D", "Nature > Water"),
        _entry("Water protection areas", "Nature > Water"),
    ]
    assert [e["title"] for e in ks.match_catalog_entries(entries, "swissimage", 5)] == [
        "SWISSIMAGE Journey through time"
    ]
    # Every token must match somewhere; title hits outrank category-only hits.
    water = ks.match_catalog_entries(entries, "water", 5)
    assert [e["title"] for e in water] == [
        "Water protection areas",
        "Hydrography swissTLM3D",
    ]
    assert ks.match_catalog_entries(entries, "tlm hydrography", 5)[0]["title"] == (
        "Hydrography swissTLM3D"
    )
    assert ks.match_catalog_entries(entries, "   ", 5) == []


def test_for_kadas_uses_kadas_sources_instead_of_hardcoded_geoadmin():
    agent = for_kadas(MockQGISIface(), MockQGISProject(), model=_MockModel())
    names = set(agent.strands_agent.tool_names)
    assert {
        "describe_data_sources",
        "search_catalog",
        "load_catalog_layer",
        "search_location",
        "locate_and_zoom",
    } <= names
    assert (
        not {
            "search_geoadmin_catalog",
            "load_geoadmin_layer",
            "get_geoadmin_layer_info",
        }
        & names
    )
