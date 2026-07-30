"""Plan-first reasoning — a lightweight "think, then act" loop for small models.

Small local models act far better when they **plan before they call tools** than when they
jump straight into tool use. This module runs a cheap planning pass: a **toolless** model
call that turns the user request into a short, ordered plan naming the tools to use. The
plan is then prepended to the real (tool-enabled) turn, so the model executes against its
own decomposition instead of improvising step by step.

Why toolless: the planner does **not** get the ~10.6k tokens of tool schemas — only the tool
*names* as a menu. So the extra call is cheap and fast even on a slow endpoint, and it keeps
the model's attention on "what's the approach" rather than "which argument goes where".

This mirrors the value of a plan/'/loop' step: one reasoning pass up front, then execution.

Shipped in the core so the plugin (a clickable UI mode) and the eval harness both use the
same primitive. Import-safe: ``strands`` is imported lazily inside :func:`make_plan`.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

PLANNER_SYSTEM_PROMPT = """\
You are the PLANNING step of a GIS map assistant. You do not act; you plan.

Given a user request and a list of available tool names, write a SHORT numbered plan
(1-6 steps) describing how to fulfil it. For each step, name the single tool to call and
its key arguments (use the exact tool names given). Prefer the narrowest dedicated tool;
reach for a script only as a last resort. If the request needs just one tool, a one-line
plan is correct.

Rules:
- Output ONLY the plan. Do NOT call any tool now. Do NOT write the final answer.
- If a step needs a value you do not have yet (a coordinate, a layer name), say which
  earlier step or tool provides it.
- Keep it tight: a plan the model can follow, not an essay.
"""


def make_plan(
    model: Any,
    query: str,
    *,
    tool_names: Optional[Sequence[str]] = None,
    guide_block: str = "",
) -> str:
    """Return a short plan for *query*, produced by a toolless call on *model*.

    Args:
        model: A resolved Strands model object. Reuse the main agent's model
            (``agent.strands_agent.model``) so the plan runs on the same endpoint with no
            re-resolution.
        tool_names: The tool names available for execution, shown to the planner as a menu.
            Names only — never the full schemas — to keep the call cheap.
        guide_block: Optional operations-guide text (e.g. the ``core`` tier) to steer the
            plan toward the right pathways.

    Returns:
        The plan text, or "" if planning produced nothing (caller then runs normally).
    """
    from strands import Agent

    menu = ", ".join(tool_names) if tool_names else "(the available tools)"
    parts = [f"Available tools: {menu}", ""]
    if guide_block:
        parts += [guide_block, ""]
    parts += [f"User request:\n{query}", "", "Write the numbered plan now."]
    user_message = "\n".join(parts)

    planner = Agent(model=model, tools=[], system_prompt=PLANNER_SYSTEM_PROMPT)
    result = planner(user_message)
    return _plan_text(result)


def _plan_text(result: Any) -> str:
    """Extract plan text from a Strands result, robust to shape differences."""
    try:
        message = getattr(result, "message", None)
        if isinstance(message, dict):
            texts = [
                block.get("text", "")
                for block in message.get("content", [])
                if isinstance(block, dict)
            ]
            joined = "\n".join(t for t in texts if t).strip()
            if joined:
                return joined
    except Exception:
        pass
    text = str(result).strip()
    return text if text and text.lower() != "none" else ""


def build_execution_prompt(plan: str, query: str) -> str:
    """Prepend *plan* to *query* as the execution turn, or return *query* unchanged."""
    if not plan:
        return query
    return (
        "You planned this approach:\n"
        f"{plan}\n\n"
        "Now carry it out by calling the tools in order. If a step turns out to be wrong "
        "or a tool errors, adjust and continue.\n\n"
        f"User request:\n{query}"
    )
