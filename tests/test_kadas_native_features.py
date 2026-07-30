"""Tests for the KADAS-native additions: OSM, external files, feedback telemetry.

These cover the import-safe, QGIS-free logic (Overpass query building, the
external-folder sandbox, and the "Training AI" feedback logger) plus the tool
wiring exposed through :func:`geoagent.for_kadas`.
"""

from __future__ import annotations

import json

from geoagent import for_kadas
from geoagent.core.telemetry import FeedbackLogger
from geoagent.testing import MockQGISIface, MockQGISProject
from geoagent.tools import capabilities, external_files, osm


class _MockModel:
    """Minimal model double so ``for_kadas`` can build an agent offline."""

    stateful = False

    def converse(self, *args, **kwargs):  # pragma: no cover - not exercised
        raise NotImplementedError


# -- OSM ---------------------------------------------------------------------


def test_build_overpass_query_reorders_bbox_and_and_combines_tags():
    query = osm._build_overpass_query(
        {"amenity": "cafe", "name": "X"}, (7.0, 46.0, 7.1, 46.2), 50
    )
    # Overpass wants (south, west, north, east).
    assert "(46.0,7.0,46.2,7.1)" in query
    assert '["amenity"="cafe"]' in query and '["name"="X"]' in query
    assert query.count("(46.0,7.0,46.2,7.1)") == 3  # node/way/relation
    assert "out geom 50;" in query


def test_element_geometry_classifies_point_line_polygon():
    node = {"type": "node", "lon": 7.0, "lat": 46.0}
    assert osm._element_geometry(node) == ("point", (7.0, 46.0))

    way = {
        "type": "way",
        "geometry": [{"lon": 7.0, "lat": 46.0}, {"lon": 7.1, "lat": 46.1}],
        "tags": {"highway": "primary"},
    }
    kind, coords = osm._element_geometry(way)
    assert kind == "line" and len(coords) == 2

    building = {
        "type": "way",
        "geometry": [
            {"lon": 7.0, "lat": 46.0},
            {"lon": 7.1, "lat": 46.0},
            {"lon": 7.1, "lat": 46.1},
            {"lon": 7.0, "lat": 46.0},
        ],
        "tags": {"building": "yes"},
    }
    assert osm._element_geometry(building)[0] == "polygon"


def test_osm_tools_empty_without_iface():
    assert osm.osm_tools(None) == []


# -- External files sandbox --------------------------------------------------


def _tool_map(tools):
    return {t.tool_name: t for t in tools}


def test_external_files_disabled_without_roots(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOAGENT_EXTERNAL_ROOTS", raising=False)
    assert external_files.external_files_tools([]) == []


def test_external_files_scan_read_and_traversal_guard(tmp_path):
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.tif").write_text("x", encoding="utf-8")

    tools = _tool_map(external_files.external_files_tools([str(tmp_path)]))

    roots = tools["list_external_roots"]()
    assert roots["success"] and str(tmp_path) in roots["roots"][0]

    scan = tools["scan_external_folder"](pattern="*.tif", recursive=True)
    assert scan["success"]
    assert any(e["name"] == "b.tif" for e in scan["entries"])

    read = tools["read_external_file"]("a.txt")
    assert read["success"] and read["content"] == "hello world"

    escaped = tools["read_external_file"]("../../../etc/passwd")
    assert not escaped["success"] and "outside" in escaped["error"]


def test_external_roots_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOAGENT_EXTERNAL_ROOTS", str(tmp_path))
    roots = external_files.resolve_roots()
    assert roots and str(roots[0]) == str(tmp_path.resolve())


def test_find_spatial_data_discovers_files(tmp_path):
    # A spatial file (found) and a plain text file (ignored).
    (tmp_path / "roads.geojson").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")

    tools = _tool_map(external_files.external_files_tools([str(tmp_path)]))
    assert "find_spatial_data" in tools

    result = tools["find_spatial_data"](recursive=True)
    assert result["success"]
    found = {d["name"] for d in result["datasets"]}
    assert "roads.geojson" in found
    assert "notes.txt" not in found


# -- Capabilities: log querying ----------------------------------------------


def test_query_agent_logs_filters_by_kind_and_substring(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOAGENT_LOG_DIR", str(tmp_path))
    (tmp_path / "agent_execution.log").write_text(
        "\n".join(
            [
                json.dumps({"kind": "tool_call", "time": 1, "name": "add_map_marker"}),
                json.dumps({"kind": "error", "time": 2, "message": "boom happened"}),
                json.dumps(
                    {"kind": "tool_call", "time": 3, "name": "get_elevation_at"}
                ),
            ]
        ),
        encoding="utf-8",
    )

    tools = {t.tool_name: t for t in capabilities.capability_tools(MockQGISIface())}
    assert "query_agent_logs" in tools

    errs = tools["query_agent_logs"](kind="error")
    assert errs["success"] and errs["count"] == 1
    assert errs["entries"][0]["message"] == "boom happened"

    hits = tools["query_agent_logs"](kind="all", contains="elevation")
    assert hits["count"] == 1 and hits["entries"][0]["name"] == "get_elevation_at"


def test_capability_tools_empty_without_iface():
    assert capabilities.capability_tools(None) == []


# -- Feedback telemetry ------------------------------------------------------


def test_feedback_logger_writes_jsonl_and_normalizes_status(tmp_path):
    path = tmp_path / "fb.log"
    logger = FeedbackLogger(log_path=path)

    event = logger.record_feedback(
        status="Success", feedback="good", question="q", answer="a", extra=1
    )
    assert event["status"] == "success"
    assert "timestamp" in event and event["kind"] == "feedback"

    logger.record_feedback(status="bogus", feedback="", question="", answer="")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["status"] == "unclassified"


def test_feedback_status_normalization():
    assert FeedbackLogger.normalize_status("FAILURE") == "failure"
    assert FeedbackLogger.normalize_status(None) == "unclassified"


# -- Wiring ------------------------------------------------------------------


def test_for_kadas_exposes_native_tools(tmp_path):
    agent = for_kadas(
        MockQGISIface(),
        MockQGISProject(),
        model=_MockModel(),
        external_roots=[str(tmp_path)],
    )
    names = set(agent.strands_agent.tool_names)
    # OSM + coordinate/elevation/LOS wrappers + external-file surface.
    assert {"add_osm_basemap", "query_osm_features"} <= names
    assert {"convert_coordinates", "get_elevation_at", "check_line_of_sight"} <= names
    assert {"scan_external_folder", "read_external_file", "find_spatial_data"} <= names
    # Capability/plugin/algorithm discovery + native GPKG round-trip + logs.
    assert {
        "list_qgis_capabilities",
        "list_processing_algorithms",
        "describe_processing_algorithm",
        "list_plugins",
        "describe_plugin",
        "export_layer",
        "export_gpkg",
        "import_gpkg",
        "query_agent_logs",
    } <= names
    # Native KADAS command bridge (findAction-based).
    assert {"list_kadas_actions", "trigger_kadas_action"} <= names
    # Headless project primitives (no run_pyqgis_script needed).
    assert {"new_project", "open_project", "save_project"} <= names
