"""Shipped, context-adaptive KADAS operations guide (the "upskilling" injection).

This is the **shipped home** of the operations guide so the KADAS/QGIS *plugin* can inject
it: the plugin cannot import ``local_agent`` (the experiment scope), but it can import this.
The eval harness (``local_agent.skills.operations``) delegates here too, so there is one
source of truth: ``kadas_operations_guide.md`` next to this file.

The guide is nested in three tiers, cheapest first (``core`` → ``extended`` → ``reference``),
marked with ``<!-- TIER: name -->`` comments. :func:`build_block` returns the largest tier
*prefix* that fits a token budget, so a 131k-context model gets the whole guide while a
small local model whose tool schemas already fill its window gets only ``core`` — the
"injection scales to the model's context size" behaviour.

Import-safe: standard library only, no QGIS, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

GUIDE_PATH = Path(__file__).resolve().parent / "kadas_operations_guide.md"

TIER_ORDER = ("core", "extended", "reference")
_CHARS_PER_TOKEN = 4  # ~4 chars/token; enough to budget, never quoted as exact.


def _read_guide() -> str:
    try:
        return GUIDE_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _strip_front_matter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[text.find("\n", end + 1) + 1 :]
    return text


def load_tiers() -> dict[str, str]:
    """Return ``{tier_name: body}`` parsed from the guide's tier markers.

    A guide with no markers degrades to ``{"core": <whole body>}`` so a hand-edit that
    drops the comments still injects something rather than nothing.
    """
    body = _strip_front_matter(_read_guide())
    if not body.strip():
        return {}
    tiers: dict[str, str] = {}
    for name in TIER_ORDER:
        m = re.search(
            rf"<!--\s*TIER:\s*{name}\s*-->(.*?)<!--\s*END TIER:\s*{name}\s*-->",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            tiers[name] = m.group(1).strip()
    if not tiers:
        tiers["core"] = body.strip()
    return tiers


def estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def selected_tiers(max_tokens: int | None) -> list[str]:
    """Which tier names fit within ``max_tokens`` (nested, cheapest first)."""
    tiers = load_tiers()
    out: list[str] = []
    used = 0
    for name in TIER_ORDER:
        chunk = tiers.get(name)
        if not chunk:
            continue
        cost = estimate_tokens(chunk)
        if max_tokens is not None and used + cost > max_tokens:
            break
        out.append(name)
        used += cost
    return out


def build_block(max_tokens: int | None = None) -> str:
    """Return the operations guidance sliced to ``max_tokens``, wrapped in delimiters.

    Args:
        max_tokens: Token budget. ``None`` -> the whole guide (the big-context path). A
            budget too small even for ``core`` returns "" — better nothing than half a rule.
    """
    tiers = load_tiers()
    if not tiers:
        return ""
    chosen: list[str] = []
    used = 0
    for name in TIER_ORDER:
        chunk = tiers.get(name)
        if not chunk:
            continue
        cost = estimate_tokens(chunk)
        if max_tokens is not None and used + cost > max_tokens:
            break
        chosen.append(chunk)
        used += cost
    if not chosen:
        return ""
    inner = "\n\n".join(chosen)
    return (
        "--- BEGIN KADAS OPERATIONS GUIDE ---\n"
        f"{inner}\n"
        "--- END KADAS OPERATIONS GUIDE ---"
    )
