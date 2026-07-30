"""Adapt the prompt to the model at hand, and account for what it costs.

Requirements #4 (balance tools vs freedom), #5 (documancer), and #6 (context accounting)
all reduce to one question asked per (prompt, model): **does the agent's own prompt fit,
and if not, what gives?** This module answers it without calling any model.

The finding this repo is built on (``local_agent/README.md``): for ``for_kadas()`` the
**tool schemas** are ~85% of the budget, the prompts are a rounding error. So the levers,
in order of effect, are:

    1. the tool surface   (full 62 tools ≈ 10.6k tok  →  fast subset ≈ ...)   << biggest
    2. api_docs injection  (documancer; capped, per-prompt)
    3. upskill injection   (operations pathway; small)

:func:`plan_context` measures all of these for a spec and reports whether the fixed
overhead fits the model's usable window. :func:`adapt_spec` returns a spec adjusted to fit
(flip to the fast surface, drop optional injections) — the "adapt the context based on the
model at hand" half of #6.

Import-safe: token measurement builds a real agent against the **mock** hosts (no QGIS, no
GPU, no network), reusing ``local_agent.tests.context_budget``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from local_agent.suite.agents import AgentSpec

# Past this fraction of the hard window, a small quantised model's recall degrades even
# though the limit is not yet hit. Matches ``context_budget.USABLE_FRACTION``.
USABLE_FRACTION = 0.6

# When a spec gives no context_window, assume this. 8192 is LM Studio's conservative
# default load and the value that first exposed the tool-schema problem — a safe worst case.
ASSUMED_WINDOW = 8192

# Cap the operations guide at this fraction of the usable window, so injecting it never
# eats the room a turn needs for history + tool results. On a big-context model this cap is
# far above the full guide (so the whole thing goes in); on a small one it forces the CORE
# tier only. This is the "injection depends on the agent's context size" mechanism.
UPSKILL_MAX_FRACTION = 0.15


@dataclass
class ContextPlan:
    """What one (prompt, spec) will put in front of the model, in tokens."""

    agent: str
    model: str
    window: int
    usable: int
    fast: bool
    system_tokens: int
    tool_count: int
    tool_tokens: int
    api_docs_tokens: int
    upskill_tokens: int
    prompt_tokens: int
    recommendations: list[str] = field(default_factory=list)

    @property
    def fixed_overhead(self) -> int:
        """Everything the model must read before it can answer this one turn."""
        return (
            self.system_tokens
            + self.tool_tokens
            + self.api_docs_tokens
            + self.upskill_tokens
            + self.prompt_tokens
        )

    @property
    def fits(self) -> bool:
        return self.fixed_overhead <= self.usable

    @property
    def headroom(self) -> int:
        """Usable tokens left for conversation history + tool results after the overhead."""
        return self.usable - self.fixed_overhead

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "model": self.model,
            "window": self.window,
            "usable": self.usable,
            "fast": self.fast,
            "system_tokens": self.system_tokens,
            "tool_count": self.tool_count,
            "tool_tokens": self.tool_tokens,
            "api_docs_tokens": self.api_docs_tokens,
            "upskill_tokens": self.upskill_tokens,
            "prompt_tokens": self.prompt_tokens,
            "fixed_overhead": self.fixed_overhead,
            "headroom": self.headroom,
            "fits": self.fits,
            "recommendations": self.recommendations,
        }


def _count(text: str) -> int:
    from local_agent.tests.context_budget import count_tokens

    return count_tokens(text)


def api_docs_block(prompt: str, *, max_tokens: int = 4000) -> str:
    """The KADAS API reference that would be injected for *prompt* (documancer, #5)."""
    from geoagent.core import context_docs

    return context_docs.build_context_block(prompt, max_packs=1, max_tokens=max_tokens)


def upskill_block(prompt: str, max_tokens: int | None = None) -> str:
    """The operations guidance to inject, sliced to ``max_tokens``.

    Draws from the single cohesive ``skills/kadas-operations/SKILL.md`` (documented in
    ``OPERATIONS.md``), tier-sliced by :mod:`local_agent.skills.operations` so a small
    window gets only the CORE conventions and a large one gets the whole guide. ``prompt``
    is unused — the guide is cohesive, not prompt-specific — but kept for call-site
    symmetry with :func:`api_docs_block`. Telemetry auto-generation is deprecated.
    """
    from local_agent.skills import operations

    return operations.build_operations_block(max_tokens)


def upskill_budget(usable: int, base_tokens: int) -> int:
    """Tokens available for the operations guide: leftover after the fixed base, capped.

    The cap (:data:`UPSKILL_MAX_FRACTION` of the usable window) preserves headroom for
    conversation history and tool results. Returns 0 when the base already fills the window.
    """
    leftover = max(0, usable - base_tokens)
    return min(leftover, int(usable * UPSKILL_MAX_FRACTION))


def plan_context(
    spec: "AgentSpec",
    prompt: str,
    *,
    usable_fraction: float = USABLE_FRACTION,
) -> ContextPlan:
    """Measure the fixed prompt overhead for *spec* answering *prompt*.

    Calls no model. Builds the tool surface against the mock hosts to read the exact
    schemas Strands would send, then adds whatever ``spec`` opts into.
    """
    from local_agent.tests.context_budget import (
        system_prompt_tokens,
        tool_schema_tokens,
    )

    window = spec.context_window or ASSUMED_WINDOW
    usable = int(window * usable_fraction)

    tool_count, tool_tokens, _ = tool_schema_tokens(fast=spec.fast)
    system_tokens = system_prompt_tokens()
    api_docs_tokens = _count(api_docs_block(prompt)) if spec.api_docs else 0
    prompt_tokens = _count(prompt)

    # The operations guide is injected at a depth that fits what is left after the fixed
    # base — the "adapt injection to the model's window" behaviour. Big window -> whole
    # guide; small window -> CORE conventions only; no room -> nothing.
    if spec.upskill:
        base = system_tokens + tool_tokens + api_docs_tokens + prompt_tokens
        upskill_tokens = _count(upskill_block(prompt, upskill_budget(usable, base)))
    else:
        upskill_tokens = 0

    plan = ContextPlan(
        agent=spec.name,
        model=spec.model,
        window=window,
        usable=usable,
        fast=spec.fast,
        system_tokens=system_tokens,
        tool_count=tool_count,
        tool_tokens=tool_tokens,
        api_docs_tokens=api_docs_tokens,
        upskill_tokens=upskill_tokens,
        prompt_tokens=prompt_tokens,
    )
    plan.recommendations = _recommend(plan, spec)
    return plan


def _recommend(plan: ContextPlan, spec: "AgentSpec") -> list[str]:
    """Ordered, actionable suggestions when the overhead is tight or over budget."""
    recs: list[str] = []
    if plan.fits and plan.headroom > plan.usable * 0.25:
        return recs  # comfortable; say nothing

    # Order matters: recommend the biggest lever first (tools >> docs >> upskill).
    if not spec.fast and plan.tool_tokens > plan.usable * 0.4:
        recs.append(
            f"tool schemas are {plan.tool_tokens} tok "
            f"({plan.tool_tokens * 100 // plan.usable}% of usable) — try fast=True."
        )
    if plan.api_docs_tokens and plan.fixed_overhead > plan.usable:
        recs.append(
            f"api_docs adds {plan.api_docs_tokens} tok; lower its cap or drop it for this model."
        )
    if plan.upskill_tokens and plan.fixed_overhead > plan.usable:
        recs.append(f"upskill adds {plan.upskill_tokens} tok; drop it if space is tight.")
    if not plan.fits and not recs:
        recs.append(
            f"over budget by {plan.fixed_overhead - plan.usable} tok with no cheap lever left; "
            "use a larger-context model or narrow the tool surface further."
        )
    return recs


def adapt_spec(spec: "AgentSpec", prompt: str) -> tuple["AgentSpec", ContextPlan, list[str]]:
    """Return a copy of *spec* adjusted to fit its window, the resulting plan, and a log.

    The "adapt the context based on the model at hand" mechanism (#6). Applies levers in
    effect order until the overhead fits or nothing is left to trim. A big-context model
    (e.g. Claude) is returned unchanged because its plan already fits.
    """
    from dataclasses import replace

    changes: list[str] = []
    current = spec
    plan = plan_context(current, prompt)

    if plan.fits:
        return current, plan, changes

    # 1. Full → fast surface (biggest lever).
    if not current.fast:
        current = replace(current, fast=True)
        changes.append("enabled fast tool surface")
        plan = plan_context(current, prompt)
    # 2. Drop api_docs.
    if not plan.fits and current.api_docs:
        current = replace(current, api_docs=False)
        changes.append("dropped api_docs injection")
        plan = plan_context(current, prompt)
    # 3. Drop upskill.
    if not plan.fits and current.upskill:
        current = replace(current, upskill=False)
        changes.append("dropped upskill injection")
        plan = plan_context(current, prompt)

    return current, plan, changes
