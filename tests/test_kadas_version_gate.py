"""Tests for the KADAS annotation-API detection used by the plugin gate.

GeoAgent supports both KADAS annotation generations and picks the right one at
runtime (see ``geoagent.tools.kadas``):

* **Kadas 3** (post 2026-06-23, ``kadas-albireo2`` master): stock
  ``QgsAnnotationLayer`` + ``Kadas*AnnotationItem``, keyed by the presence of
  ``KadasAnnotationLayerHelpers``.
* **Kadas 2** (the released 2.x line up to ``v2.3.20``, Qt5): the older
  ``KadasItemLayer`` + ``mapitems/`` API, keyed by the presence of
  ``KadasItemLayer``.

The plugin loads whenever *either* API is present, so
``has_kadas_annotation_support`` must be true for both generations and false
only when neither class exists (i.e. not a real KADAS).

The probes are loaded from source rather than imported: ``_shared`` lives in the
plugin package, which is not importable without KADAS on the path.
"""

from __future__ import annotations

import ast
import importlib
import sys
import types
from pathlib import Path

import pytest

_SHARED = (
    Path(__file__).resolve().parents[1]
    / "kadas_geoagent"
    / "kadas_geoagent"
    / "_shared.py"
)

_PROBE_FUNCS = (
    "_kadasgui_module",
    "has_new_annotation_api",
    "has_legacy_annotation_api",
    "has_kadas_annotation_support",
)


def _load_probes() -> dict:
    """Return the annotation-detection helpers extracted from ``_shared.py``."""
    tree = ast.parse(_SHARED.read_text(encoding="utf-8"))
    keep = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        or (isinstance(node, ast.FunctionDef) and node.name in _PROBE_FUNCS)
    ]
    namespace: dict = {"importlib": importlib}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "<probe>", "exec"), namespace)
    return namespace


@pytest.fixture
def probes():
    return _load_probes()


@pytest.fixture
def fake_kadasgui(monkeypatch):
    """Install a stand-in ``kadas.kadasgui`` and yield it for mutation."""

    def _install(**attrs):
        kadas = types.ModuleType("kadas")
        kadasgui = types.ModuleType("kadas.kadasgui")
        for name, value in attrs.items():
            setattr(kadasgui, name, value)
        kadas.kadasgui = kadasgui
        monkeypatch.setitem(sys.modules, "kadas", kadas)
        monkeypatch.setitem(sys.modules, "kadas.kadasgui", kadasgui)
        return kadasgui

    return _install


def test_absent_kadas_is_unsupported(probes, monkeypatch):
    """Plain CI / QGIS has no kadas package at all."""
    monkeypatch.setitem(sys.modules, "kadas", None)
    assert probes["has_kadas_annotation_support"]() is False
    assert probes["has_new_annotation_api"]() is False
    assert probes["has_legacy_annotation_api"]() is False


def test_kadas_2x_is_supported_via_legacy_api(probes, fake_kadasgui):
    """v2.3.20 exposes KadasItemLayer + the mapitems/ classes, not the new API."""
    fake_kadasgui(KadasItemLayer=object, KadasCircleItem=object, KadasTextItem=object)
    assert probes["has_kadas_annotation_support"]() is True
    assert probes["has_legacy_annotation_api"]() is True
    assert probes["has_new_annotation_api"]() is False


def test_kadas_3_is_supported_via_new_api(probes, fake_kadasgui):
    """Post-refactor builds expose KadasAnnotationLayerHelpers."""
    fake_kadasgui(
        KadasAnnotationLayerHelpers=object,
        KadasCircleAnnotationItem=object,
    )
    assert probes["has_kadas_annotation_support"]() is True
    assert probes["has_new_annotation_api"]() is True


def test_build_with_neither_api_is_unsupported(probes, fake_kadasgui):
    """A kadasgui module exposing neither annotation class is not a real KADAS."""
    fake_kadasgui(SomeUnrelatedClass=object)
    assert probes["has_kadas_annotation_support"]() is False
    assert probes["has_new_annotation_api"]() is False
    assert probes["has_legacy_annotation_api"]() is False
