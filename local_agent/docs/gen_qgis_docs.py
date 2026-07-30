#!/usr/bin/env python3
"""Generate PyQGIS doc packs for the documancer, from the installed QGIS Python API.

The documancer (``geoagent.core.context_docs``) injects the *slice* of an API a prompt is
about, so the model writes ``run_pyqgis_script`` code against real signatures instead of
half-remembered ones. The KADAS packs are generated from SIP bindings by
``gen_kadas_docs.py``; this is the QGIS/PyQGIS counterpart.

**Signatures are read from the live bindings, never invented.** For each curated class it
introspects the actual ``qgis.core``/``qgis.gui``/``qgis.analysis`` objects: real method
names, ``inspect.signature`` where the wrapper exposes it, and the first line of each
``__doc__`` (the SIP-generated signature line) otherwise. A method that cannot be
introspected is simply omitted — the pack never claims an API it did not observe.

Run it **inside QGIS** (its Python has ``qgis``), e.g. the QGIS/KADAS Python console::

    exec(open("/home/aloha/OPENGIS/plugins/qgis-plugins/GeoAgent/local_agent/docs/gen_qgis_docs.py").read())

or headless against a QGIS-enabled interpreter::

    python local_agent/docs/gen_qgis_docs.py            # write packs
    python local_agent/docs/gen_qgis_docs.py --stats    # sizes only, no write

Packs are written into the shipped ``geoagent/docs/`` dir as ``qgis-<topic>.md`` with
``triggers:`` front matter, so ``context_docs`` loads and matches them with no further
wiring. Toggle injection per prompt with GeoAgent Settings -> "Inject API docs".
"""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path

# Written straight into the shipped package: the packs are runtime data read by
# geoagent.core.context_docs, and QGIS is not present on every machine that ships them.
OUT_DIR = Path(__file__).resolve().parents[2] / "geoagent" / "docs"

# Curated topic packs. Keep each pack small (documancer principle: inject a slice, not the
# world). class path -> resolved at runtime from the qgis modules. Triggers are the
# keywords context_docs matches against the prompt.
TOPICS: dict[str, dict] = {
    "qgis-project": {
        "triggers": ["project", "layer registry", "map layers", "crs of project", "instance"],
        "classes": ["qgis.core.QgsProject", "qgis.core.QgsMapLayer",
                    "qgis.core.QgsLayerTreeGroup", "qgis.core.QgsLayerTreeLayer"],
    },
    "qgis-vector": {
        "triggers": ["vector", "feature", "attribute", "field", "geometry", "editing",
                     "add feature", "expression"],
        "classes": ["qgis.core.QgsVectorLayer", "qgis.core.QgsFeature",
                    "qgis.core.QgsField", "qgis.core.QgsFields",
                    "qgis.core.QgsVectorFileWriter", "qgis.core.QgsFeatureRequest"],
    },
    "qgis-raster": {
        "triggers": ["raster", "band", "pixel", "dem", "dtm", "hillshade", "resample",
                     "raster value"],
        "classes": ["qgis.core.QgsRasterLayer", "qgis.core.QgsRasterDataProvider",
                    "qgis.core.QgsRasterBandStats"],
    },
    "qgis-geometry": {
        "triggers": ["geometry", "buffer", "intersection", "distance", "area", "centroid",
                     "point", "polygon", "wkt"],
        "classes": ["qgis.core.QgsGeometry", "qgis.core.QgsPointXY",
                    "qgis.core.QgsRectangle", "qgis.core.QgsGeometryUtils"],
    },
    "qgis-crs": {
        "triggers": ["crs", "coordinate", "projection", "transform", "epsg", "reproject",
                     "lv95", "wgs84"],
        "classes": ["qgis.core.QgsCoordinateReferenceSystem",
                    "qgis.core.QgsCoordinateTransform", "qgis.core.QgsDistanceArea"],
    },
    "qgis-processing": {
        "triggers": ["processing", "algorithm", "run algorithm", "geoprocessing",
                     "buffer tool", "clip", "zonal"],
        "classes": ["qgis.core.QgsApplication", "qgis.core.QgsProcessing",
                    "qgis.core.QgsProcessingFeedback"],
    },
}

# Cap methods per class so a pack stays a slice, not a dump. Highest-value first is not
# knowable generically, so it is a simple alphabetical cap with the count reported.
MAX_METHODS_PER_CLASS = 40


def _resolve(path: str):
    module_name, _, attr = path.rpartition(".")
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _signature(obj, name: str, member) -> str:
    """Best available signature string for *member*: inspect first, else __doc__ line."""
    try:
        return f"{name}{inspect.signature(member)}"
    except (TypeError, ValueError):
        pass
    doc = inspect.getdoc(member) or ""
    first = doc.splitlines()[0].strip() if doc else ""
    # SIP docstrings usually start with the signature, e.g. "name(self, ...) -> ...".
    if first.startswith(name) or "(" in first:
        return first
    return f"{name}(...)"


def _class_markdown(path: str) -> tuple[str, int]:
    """Return (markdown, method_count) for one class, or ('', 0) if unresolved."""
    try:
        cls = _resolve(path)
    except Exception:
        return "", 0
    cls_doc = (inspect.getdoc(cls) or "").splitlines()
    summary = cls_doc[0].strip() if cls_doc else ""
    lines = [f"### {path}", ""]
    if summary:
        lines += [summary, ""]

    names = sorted(
        n for n in dir(cls)
        if not n.startswith("_") and callable(getattr(cls, n, None))
    )
    shown = names[:MAX_METHODS_PER_CLASS]
    for n in shown:
        try:
            member = getattr(cls, n)
        except Exception:
            continue
        sig = _signature(cls, n, member)
        doc = inspect.getdoc(member) or ""
        first = doc.splitlines()[0].strip() if doc else ""
        note = f" — {first}" if first and first != sig else ""
        lines.append(f"- `{sig}`{note}")
    if len(names) > len(shown):
        lines.append(f"- … {len(names) - len(shown)} more methods (introspect in console).")
    lines.append("")
    return "\n".join(lines), len(shown)


def build_pack(topic: str, spec: dict) -> tuple[str, int]:
    triggers = ", ".join(spec["triggers"])
    header = (
        "---\n"
        f"name: qgis-{topic.split('-', 1)[-1]}\n"
        f"description: PyQGIS API reference ({topic}) — real signatures from the installed QGIS.\n"
        f"triggers: [{triggers}]\n"
        "---\n\n"
        f"# PyQGIS API: {topic}\n\n"
        "Real signatures introspected from this machine's QGIS. Use them verbatim in "
        "`run_pyqgis_script`; do not invent methods not listed here.\n\n"
    )
    body_parts = []
    total = 0
    for path in spec["classes"]:
        md, count = _class_markdown(path)
        if md:
            body_parts.append(md)
            total += count
    return header + "\n".join(body_parts), total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", action="store_true", help="report sizes; do not write")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)

    try:
        import qgis.core  # noqa: F401
    except Exception as exc:
        print(f"error: qgis not importable ({exc}). Run this inside QGIS/KADAS.")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    for topic, spec in TOPICS.items():
        pack, methods = build_pack(topic, spec)
        approx_tokens = len(pack) // 4
        if args.stats:
            print(f"{topic:<18} {methods:>4} methods  ~{approx_tokens} tok")
            continue
        dest = args.out / f"{topic}.md"
        dest.write_text(pack, encoding="utf-8")
        print(f"wrote {dest}  ({methods} methods, ~{approx_tokens} tok)")
    if not args.stats:
        print("\nDone. context_docs will match these on relevant prompts automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
