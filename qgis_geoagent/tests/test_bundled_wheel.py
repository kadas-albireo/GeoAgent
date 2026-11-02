"""Tests for the bundled-GeoAgent-wheel path used by client builds.

``build_release.sh`` ships a GeoAgent wheel inside the plugin so a fresh client
install does not depend on a PyPI release of unreleased code. These tests pin
that contract: if the discovery or substitution breaks, a client build silently
installs whatever is on PyPI instead of the code in the zip.
"""

from __future__ import annotations

from open_geoagent import deps_manager


def test_no_bundled_wheel_in_a_source_checkout():
    """A plain checkout has no bundled/ dir, so the PyPI spec must be used."""
    assert deps_manager.bundled_geoagent_wheel() is None
    specs = dict(deps_manager.packages_for_group("Core Providers"))
    assert specs["geoagent"].startswith("GeoAgent[providers]")


def test_bundled_wheel_is_discovered_and_replaces_the_pypi_spec(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    wheel = bundled / "geoagent-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"")
    monkeypatch.setattr(deps_manager, "__file__", str(tmp_path / "deps_manager.py"))

    assert deps_manager.bundled_geoagent_wheel() == str(wheel)

    specs = dict(deps_manager.packages_for_group("Core Providers"))
    # The geoagent entry becomes the local wheel, keeping the providers extra...
    assert specs["geoagent"] == f"{wheel}[providers]"
    # ...and every other dependency is left alone (still fetched from PyPI).
    assert specs["strands"].startswith("strands-agents")
    assert specs["anthropic"].startswith("anthropic")


def test_unrelated_wheels_are_ignored(tmp_path, monkeypatch):
    """Only a GeoAgent wheel should be substituted, not any wheel present."""
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "somethingelse-1.0-py3-none-any.whl").write_bytes(b"")
    monkeypatch.setattr(deps_manager, "__file__", str(tmp_path / "deps_manager.py"))

    assert deps_manager.bundled_geoagent_wheel() is None
