#!/usr/bin/env python3
"""Isolated 'upskill' mechanism for the local agent.

This is a small, self-contained skill manager that lives **entirely inside**
``local_agent/``. It turns recorded GeoAgent telemetry into reusable ``SKILL.md``
files and lets you register/list/bundle them — without ever touching the shipped
``geoagent`` package or the KADAS plugin. Every write is confined to
``local_agent/skills/`` (guarded in :func:`_skill_dir`), so experimenting here
can never leak into production behaviour.

A "skill" is a directory ``skills/<slug>/`` containing a single ``SKILL.md`` with
YAML front matter (``name`` + ``description``) and a Markdown body. This is the
same shape ``fast-agent``/``upskill generate`` expect, so the files are portable.

Commands
--------
``generate``  Distil a ``SKILL.md`` from ``agent_execution.log`` (or a trace):
              counts tool usage across clean turns and embeds a couple of
              successful turns as worked examples.
``register``  Create/overwrite a skill from a title/description (+ optional body
              file) — for hand-authored skills.
``list``      List the skills currently registered in this isolated scope.
``bundle``    Concatenate all skills into ``skills/skills_prompt.md``, ready to
              inject into the GeoAgent system prompt (see DEPLOYMENT.md).
``remove``    Delete a skill directory (isolated scope only).

Standard library only; runs under any Python >= 3.10.

Usage::

    python upskill.py generate --name swiss-layers        # from ~/.kadas log
    python upskill.py generate --name x --from trace.md
    python upskill.py register --name y --description "..." --body-file body.md
    python upskill.py list
    python upskill.py bundle
    python upskill.py remove --name x
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Reuse the trace parser that already lives in this folder.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_from_log import (  # noqa: E402
    _read_events,
    _split_turns,
    _turn_is_clean,
    default_log_path,
)

# The one and only place skills may be written. Kept inside local_agent so the
# upskill scope is physically isolated from the shipped package.
SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def _slugify(name: str) -> str:
    """Return a filesystem-safe kebab-case slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return slug or "skill"


def _skill_dir(slug: str) -> Path:
    """Return ``skills/<slug>`` and assert it stays inside ``SKILLS_DIR``.

    This is the isolation guard: a crafted ``--name`` (``../../geoagent``) can
    never resolve outside the local ``skills/`` directory.
    """
    candidate = (SKILLS_DIR / slug).resolve()
    root = SKILLS_DIR.resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"refusing to write outside {root}: {candidate}")
    return candidate


def _write_skill(slug: str, description: str, body: str) -> Path:
    """Write ``skills/<slug>/SKILL.md`` with front matter + body."""
    directory = _skill_dir(slug)
    directory.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {slug}\ndescription: {description}\n---\n\n"
    path = directory / "SKILL.md"
    path.write_text(front + body.rstrip() + "\n", encoding="utf-8")
    return path


# -- generate ----------------------------------------------------------------


def _tool_frequency(turns: list[list[dict[str, Any]]]) -> Counter:
    """Count tool_call names across the given turns."""
    counter: Counter = Counter()
    for turn in turns:
        for event in turn:
            if event.get("kind") == "tool_call" and event.get("name"):
                counter[event["name"]] += 1
    return counter


def _example_turn(turn: list[dict[str, Any]], max_chars: int = 600) -> str:
    """Render a compact user→tools→answer example from one turn."""
    lines: list[str] = []
    for event in turn:
        kind = event.get("kind")
        if kind == "turn_start":
            task = str(event.get("task", "")).strip().splitlines()
            first = task[0] if task else ""
            lines.append(f"- **User:** {first[:200]}")
        elif kind == "tool_call":
            args = json.dumps(event.get("input"), ensure_ascii=False, default=str)
            lines.append(f"  - `{event.get('name')}` → `{args[:160]}`")
        elif kind == "turn_end":
            answer = str(event.get("answer", "")).strip().splitlines()
            first = answer[0] if answer else ""
            if first:
                lines.append(f"  - **Answer:** {first[:200]}")
    return "\n".join(lines)[:max_chars]


def cmd_generate(args: argparse.Namespace) -> int:
    """Distil a SKILL.md from telemetry (clean turns only).

    DEPRECATED. Telemetry-driven auto-generation produces shallow, repetitive skills
    (a tool-frequency table and placeholder examples — see
    ``skills/kadas-map-ops/SKILL.md`` for what it yields). The maintained approach is to
    hand-author pathways in ``OPERATIONS.md`` and the ``skills/*/SKILL.md`` files, using
    ``trace_from_log.py`` to *read* telemetry rather than compile it. Kept behind
    ``--force`` for one-off exploration only.
    """
    if not getattr(args, "force", False):
        print(
            "upskill generate is DEPRECATED. Auto-distilled skills are shallow and "
            "repetitive.\nAuthor pathways in local_agent/OPERATIONS.md and the "
            "skills/*/SKILL.md files instead.\nUse `python local_agent/trace_from_log.py` "
            "to read telemetry by hand.\nRe-run with --force to override.",
            file=sys.stderr,
        )
        return 2
    log_path: Path = args.log
    if not log_path.exists():
        print(f"error: log not found: {log_path}", file=sys.stderr)
        return 1
    events = _read_events(log_path)
    turns = _split_turns(events)
    clean = [t for t in turns if _turn_is_clean(t)]
    if not clean:
        print("error: no clean turns to learn from", file=sys.stderr)
        return 1

    freq = _tool_frequency(clean)
    top = freq.most_common(12)
    slug = _slugify(args.name)
    description = args.description or (
        f"Learned workflow from {len(clean)} successful GeoAgent turns."
    )

    body_lines = [
        f"# Skill: {slug}",
        "",
        f"Distilled from `{log_path}` ({len(clean)}/{len(turns)} clean turns).",
        "",
        "## Preferred tools (by observed frequency)",
        "",
    ]
    body_lines += [f"- `{name}` — used {count}×" for name, count in top]
    body_lines += ["", "## Worked examples", ""]
    for turn in clean[: args.examples]:
        example = _example_turn(turn)
        if example:
            body_lines += [example, ""]
    body_lines += [
        "## Guidance",
        "",
        "- Prefer the dedicated tools above over hand-written PyQGIS.",
        "- Follow the example call order for similar requests.",
    ]

    path = _write_skill(slug, description, "\n".join(body_lines))
    print(f"wrote {path}", file=sys.stderr)
    return 0


# -- register / list / bundle / remove ---------------------------------------


def cmd_register(args: argparse.Namespace) -> int:
    """Create/overwrite a hand-authored skill."""
    slug = _slugify(args.name)
    body = ""
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    elif args.body:
        body = args.body
    else:
        body = f"# Skill: {slug}\n\n(Describe the workflow here.)"
    path = _write_skill(slug, args.description or slug, body)
    print(f"registered {path}", file=sys.stderr)
    return 0


def _iter_skills() -> list[Path]:
    """Return each ``skills/<slug>/SKILL.md`` path, sorted."""
    if not SKILLS_DIR.exists():
        return []
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def cmd_list(_: argparse.Namespace) -> int:
    """List registered skills."""
    skills = _iter_skills()
    if not skills:
        print("(no skills registered)", file=sys.stderr)
        return 0
    for path in skills:
        slug = path.parent.name
        desc = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
                break
        print(f"{slug}\t{desc}")
    return 0


def cmd_bundle(args: argparse.Namespace) -> int:
    """Concatenate all skills into one injectable prompt fragment."""
    skills = _iter_skills()
    if not skills:
        print("error: no skills to bundle", file=sys.stderr)
        return 1
    parts = [
        "# Learned skills",
        "",
        "The following skills were distilled from prior successful sessions.",
        "Apply them when a request matches.",
        "",
    ]
    for path in skills:
        parts.append(path.read_text(encoding="utf-8").strip())
        parts.append("\n---\n")
    out: Path = args.out
    out.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    print(f"bundled {len(skills)} skill(s) -> {out}", file=sys.stderr)
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Delete a skill directory (isolated scope only)."""
    directory = _skill_dir(_slugify(args.name))
    if not directory.exists():
        print(f"error: no such skill: {directory.name}", file=sys.stderr)
        return 1
    shutil.rmtree(directory)
    print(f"removed {directory}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser(
        "generate", help="DEPRECATED: distil a SKILL.md from telemetry (see OPERATIONS.md)"
    )
    gen.add_argument(
        "--force", action="store_true", help="override the deprecation and run anyway"
    )
    gen.add_argument("--name", required=True, help="Skill slug/name")
    gen.add_argument("--description", default="", help="One-line description")
    gen.add_argument("--log", type=Path, default=default_log_path())
    gen.add_argument("--from", dest="log", type=Path, help="Alias for --log")
    gen.add_argument("--examples", type=int, default=3)
    gen.set_defaults(func=cmd_generate)

    reg = sub.add_parser("register", help="Create/overwrite a hand-authored skill")
    reg.add_argument("--name", required=True)
    reg.add_argument("--description", default="")
    reg.add_argument("--body", default="")
    reg.add_argument("--body-file", default="")
    reg.set_defaults(func=cmd_register)

    lst = sub.add_parser("list", help="List registered skills")
    lst.set_defaults(func=cmd_list)

    bnd = sub.add_parser("bundle", help="Bundle skills into one prompt fragment")
    bnd.add_argument("--out", type=Path, default=SKILLS_DIR / "skills_prompt.md")
    bnd.set_defaults(func=cmd_bundle)

    rem = sub.add_parser("remove", help="Delete a skill")
    rem.add_argument("--name", required=True)
    rem.set_defaults(func=cmd_remove)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
