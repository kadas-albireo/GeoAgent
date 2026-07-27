"""Token → USD estimation for a run.

Part of requirement #6: benchmark **cost** alongside tokens/latency/context, and make the
local-vs-cloud tradeoff legible. A local model's dollar cost is zero at the margin (you
already own the GPU); the number that matters there is latency and context, not price. So
this table exists mainly to price the *cloud baseline* you are comparing against.

    Provenance
    ----------
    The per-token prices below are **unverified priors from training data** and move
    faster than this file. They are order-of-magnitude, for relative comparison in a
    sweep — never quote them as a bill. For real numbers, check the provider's live
    pricing page (or ask the agent to web-search current rates) and pass ``--price-in`` /
    ``--price-out`` on the CLI to override.

Local providers (``local=True`` in the :class:`~local_agent.suite.agents.AgentSpec`) are
priced at $0 regardless of the table.
"""

from __future__ import annotations

from dataclasses import dataclass

# USD per 1,000,000 tokens, (input, output). Priors only — see module docstring.
# Keyed by a normalised model id prefix; longest matching prefix wins.
PRICE_TABLE_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-3-5-haiku": (0.80, 4.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
    "gpt-4.1": (2.0, 8.0),
    "o3": (2.0, 8.0),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2": (0.15, 0.60),
}

UNKNOWN_PRICE = (0.0, 0.0)


@dataclass
class CostEstimate:
    """A priced token count. ``priced`` is False when the model was not in the table."""

    input_tokens: int
    output_tokens: int
    usd: float
    priced: bool
    price_in: float  # USD / Mtok used
    price_out: float


def _normalise(model: str) -> str:
    """Strip routing prefixes like ``openai/`` and vendor scoping so keys match."""
    m = model.strip().lower()
    if "/" in m:
        m = m.split("/", 1)[1]
    return m


def lookup_price(model: str) -> tuple[float, float] | None:
    """Return ``(price_in, price_out)`` in USD/Mtok for *model*, or ``None``.

    Longest-prefix match so ``claude-sonnet-4-6`` resolves via ``claude-sonnet-4``.
    """
    key = _normalise(model)
    best: tuple[int, tuple[float, float]] | None = None
    for prefix, price in PRICE_TABLE_USD_PER_MTOK.items():
        if key.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), price)
    return best[1] if best else None


def estimate(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    local: bool = False,
    price_in: float | None = None,
    price_out: float | None = None,
) -> CostEstimate:
    """Price a single turn.

    Args:
        local: Self-hosted model → $0. Overrides the table.
        price_in/price_out: Explicit USD/Mtok overrides (from the CLI). Win over the table.
    """
    if local and price_in is None and price_out is None:
        return CostEstimate(input_tokens, output_tokens, 0.0, True, 0.0, 0.0)

    if price_in is not None or price_out is not None:
        pin, pout = price_in or 0.0, price_out or 0.0
        priced = True
    else:
        table = lookup_price(model)
        priced = table is not None
        pin, pout = table if table else UNKNOWN_PRICE

    usd = (input_tokens * pin + output_tokens * pout) / 1_000_000
    return CostEstimate(input_tokens, output_tokens, round(usd, 6), priced, pin, pout)
