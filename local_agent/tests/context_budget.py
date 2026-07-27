#!/usr/bin/env python3
"""Measure what actually consumes a local model's context window.

The motivating finding: for ``for_kadas()`` the **tool schemas** cost ~9.9k tokens
while the whole skill bundle costs ~0.6k. Skill length is a rounding error; the tool
surface is the budget. This script re-measures that claim so it can be checked rather
than believed, and so it stays honest as the tool surface grows.

Runs against the mock hosts, so it needs no QGIS/KADAS and no GPU::

    ~/.open_geoagent/venv_py3.12/bin/python local_agent/tests/context_budget.py
    ~/.open_geoagent/venv_py3.12/bin/python local_agent/tests/context_budget.py --context 16384

Token counts are estimated at ~4 chars/token unless ``tiktoken`` is installed, in which
case a real BPE count is used. The estimate is within ~10% for JSON schemas and is fine
for budgeting; do not quote it as exact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SKILLS_DIR = REPO_ROOT / "local_agent" / "skills"

# Fraction of the window past which a small quantized model's recall degrades
# noticeably, even though the hard limit is not yet reached.
USABLE_FRACTION = 0.6


def count_tokens(text: str) -> int:
    """Return a token count for *text* (real BPE if available, else ~4 chars/token)."""
    try:
        import tiktoken
    except ImportError:
        return len(text) // 4
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def tool_schema_tokens(fast: bool) -> tuple[int, int, list[tuple[str, int]]]:
    """Return (tool_count, total_tokens, per_tool) for the KADAS surface.

    Builds a real agent against the mock hosts and reads the schemas Strands would
    actually send to the model, rather than trusting the decorators' docstrings.
    """
    from geoagent.core import factory
    from geoagent.testing import MockQGISIface, MockQGISProject

    agent = factory.for_kadas(
        MockQGISIface(),
        MockQGISProject(),
        fast=fast,
        # Never resolves a network client: we only read the tool registry.
        provider="litellm",
        model_id="openai/qwen2.5-7b-instruct",
    )
    specs = agent.strands_agent.tool_registry.get_all_tool_specs()
    per_tool = sorted(
        ((s["name"], count_tokens(json.dumps(s))) for s in specs),
        key=lambda pair: -pair[1],
    )
    return len(specs), sum(tokens for _, tokens in per_tool), per_tool


def system_prompt_tokens() -> int:
    """Return the token cost of KADAS_SYSTEM_PROMPT as shipped."""
    from geoagent.core import factory

    return count_tokens(factory.KADAS_SYSTEM_PROMPT)


def skill_bundle_tokens() -> int:
    """Return the token cost of the bundled skills, or 0 if not bundled yet."""
    bundle = SKILLS_DIR / "skills_prompt.md"
    if not bundle.exists():
        return 0
    return count_tokens(bundle.read_text(encoding="utf-8"))


def report(context: int, top: int) -> int:
    """Print the budget breakdown. Returns an exit code (1 if nothing fits)."""
    system = system_prompt_tokens()
    skills = skill_bundle_tokens()
    usable = int(context * USABLE_FRACTION)

    print(f"\ncontext window : {context:,} tokens")
    print(
        f"usable (~{int(USABLE_FRACTION * 100)}%)  : {usable:,} tokens "
        f"(recall degrades past this)\n"
    )

    rows: list[tuple[str, int, int, bool]] = []
    for fast in (False, True):
        count, tokens, per_tool = tool_schema_tokens(fast)
        total = tokens + system
        rows.append((f"for_kadas(fast={fast})", count, total, total <= usable))
        label = "fast " if fast else "full "
        print(
            f"{label}surface: {count:3d} tools  schemas ~{tokens:6,d} tok"
            f"  + system ~{system:,d}  = ~{total:6,d} tok"
        )
        if not fast and top:
            print(f"\n  most expensive tools (of {count}):")
            for name, tok in per_tool[:top]:
                print(f"    {name:38s} ~{tok:4,d} tok")
            print()

    print(f"\nsystem prompt  : ~{system:6,d} tok")
    print(
        f"skill bundle   : ~{skills:6,d} tok  "
        f"({skills / max(system + skills, 1) * 100:.0f}% of prompt text)"
    )

    print("\n" + "-" * 62)
    for label, count, total, fits in rows:
        verdict = "FITS" if fits else "OVERFLOWS"
        delta = (usable - total) / usable * 100
        print(
            f"{label:24s} {count:3d} tools  ~{total:6,d} tok  "
            f"{verdict:9s} ({delta:+.0f}% vs usable)"
        )
    print("-" * 62)

    if not any(fits for _, _, _, fits in rows):
        print(
            "\nNeither surface fits. Reduce the tool surface (skill `tools:` subset)\n"
            "or raise the model's context length. Trimming skills will not help:\n"
            f"the entire bundle is only ~{skills:,} tok.\n"
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--context",
        type=int,
        default=8192,
        help="Context window to budget against (LM Studio 'loaded_context_length')",
    )
    parser.add_argument(
        "--top", type=int, default=8, help="Show the N most expensive tools"
    )
    args = parser.parse_args(argv)
    return report(args.context, args.top)


if __name__ == "__main__":
    raise SystemExit(main())
