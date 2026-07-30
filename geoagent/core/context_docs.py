"""Keyword-retrieved KADAS/QGIS API reference for the prompt's tail.

KADAS has no published Python API reference, so a model asked to drive it works from
whatever it half-remembers about QGIS. That is the origin of the classic failure here:
confident calls to methods that do not exist, or right method / wrong argument names.

This module retrieves the *relevant* slice of the real API (generated from KADAS's SIP
bindings by ``local_agent/docs/gen_kadas_docs.py``) and hands it back as a text block for
the caller to put in the **user message**.

Position matters, and this is the whole reason the module exists rather than the docs
simply being appended to the system prompt:

    [ system prompt + tool definitions ]  <- STABLE. llama.cpp caches this prefix.
    [ conversation history ]
    [ retrieved docs + user query ]       <- VOLATILE. Cheap to reprocess.

Measured on a local qwen2.5-7b (2026-07-16): re-sending an identical ~16k prefix costs
**0.47s**; changing it costs **13-22s**, because the whole prefix (history included) must
be reprefilled. Docs vary per question, so putting them in the system prompt would
invalidate the cache on every single turn. In the user message they cost only their own
tokens.

Retrieval is deliberately keyword/trigger based rather than embedding based: it needs no
model, no VRAM (the 6 GiB dev box has ~290 MiB free with qwen loaded), and it is
debuggable -- you can see exactly why a pack matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# A pack must fit the tail without crowding out the answer. The KADAS tool schemas are
# ~12.7k of a 32k window; a 4k doc block keeps total prompt overhead near half, leaving
# room for history and tool results.
DEFAULT_MAX_TOKENS = 4000

# ~4 chars/token. Good enough to budget with; exact counting would need tiktoken, which is
# not a runtime dependency of the shipped package.
_CHARS_PER_TOKEN = 4


@dataclass
class DocPack:
    """One retrievable reference document."""

    name: str
    description: str
    text: str
    triggers: list[str] = field(default_factory=list)
    path: Path | None = None

    @property
    def estimated_tokens(self) -> int:
        """Rough token cost of injecting this pack."""
        return len(self.text) // _CHARS_PER_TOKEN

    def score(self, prompt: str) -> int:
        """Return how many trigger phrases *prompt* contains.

        Whole-word matching so 'los' does not fire on 'close' and 'line' does not fire on
        'online'. Multi-word triggers ('annotation layer') are matched as phrases.
        """
        lowered = prompt.lower()
        return sum(
            1
            for trigger in self.triggers
            if re.search(rf"(?<!\w){re.escape(trigger.lower())}(?!\w)", lowered)
        )


def _parse_front_matter(text: str) -> tuple[dict[str, object], str]:
    """Split a ``---`` front-matter block from the body."""
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


def load_packs(directory: Path | None = None) -> list[DocPack]:
    """Load every ``*.md`` doc pack from *directory* (default: shipped ``geoagent/docs``).

    Returns [] when the directory is missing rather than raising: the packs are optional
    reference data and their absence must degrade to "no extra context", never to a
    broken agent.
    """
    base = directory or DOCS_DIR
    if not base.is_dir():
        return []
    packs = []
    for path in sorted(base.glob("*.md")):
        meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
        packs.append(
            DocPack(
                name=str(meta.get("name", path.stem)),
                description=str(meta.get("description", "")),
                text=body.strip(),
                triggers=[str(t) for t in (meta.get("triggers") or [])],  # type: ignore[union-attr]
                path=path,
            )
        )
    return packs


def select_packs(
    prompt: str,
    *,
    directory: Path | None = None,
    max_packs: int = 1,
    max_tokens: int | None = DEFAULT_MAX_TOKENS,
) -> list[DocPack]:
    """Return the packs relevant to *prompt*, best match first.

    Args:
        max_packs: Cap on packs injected. One is usually right: two references for one
            question mostly dilutes attention.
        max_tokens: Skip packs that would blow the budget. ``None`` disables the check.

    Returns:
        [] when nothing matches, which is the correct outcome -- an unmatched prompt gets
        the base prompt rather than an arbitrary document.
    """
    scored = [(pack.score(prompt), pack) for pack in load_packs(directory)]
    ranked = sorted(
        ((score, pack) for score, pack in scored if score > 0),
        key=lambda pair: (-pair[0], pair[1].estimated_tokens),
    )
    chosen: list[DocPack] = []
    budget = max_tokens
    for _, pack in ranked:
        if len(chosen) >= max_packs:
            break
        if budget is not None:
            if pack.estimated_tokens > budget:
                continue
            budget -= pack.estimated_tokens
        chosen.append(pack)
    return chosen


def build_context_block(
    prompt: str,
    *,
    directory: Path | None = None,
    max_packs: int = 1,
    max_tokens: int | None = DEFAULT_MAX_TOKENS,
) -> str:
    """Return API reference text to prepend to the **user message**, or ''.

    Do not put the result in the system prompt: it changes per question and would
    invalidate the model's cached prefix every turn (see module docstring).
    """
    packs = select_packs(
        prompt, directory=directory, max_packs=max_packs, max_tokens=max_tokens
    )
    if not packs:
        return ""
    parts = [
        "The following is the real KADAS Python API, generated from its SIP bindings.",
        "Use these exact signatures. Do not invent methods that are not listed here.",
        "",
    ]
    for pack in packs:
        parts += [
            f"--- BEGIN API REFERENCE: {pack.name} ---",
            pack.text,
            f"--- END API REFERENCE: {pack.name} ---",
            "",
        ]
    return "\n".join(parts)


def available_packs(directory: Path | None = None) -> list[tuple[str, str, int]]:
    """Return ``(name, description, tokens)`` for each pack, for a UI listing."""
    return [
        (pack.name, pack.description, pack.estimated_tokens)
        for pack in load_packs(directory)
    ]
