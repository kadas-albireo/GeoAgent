"""Tests for the KADAS version gate.

GeoAgent's annotation surface targets the QgsAnnotationLayer-based API added by
kadas-albireo2 commit 78efe485 ("Annotation refactoring", 2026-06-23). No tagged
release contains it: v2.3.20 still ships KadasItemLayer + mapitems/ on Qt5. On
such a build every annotation tool import-fails at call time, so the plugin must
refuse to load instead of offering tools that cannot work.

The probe is loaded from source rather than imported: ``_shared`` lives in the
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


def _load_probe():
    """Return ``has_kadas_annotation_api`` extracted from ``_shared.py``."""
    tree = ast.parse(_SHARED.read_text(encoding="utf-8"))
    keep = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        or (
            isinstance(node, ast.FunctionDef)
            and node.name == "has_kadas_annotation_api"
        )
    ]
    namespace: dict = {"importlib": importlib}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "<probe>", "exec"), namespace)
    return namespace["has_kadas_annotation_api"]


@pytest.fixture
def probe():
    return _load_probe()


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


def test_absent_kadas_is_unsupported(probe, monkeypatch):
    """Plain CI / QGIS has no kadas package at all."""
    monkeypatch.setitem(sys.modules, "kadas", None)
    assert probe() is False


def test_old_kadas_2x_is_rejected(probe, fake_kadasgui):
    """v2.3.20 exposes KadasItemLayer and the mapitems/ classes, not the new API."""
    fake_kadasgui(KadasItemLayer=object, KadasCircleItem=object, KadasTextItem=object)
    assert probe() is False


def test_new_kadas_is_accepted(probe, fake_kadasgui):
    """Post-refactor builds expose KadasAnnotationLayerHelpers."""
    fake_kadasgui(
        KadasAnnotationLayerHelpers=object,
        KadasCircleAnnotationItem=object,
    )
    assert probe() is True


def test_probe_keys_on_the_class_geoagent_actually_needs(probe, fake_kadasgui):
    """A build with the new items but no helpers is still unsupported.

    kadas.py calls KadasAnnotationLayerHelpers.createLayer to get a layer that
    carries KADAS' parametric-annotation metadata, so that class is the real
    requirement, not just the item subclasses.
    """
    fake_kadasgui(KadasCircleAnnotationItem=object)
    assert probe() is False
