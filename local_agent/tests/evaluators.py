#!/usr/bin/env python3
"""Advisory checks for benchmark results.

**These are triage aids, not verdicts.** They exist so a 15-test × 3-agent sweep can be
skimmed instead of read end-to-end, and so obvious regressions surface fast. They are
deliberately shallow:

- A "pass" means *the mechanical checks did not object*. It does not mean the map is right.
- A "fail" is a prompt to go look at the screenshot, not a conclusion.

The authoritative signal is a human comparing the screenshot and ``raw_output`` against
``eval_criteria.human_check``. Anything subtle (is the circle geodetically 5 km? is the
symbol the right MilX code?) is unreachable from here by design -- encoding it would
produce confident wrong answers, which is worse than no answer.

Import-safe outside QGIS: state probes import ``qgis`` lazily and degrade to "unknown"
when it is absent.
"""

from __future__ import annotations

from typing import Any


class CheckResult:
    """Outcome of the advisory checks for one test."""

    def __init__(self) -> None:
        self.checks: dict[str, Any] = {}
        self.failures: list[str] = []

    def note(self, name: str, passed: bool | None, detail: str = "") -> None:
        """Record one check. ``passed=None`` means 'could not evaluate'."""
        self.checks[name] = {"passed": passed, "detail": detail}
        if passed is False:
            self.failures.append(f"{name}: {detail}" if detail else name)

    @property
    def status(self) -> str:
        """'pass' if nothing objected, else 'fail'. Advisory."""
        return "fail" if self.failures else "pass"


def _called_names(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Return the tool names invoked, in order."""
    return [str(call.get("name", "")) for call in tool_calls]


def check_tool_calls(
    criteria: dict[str, Any], tool_calls: list[dict[str, Any]], result: CheckResult
) -> None:
    """Apply the tool-call expectations in *criteria*."""
    called = _called_names(tool_calls)

    required = criteria.get("tool_calls_include")
    if required:
        missing = [name for name in required if name not in called]
        result.note(
            "tool_calls_include",
            not missing,
            f"missing {missing}; called {called}" if missing else "",
        )

    any_of = criteria.get("tool_calls_include_any")
    if any_of:
        hit = [name for name in any_of if name in called]
        result.note(
            "tool_calls_include_any",
            bool(hit),
            f"none of {any_of}; called {called}" if not hit else "",
        )

    cap = criteria.get("max_tool_calls")
    if cap is not None:
        result.note(
            "max_tool_calls",
            len(called) <= cap,
            f"{len(called)} calls > cap {cap}" if len(called) > cap else "",
        )


def check_answer(criteria: dict[str, Any], answer: str, result: CheckResult) -> None:
    """Apply substring expectations against the agent's prose answer.

    Substring matching is crude: it catches "did the number appear at all" and nothing
    more. A model can pass this by coincidence, which is precisely why it is advisory.
    """
    needles = criteria.get("answer_contains_any")
    if not needles:
        return
    lowered = (answer or "").lower()
    hit = [n for n in needles if str(n).lower() in lowered]
    result.note(
        "answer_contains_any",
        bool(hit),
        f"none of {needles} in answer" if not hit else f"matched {hit}",
    )


def _canvas_extent_contains(
    iface: Any, lonlat: list[float], tolerance_m: float
) -> tuple[bool | None, str]:
    """True when the canvas extent contains *lonlat* (buffered by *tolerance_m*).

    Transforms WGS84 -> the canvas CRS (LV95 in KADAS), because comparing degrees against
    a projected extent is the exact mistake this whole benchmark suite is watching for.
    """
    try:
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsPointXY,
            QgsProject,
        )
    except ImportError:
        return None, "qgis unavailable"

    try:
        canvas = iface.mapCanvas()
        extent = canvas.extent()
        dest_crs = canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"), dest_crs, QgsProject.instance()
        )
        point = transform.transform(QgsPointXY(lonlat[0], lonlat[1]))
        buffered = extent.buffered(tolerance_m) if tolerance_m else extent
        inside = buffered.contains(point)
        return (
            inside,
            f"point {point.x():.0f},{point.y():.0f} vs extent {extent.toString(0)}",
        )
    except Exception as exc:
        return None, f"probe error: {exc}"


def check_state(
    criteria: dict[str, Any],
    iface: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    result: CheckResult,
) -> None:
    """Apply post-state probes comparing project state before/after the turn."""
    for probe in criteria.get("state", []):
        kind = probe.get("probe")

        if kind == "layer_count_increased":
            need = probe.get("by_at_least", 1)
            delta = after.get("layer_count", 0) - before.get("layer_count", 0)
            result.note(
                "layer_count_increased",
                delta >= need,
                f"delta {delta} < {need}" if delta < need else f"+{delta} layers",
            )

        elif kind == "layer_count_equals":
            want = probe.get("value", 0)
            got = after.get("layer_count", -1)
            result.note("layer_count_equals", got == want, f"got {got}, want {want}")

        elif kind == "canvas_extent_contains":
            passed, detail = _canvas_extent_contains(
                iface, probe.get("lonlat", [0, 0]), probe.get("tolerance_m", 0)
            )
            result.note("canvas_extent_contains", passed, detail)

        else:
            result.note(f"unknown_probe:{kind}", None, "no such probe")


def project_state() -> dict[str, Any]:
    """Snapshot the bits of project state the probes compare.

    Reads ``QgsProject.instance()`` rather than an iface, since that is the same project
    the tools mutate. Returns an empty-ish dict outside QGIS so the runner stays
    importable.
    """
    try:
        from qgis.core import QgsProject
    except ImportError:
        return {"layer_count": 0, "layers": []}
    try:
        layers = list(QgsProject.instance().mapLayers().values())
        return {"layer_count": len(layers), "layers": [lyr.name() for lyr in layers]}
    except Exception:
        return {"layer_count": 0, "layers": []}


def evaluate(
    criteria: dict[str, Any],
    *,
    answer: str,
    tool_calls: list[dict[str, Any]],
    iface: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> CheckResult:
    """Run every applicable advisory check and return the aggregate.

    Returns:
        A :class:`CheckResult` whose ``status`` is a hint. Read ``human_check`` in the
        benchmark before believing it.
    """
    result = CheckResult()
    check_tool_calls(criteria, tool_calls, result)
    check_answer(criteria, answer, result)
    if iface is not None:
        check_state(criteria, iface, before or {}, after or {}, result)
    return result
