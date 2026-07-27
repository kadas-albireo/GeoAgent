#!/usr/bin/env python3
"""Turn a GeoAgent telemetry log into a Markdown trace for ``upskill generate``.

The core tracer (:mod:`geoagent.core.telemetry`) writes append-only **JSONL**
events to ``agent_execution.log``. ``upskill generate --from`` wants a readable
**Markdown** conversation. This script bridges the two: it groups the JSONL
events into turns and renders each turn as a user / reasoning / tool-call /
tool-result / answer exchange.

By default only "clean" turns are emitted (a turn that reached ``turn_end`` with
no ``error`` event and a non-error stop reason), because a skill should be
distilled from successful behaviour, not failures. Pass ``--all`` to keep every
turn.

Usage::

    python trace_from_log.py                       # ~/.kadas/agent_execution.log -> trace.md
    python trace_from_log.py --log path.log --out trace.md
    python trace_from_log.py --all --max-chars 4000

Standard library only, so it runs under any Python >= 3.10 (either the GeoAgent
3.10 venv or the upskill 3.13 venv).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def default_log_path() -> Path:
    """Mirror :func:`geoagent.core.telemetry.default_log_path`."""
    base = os.environ.get("GEOAGENT_LOG_DIR")
    directory = Path(base) if base else Path.home() / ".kadas"
    return directory / "agent_execution.log"


def _read_events(log_path: Path) -> list[dict[str, Any]]:
    """Return the parsed JSONL events, skipping blank or malformed lines."""
    events: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def _clip(text: str, max_chars: int) -> str:
    """Truncate long values so the trace stays token-cheap for the generator."""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"
    return text


def _as_text(value: Any) -> str:
    """Best-effort readable string for a logged value."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


def _format_result(result: Any) -> str:
    """Pull the text out of a Strands ToolResult, else pretty-print the value.

    Tool results are recorded raw and usually look like
    ``{"status": ..., "content": [{"text": "<json>"}], ...}`` — the ``text`` is
    the JSON your ``@geo_tool`` returned, which is what we want to show.
    """
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        parts = [
            block["text"]
            for block in result["content"]
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        if parts:
            return "\n".join(parts)
    return _as_text(result)


def _split_turns(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group events into turns delimited by ``turn_start`` / ``turn_end``.

    Events before the first ``turn_start`` (e.g. ``session_start``) are dropped
    from the per-turn output; the caller reads the preamble separately.
    """
    turns: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] | None = None
    for event in events:
        kind = event.get("kind")
        if kind == "turn_start":
            if current is not None:
                turns.append(current)
            current = [event]
        elif current is not None:
            current.append(event)
    if current is not None:
        turns.append(current)
    return turns


def _turn_is_clean(turn: list[dict[str, Any]]) -> bool:
    """True if the turn finished normally: reached ``turn_end``, no ``error``."""
    reached_end = False
    for event in turn:
        if event.get("kind") == "error":
            return False
        if event.get("kind") == "turn_end":
            reached_end = True
            stop = str(event.get("stop_reason", "")).lower()
            if "error" in stop or "exception" in stop:
                return False
    return reached_end


def _render_turn(index: int, turn: list[dict[str, Any]], max_chars: int) -> str:
    """Render one turn as a Markdown block."""
    lines: list[str] = [f"## Turn {index}", ""]
    for event in turn:
        kind = event.get("kind")
        if kind == "turn_start":
            task = _clip(_as_text(event.get("task", "")), max_chars).strip()
            lines += [f"**User:** {task}", ""]
        elif kind == "thinking":
            text = _clip(_as_text(event.get("text", "")), max_chars).strip()
            if text:
                lines += ["**Assistant (reasoning):**", "", text, ""]
        elif kind == "tool_call":
            name = event.get("name", "")
            args = _clip(_as_text(event.get("input")), max_chars)
            lines += [f"**Tool call — `{name}`:**", "", "```json", args, "```", ""]
        elif kind == "tool_result":
            name = event.get("name", "")
            body = _clip(_format_result(event.get("result")), max_chars)
            header = f"**Tool result — `{name}`"
            if event.get("exception"):
                header += f" (exception: {event['exception']})"
            lines += [header + ":**", "", "```json", body, "```", ""]
        elif kind == "turn_end":
            answer = _clip(_as_text(event.get("answer", "")), max_chars).strip()
            if answer:
                lines += ["**Assistant:**", "", answer, ""]
    return "\n".join(lines).rstrip() + "\n"


def _preamble(events: list[dict[str, Any]]) -> str:
    """Render the session_start system prompt + tool inventory, if present."""
    for event in events:
        if event.get("kind") == "session_start":
            tools = ", ".join(event.get("tools") or [])
            prompt = str(event.get("system_prompt", "")).strip()
            parts = ["# GeoAgent execution trace", ""]
            if tools:
                parts += [f"**Available tools:** {tools}", ""]
            if prompt:
                parts += [
                    "<details><summary>System prompt</summary>",
                    "",
                    prompt,
                    "",
                    "</details>",
                    "",
                ]
            return "\n".join(parts)
    return "# GeoAgent execution trace\n"


def build_trace(
    events: list[dict[str, Any]], *, include_all: bool, max_chars: int
) -> tuple[str, int, int]:
    """Return ``(markdown, total_turns, included_turns)``."""
    turns = _split_turns(events)
    blocks = [_preamble(events)]
    included = 0
    for turn in turns:
        if not include_all and not _turn_is_clean(turn):
            continue
        included += 1
        blocks.append(_render_turn(included, turn, max_chars))
    return "\n".join(blocks).rstrip() + "\n", len(turns), included


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        type=Path,
        default=default_log_path(),
        help="Path to agent_execution.log (default: $GEOAGENT_LOG_DIR or ~/.kadas)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("trace.md"),
        help="Markdown trace to write (default: ./trace.md)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="include_all",
        help="Include every turn, not just clean/successful ones",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=2000,
        help="Truncate any single value past this many chars (0 = no limit)",
    )
    args = parser.parse_args(argv)

    if not args.log.exists():
        print(f"error: log not found: {args.log}", file=sys.stderr)
        return 1

    events = _read_events(args.log)
    if not events:
        print(f"error: no events parsed from {args.log}", file=sys.stderr)
        return 1

    markdown, total, included = build_trace(
        events, include_all=args.include_all, max_chars=args.max_chars
    )
    args.out.write_text(markdown, encoding="utf-8")
    kept = "all" if args.include_all else "clean"
    print(
        f"wrote {args.out}  ({included}/{total} turns, {kept} filter, "
        f"{len(events)} events)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
