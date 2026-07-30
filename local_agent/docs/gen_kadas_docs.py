#!/usr/bin/env python3
"""Generate KADAS doc packs from the SIP bindings.

KADAS has no published Python API reference, and its C++ docs describe classes that are
**not necessarily bound to Python**. Writing these packs by hand from memory is how you
end up teaching a model an API that does not exist -- a mistake already made once in this
project (four invented signatures: ``x``/``y`` for ``lon``/``lat``, ``bodid`` for
``bod_id``). The `.sip.in` files are the ground truth for what Python can actually call,
so generate from them.

Reads ``kadas-albireo2/python/*/auto_generated/**/*.sip.in`` and emits one Markdown pack
per topic group into this directory, each with ``triggers:`` front matter so
``skills/selector.py`` can load it into the prompt's volatile tail on keyword match.

Deliberately conservative about what it claims:

- Only classes that appear in a ``.sip.in`` are emitted. If a class is not there, Python
  cannot call it, and the pack says so rather than staying silent.
- Signatures are copied verbatim from the bindings, never paraphrased.
- ``%Docstring`` blocks are the authors' own words; they are quoted, not rewritten.

Usage::

    python local_agent/docs/gen_kadas_docs.py                # write packs
    python local_agent/docs/gen_kadas_docs.py --stats        # sizes only
    python local_agent/docs/gen_kadas_docs.py --class KadasMilxAnnotationItem
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

KADAS_ROOT = Path("/home/aloha/OPENGIS/kadas-albireo2")
SIP_GLOB = "python/*/auto_generated/**/*.sip.in"

# Write straight into the shipped package. The packs are *runtime* data read by
# geoagent.core.context_docs, and the KADAS repo is not present on a user's machine, so
# they must be generated here and committed. Keeping a second copy under local_agent/
# would just be a source of drift.
OUT_DIR = Path(__file__).resolve().parents[2] / "geoagent" / "docs"

# Topic groups: directory fragment -> (pack slug, description, trigger keywords).
# Triggers are what selector.py matches a user prompt against.
GROUPS: dict[str, tuple[str, str, list[str]]] = {
    # The annotation surface is ~9.4k tokens as one pack -- too big to ever inject
    # alongside the ~12.7k tool prefix, so it was silently never retrieved. Split three
    # ways along a real seam rather than by size:
    #
    #   items       what you CREATE and configure (setPoints, setMssString). Agent-facing.
    #   controllers interactive click-to-draw machinery. Drives a human, not an agent;
    #               ~6k of the original pack and almost never what a tool call needs.
    #   layers      registry / layer helpers / project integration / style editor.
    "annotation-items": (
        "kadas-annotation-items",
        "KADAS annotation items: the objects you create (marker, circle, line, MilX)",
        [
            "annotation",
            "marker",
            "pin",
            "circle",
            "rectangle",
            "polygon",
            "line",
            "redline",
            "draw",
            "symbol",
            "gpx",
            "waypoint",
            "picture",
            "text",
            "label",
        ],
    ),
    "annotation-controllers": (
        "kadas-annotation-controllers",
        "KADAS annotation controllers: interactive click-to-draw editing",
        ["controller", "interactive", "click to draw", "edit annotation", "digitize"],
    ),
    "annotation-layers": (
        "kadas-annotation-layers",
        "KADAS annotation layers: registry, helpers, project integration, styling",
        [
            "annotation layer",
            "layer registry",
            "style editor",
            "project integration",
            "layer helpers",
        ],
    ),
    "milx": (
        "kadas-milx",
        "MilX/MSS military symbology: what is and is not bound to Python",
        [
            "milx",
            "mss",
            "military",
            "symbol",
            "tactical",
            "app-6",
            "sidc",
            "nato",
            "infantry",
            "unit",
        ],
    ),
    "maptools": (
        "kadas-maptools",
        "KADAS map tools (interactive canvas tools)",
        ["maptool", "map tool", "click", "digitize", "measure", "interactive", "pick"],
    ),
    "search": (
        "kadas-search",
        "KADAS search providers and location search",
        ["search", "locate", "find", "place", "geocode", "provider"],
    ),
    "catalog": (
        "kadas-catalog",
        "KADAS layer catalog browser",
        ["catalog", "browser", "layer tree", "add layer"],
    ),
}

# Classes SIP explicitly does NOT bind, but which a reader might expect. Recorded so the
# packs can state the gap; a model that "knows" about KadasMilxClient from the C++ docs
# will otherwise hallucinate calls into it.
KNOWN_UNBOUND = {
    "KadasMilxClient": (
        "Lives in kadas/gui/milx/kadasmilxclient.h and owns the symbol lookup "
        "(getSymbolMetadata, getMilitaryName, validateSymbolXml, init). It is NOT in any "
        ".sip.in, so **Python cannot call it**. This is why a symbol cannot be resolved "
        "from a name/ID in Python: the item can be built, but the MSS string it needs "
        "cannot be looked up. Binding this class would unblock a real MilX tool."
    ),
}


@dataclass
class Method:
    """One bound method signature plus its docstring."""

    signature: str
    doc: str = ""
    static: bool = False


@dataclass
class SipClass:
    """A class exposed to Python via SIP."""

    name: str
    base: str = ""
    doc: str = ""
    methods: list[Method] = field(default_factory=list)
    source: str = ""
    group: str = ""


def _clean_doc(raw: str) -> str:
    """Normalize a %Docstring body to a single tidy paragraph block."""
    text = re.sub(r"\\c\s+", "", raw)
    text = re.sub(r":py:func:`~?([^`]+)`", r"``\1``", text)
    text = text.replace("``", "`")
    lines = [line.strip() for line in text.strip().splitlines()]
    return " ".join(line for line in lines if line).strip()


# Virtual overrides inherited from QgsAnnotationItem / QgsMapTool etc. They appear on
# nearly every class, are never what an agent needs to call, and would trebled the pack
# size while burying the KADAS-specific API that matters.
_BOILERPLATE = frozenset(
    {
        "render",
        "writeXml",
        "readXml",
        "clone",
        "type",
        "boundingBox",
        "flags",
        "boundingBoxAtDevice",
        "copyCommonProperties",
        "setCommonProperties",
        "staticMetaObject",
        "icon",
        "keyPressEvent",
        "keyReleaseEvent",
    }
)


def _method_name(signature: str) -> str:
    """Return the bare method name from a C++ signature."""
    match = re.search(r"(\w+)\s*\(", signature)
    return match.group(1) if match else ""


def parse_sip(path: Path) -> list[SipClass]:
    """Extract the classes and public methods a ``.sip.in`` exposes.

    Hand-rolled rather than a real SIP parser: we only need class/base/method signatures
    and %Docstring blocks, and the generated files are highly regular. Anything not
    recognized is skipped rather than guessed at.

    **Docstring placement:** SIP puts ``%Docstring`` *after* the thing it documents, so a
    finished block attaches to the **last method parsed**, not the next one. The only
    exception is the class docstring, which follows ``class X {`` before any method. An
    earlier version of this attached each block to the following method and silently
    shifted every doc by one -- misattributed docs are worse than no docs, since a model
    cannot tell they are wrong.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    classes: list[SipClass] = []
    current: SipClass | None = None
    in_doc = False
    doc_buffer: list[str] = []
    in_private = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("%Docstring"):
            in_doc, doc_buffer = True, []
            continue
        if in_doc:
            if stripped == "%End":
                in_doc = False
                doc = _clean_doc("\n".join(doc_buffer))
                if current is None or not doc:
                    continue
                if current.methods:
                    current.methods[-1].doc = doc
                elif not current.doc:
                    current.doc = doc
            else:
                doc_buffer.append(line)
            continue

        # Skip SIP directive blocks that contain no API surface.
        if stripped.startswith(("%TypeHeaderCode", "%ModuleCode", "%ConvertTo")):
            continue

        match = re.match(r"^class\s+(\w+)\s*(?::\s*([\w\s,]+))?", stripped)
        if match:
            current = SipClass(
                name=match.group(1),
                base=(match.group(2) or "").strip(),
                source=str(path.relative_to(KADAS_ROOT)),
            )
            classes.append(current)
            in_private = False
            continue

        if current is None:
            continue
        if stripped.startswith("private:"):
            in_private = True
            continue
        if stripped.startswith(("public:", "signals:", "public slots:")):
            in_private = False
            continue
        if in_private:
            continue

        # A bound method: ends in ');' and is not a macro or comment.
        if (
            stripped.endswith(";")
            and "(" in stripped
            and not stripped.startswith(("%", "//", "*", "#"))
        ):
            signature = re.sub(r"\s*/[^/]*/\s*;?$", "", stripped).rstrip(";").strip()
            if not signature or signature.startswith("enum"):
                continue
            name = _method_name(signature)
            # Drop inherited Qgs* plumbing; keep the KADAS-specific surface.
            if name in _BOILERPLATE or name == current.name:
                continue
            current.methods.append(
                Method(signature=signature, static=signature.startswith("static"))
            )

    return classes


def _group_for(cls_name: str, path: Path) -> str:
    """Return the topic group for one class.

    Grouped per **class**, not per file, because items and their controllers are declared
    in the same directory (and sometimes need to land in different packs). Precedence:

    1. **MilX by class name.** ``KadasMilxAnnotationItem`` lives under
       ``annotationitems/`` but is the whole Python-visible MilX API. Grouping it by
       directory buried it in the oversized annotations pack while the ``milx`` pack held
       only a GUI widget -- so a "milx" query retrieved the one pack lacking the MilX API.
    2. **Annotation sub-split** by class-name suffix (item vs controller vs layer infra).
    3. Directory, then ``core``.
    """
    name = cls_name.lower()

    if "milx" in name:
        return "milx"

    if "annotation" in name or "/annotationitems/" in str(path):
        if "controller" in name:
            return "annotation-controllers"
        if name.endswith("item") or "itemcontext" in name:
            return "annotation-items"
        return "annotation-layers"

    filename = path.name.lower()
    for key in ("maptools", "search", "catalog"):
        if key in filename or f"/{key}/" in str(path):
            return key
    return "core"


def collect() -> dict[str, list[SipClass]]:
    """Parse every SIP file, grouping each class by topic."""
    grouped: dict[str, list[SipClass]] = {}
    for path in sorted(KADAS_ROOT.glob(SIP_GLOB)):
        for cls in parse_sip(path):
            cls.group = _group_for(cls.name, path)
            grouped.setdefault(cls.group, []).append(cls)
    return grouped


def render_pack(group: str, classes: list[SipClass]) -> str:
    """Render one Markdown doc pack."""
    slug, description, triggers = GROUPS.get(
        group,
        (f"kadas-{group}", f"KADAS {group} API", [group]),
    )

    out = [
        "---",
        f"name: {slug}",
        f"description: {description}",
        f"triggers: [{', '.join(triggers)}]",
        "generated_from: kadas-albireo2 SIP bindings",
        "---",
        "",
        f"# KADAS: {description}",
        "",
        "**Generated from the SIP bindings — these are the real signatures Python can "
        "call.** Do not infer methods that are not listed here; if a class or method is "
        "absent, it is not bound and calling it raises AttributeError.",
        "",
    ]

    for cls in sorted(classes, key=lambda c: c.name):
        if not cls.methods and not cls.doc:
            continue
        heading = f"## {cls.name}"
        if cls.base:
            heading += f" ({cls.base})"
        out.append(heading)
        out.append("")
        if cls.doc:
            out += [cls.doc, ""]

        statics = [m for m in cls.methods if m.static]
        instance = [m for m in cls.methods if not m.static]

        for label, methods in (("Static", statics), ("Methods", instance)):
            if not methods:
                continue
            out.append(f"**{label}:**")
            out.append("")
            out.append("```cpp")
            for method in methods:
                out.append(method.signature + ";")
            out.append("```")
            out.append("")
            documented = [m for m in methods if m.doc]
            if documented:
                for method in documented:
                    name = re.search(r"(\w+)\s*\(", method.signature)
                    out.append(f"- `{name.group(1) if name else '?'}` — {method.doc}")
                out.append("")

        out.append(f"<sub>source: `{cls.source}`</sub>")
        out.append("")

    unbound = {
        name: reason
        for name, reason in KNOWN_UNBOUND.items()
        if group == "milx" or name.lower().find(group) >= 0
    }
    if unbound:
        out += ["## NOT available from Python", ""]
        for name, reason in unbound.items():
            out += [f"### {name}", "", reason, ""]

    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stats", action="store_true", help="Show sizes, write nothing"
    )
    parser.add_argument("--class", dest="klass", help="Dump one class and exit")
    args = parser.parse_args(argv)

    if not KADAS_ROOT.exists():
        print(f"error: KADAS repo not found at {KADAS_ROOT}")
        return 1

    grouped = collect()

    if args.klass:
        for classes in grouped.values():
            for cls in classes:
                if cls.name == args.klass:
                    print(f"{cls.name} : {cls.base}   [{cls.source}]")
                    print(f"  {cls.doc}\n")
                    for method in cls.methods:
                        mark = "S" if method.static else " "
                        print(f"  {mark} {method.signature}")
                        if method.doc:
                            print(f"      -> {method.doc[:100]}")
                    return 0
        print(f"'{args.klass}' is not bound to Python (not found in any .sip.in)")
        return 1

    try:
        import tiktoken

        encode = tiktoken.get_encoding("cl100k_base").encode
    except ImportError:

        def encode(text: str) -> list[int]:  # type: ignore[misc]
            return [0] * (len(text) // 4)

    total = 0
    for group, classes in sorted(grouped.items()):
        if group not in GROUPS:
            continue
        content = render_pack(group, classes)
        tokens = len(encode(content))
        total += tokens
        slug = GROUPS[group][0]
        path = OUT_DIR / f"{slug}.md"
        if not args.stats:
            path.write_text(content, encoding="utf-8")
        print(f"{slug:22s} {len(classes):3d} classes  ~{tokens:6,d} tok  {path.name}")
    print(f"{'TOTAL':22s} {'':3s}           ~{total:6,d} tok")
    if not args.stats:
        print(f"\nwrote packs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
