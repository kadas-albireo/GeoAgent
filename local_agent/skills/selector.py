#!/usr/bin/env python3
"""Dynamic skill selection under a context budget.

``upskill.py bundle`` concatenates *every* skill into one prompt fragment. That is fine
for Claude and wrong for a 7B with an 8-16k window: it spends budget teaching the model
about terrain when the user asked about coordinates, and the irrelevant guidance actively
degrades tool choice (context dilution).

This module selects only the skills a prompt actually needs, and -- the part that matters
-- returns the **tool subset** those skills declare.

Measured on this repo (2026-07-16):

    full KADAS surface   62 tools  ~10,604 tok   overflows an 8k window on its own
    one skill's subset  ~6 tools  ~  1,000 tok

Tool schemas are ~85% of the prompt budget, so selecting skills to save prompt text is
almost pointless; selecting them to **narrow the tool surface** is the whole game. See
``research/hardware_limitations.md`` §3.

Skill front matter::

    ---
    name: terrain-analysis
    description: ...
    triggers: [elevation, summit, hillshade, ...]   # keywords that select this skill
    tools: [get_elevation_at, ...]                  # the surface it needs
    ---

Standard library only.

Usage::

    python selector.py --prompt "What is the elevation of the Matterhorn?"
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent
DOCS_DIR = SKILLS_DIR.parent / "docs"


@dataclass
class Skill:
    """One parsed ``SKILL.md``."""

    name: str
    description: str
    body: str
    triggers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    path: Path | None = None

    @property
    def text(self) -> str:
        """The guidance as injected: body only.

        Front matter is stripped deliberately. ``triggers``/``tools`` are harness
        metadata; feeding them to the model spends tokens on noise and invites it to
        treat the trigger list as instructions.
        """
        return self.body

    def score(self, prompt: str) -> int:
        """Return how many trigger words *prompt* hits.

        Whole-word matching, so 'los' (line of sight) does not fire on 'close'. Crude on
        purpose: an embedding-based selector would be better but would add a dependency
        and a model load to a harness whose job is to measure a *different* model.
        """
        lowered = prompt.lower()
        return sum(
            1
            for trigger in self.triggers
            if re.search(rf"\b{re.escape(trigger.lower())}\b", lowered)
        )


def _parse_front_matter(text: str) -> tuple[dict[str, object], str]:
    """Split a ``---`` front-matter block from the body.

    Hand-rolled rather than pulling in PyYAML: the schema is three scalars and two inline
    lists, and this module is meant to run in any Python with no install step.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, object] = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key] = value
    return meta, parts[2].lstrip("\n")


def load_skills(
    directory: Path | None = None, *, pattern: str | None = None
) -> list[Skill]:
    """Load trigger-tagged Markdown from *directory*.

    Serves two corpora with the same front-matter contract:

    - **skills** — ``skills/<slug>/SKILL.md`` (the default, hand-authored guidance)
    - **doc packs** — ``docs/<slug>.md`` (flat, generated from the KADAS SIP bindings by
      ``docs/gen_kadas_docs.py``)

    Args:
        pattern: Glob for the files. Defaults to ``*/SKILL.md``; pass ``*.md`` for the
            flat doc packs. Getting this wrong fails *silently* -- the wrong glob simply
            matches nothing and retrieval quietly returns no context -- so it is an
            explicit argument rather than a guess based on the directory name.
    """
    base = directory or SKILLS_DIR
    skills = []
    for path in sorted(base.glob(pattern or "*/SKILL.md")):
        meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
        # <slug>/SKILL.md -> the slug is the parent dir; <slug>.md -> it is the stem.
        fallback = path.parent.name if path.name == "SKILL.md" else path.stem
        skills.append(
            Skill(
                name=str(meta.get("name", fallback)),
                description=str(meta.get("description", "")),
                body=body,
                triggers=list(meta.get("triggers", []) or []),  # type: ignore[arg-type]
                tools=list(meta.get("tools", []) or []),  # type: ignore[arg-type]
                path=path,
            )
        )
    return skills


def load_doc_packs(directory: Path | None = None) -> list[Skill]:
    """Load the generated KADAS doc packs (``docs/*.md``)."""
    return load_skills(directory or DOCS_DIR, pattern="*.md")


def select(
    prompt: str,
    *,
    directory: Path | None = None,
    max_skills: int = 2,
    pattern: str | None = None,
    max_tokens: int | None = None,
) -> list[Skill]:
    """Return the entries whose triggers *prompt* hits, best first.

    Capped at *max_skills*: injecting three documents to answer one question dilutes the
    context and defeats the point. Returns [] when nothing matches, which is correct --
    an unmatched prompt should get the base prompt, not a random document.

    Args:
        pattern: Passed to :func:`load_skills`. Use ``*.md`` for the flat doc packs.
        max_tokens: Drop selected entries once the cumulative estimate exceeds this.
            The generated ``kadas-annotations`` pack is ~9.4k tokens on its own, which
            alongside the ~12.7k tool prefix would consume two thirds of a 32k window;
            an unbounded selector would happily do that. Highest-scoring entries win.
    """
    scored = [
        (skill.score(prompt), skill)
        for skill in load_skills(directory, pattern=pattern)
    ]
    hits = sorted(
        ((score, skill) for score, skill in scored if score > 0),
        key=lambda pair: -pair[0],
    )
    chosen: list[Skill] = []
    budget = max_tokens
    for _, skill in hits[:max_skills]:
        if budget is not None:
            cost = len(skill.text) // 4  # ~4 chars/token; good enough to budget
            if cost > budget:
                continue
            budget -= cost
        chosen.append(skill)
    return chosen


def select_doc_packs(
    prompt: str, *, max_packs: int = 1, max_tokens: int | None = 4000
) -> list[Skill]:
    """Return the KADAS doc packs relevant to *prompt*.

    Defaults are deliberately tight: one pack, <=4k tokens. Doc packs are reference
    material for the prompt's volatile tail, and the tail is what gets reprocessed on
    every turn that changes it.
    """
    return select(
        prompt,
        directory=DOCS_DIR,
        max_skills=max_packs,
        pattern="*.md",
        max_tokens=max_tokens,
    )


def select_tools(
    prompt: str, *, directory: Path | None = None, max_skills: int = 2
) -> list[str]:
    """Return the union of tool names the selected skills declare.

    Empty means "no skill matched" -- the caller should fall back to the full surface
    rather than an empty toolset, since an agent with no tools can do nothing.
    """
    tools: list[str] = []
    for skill in select(prompt, directory=directory, max_skills=max_skills):
        for tool in skill.tools:
            if tool not in tools:
                tools.append(tool)
    return tools


def build_prompt_fragment(
    prompt: str, *, directory: Path | None = None, max_skills: int = 2
) -> str:
    """Return the guidance text to prepend for *prompt*, or '' if nothing matched."""
    skills = select(prompt, directory=directory, max_skills=max_skills)
    if not skills:
        return ""
    parts = [
        "# Relevant skills",
        "",
        "Apply the following guidance; it was distilled from prior successful sessions.",
        "",
    ]
    for skill in skills:
        parts.append(skill.text.strip())
        parts.append("\n---\n")
    return "\n".join(parts).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True, help="The user prompt to select for")
    parser.add_argument("--max-skills", type=int, default=2)
    parser.add_argument("--show-text", action="store_true", help="Print the fragment")
    args = parser.parse_args(argv)

    skills = select(args.prompt, max_skills=args.max_skills)
    if not skills:
        print("no skill matched -> full tool surface, base prompt")
        return 0

    print(f"prompt: {args.prompt!r}\n")
    for skill in skills:
        print(
            f"  {skill.name:24s} score={skill.score(args.prompt)}  {len(skill.tools)} tools"
        )
    tools = select_tools(args.prompt, max_skills=args.max_skills)
    print(f"\ntool subset ({len(tools)}): {tools}")
    if args.show_text:
        print("\n" + "=" * 60)
        print(build_prompt_fragment(args.prompt, max_skills=args.max_skills))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
