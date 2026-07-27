# -*- coding: utf-8 -*-
"""Developer "Full LLM Mode Logging" run logger for the chat dock.

The chat dock's *Enable Full LLM Mode Logging* toggle records every finished
chat turn to a structured JSONL file so a developer can inspect exactly what the
agent did in real time (``tail -f`` the file, or open the folder with the *Logs*
button).

Two log surfaces exist and complement each other:

* The **core tracer** (:class:`geoagent.core.telemetry.AgentTracer`) writes
  fine-grained events (the exact system + user prompt, each raw tool call, tool
  results, and clean unified file diffs) while a turn runs, when the agent is
  created with ``enable_logging=True``.
* This **run logger** writes one compact turn-summary record per finished turn
  from the dock's ``job`` / ``result`` dicts (prompt, model, tools called with
  their args, a summary of any file/script changes, and the final answer).

Both stream to ``<log_dir>/agent_execution.log`` (``~/.kadas`` by default, or
``$GEOAGENT_LOG_DIR``) so everything for a session lands in one inspectable file.

This module is import-safe in plain CI: it imports the optional
``geoagent.core.telemetry`` helpers lazily and falls back to local logic when
they are unavailable.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_FILENAME = "agent_execution.log"


def _default_log_dir() -> Path:
    """Return the directory the execution log is written to."""
    override = os.environ.get("GEOAGENT_LOG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".kadas"


def _compact(value, _depth=0):
    """Return a size-limited, JSON-friendly copy of a value."""
    if _depth > 6:
        return "..."
    if isinstance(value, dict):
        return {str(k): _compact(v, _depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_compact(v, _depth + 1) for v in list(value)[:40]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = value if isinstance(value, str) else str(value)
    if len(text) > 8000:
        return text[:8000] + "... [truncated]"
    return text


def _extract_changes(tool_calls):
    """Summarize file/script changes the agent made during the turn.

    Pulls the generated code out of ``run_pyqgis_script`` calls and the command
    out of ``run_command`` calls so a reviewer can see, in one place, what the
    agent actually changed or ran. The core tracer additionally records true
    before/after unified diffs when full logging is enabled.
    """
    changes = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "")
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        if name == "run_pyqgis_script":
            code = str(args.get("code") or "")
            if code:
                changes.append(
                    {
                        "tool": name,
                        "summary": args.get("description") or "PyQGIS script",
                        "detail": code[:8000],
                    }
                )
        elif name == "run_command":
            command = str(args.get("command") or "")
            if command:
                changes.append(
                    {
                        "tool": name,
                        "summary": "Terminal command",
                        "detail": command[:8000],
                    }
                )
        else:
            # Any explicit output/path argument is a candidate change target.
            for key, val in args.items():
                if (
                    isinstance(key, str)
                    and "path" in key.lower()
                    and isinstance(val, str)
                ):
                    changes.append(
                        {
                            "tool": name,
                            "summary": f"{key}={val}",
                            "detail": "",
                        }
                    )
    return changes


def build_turn_record(job, result):
    """Build a structured JSONL record for one finished chat turn.

    Args:
        job: The dock's job dict (prompt, provider, model, mode,
            permission_profile, ...).
        result: The worker's result dict (success, answer, error, tools,
            tool_calls, cancelled, elapsed, ...).

    Returns:
        A JSON-serializable dict describing the turn.
    """
    job = job or {}
    result = result or {}
    tool_calls = result.get("tool_calls") or job.get("tool_calls") or []

    return {
        "record_type": "turn",
        "time": time.time(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": _compact(job.get("prompt", "")),
        "provider": job.get("provider", ""),
        "model": job.get("model", ""),
        "mode": job.get("mode", ""),
        "permission_profile": job.get("permission_profile", ""),
        "success": bool(result.get("success", False)),
        "elapsed": result.get("elapsed", ""),
        "executed_tools": result.get("tools", ""),
        "cancelled": result.get("cancelled", ""),
        "error": _compact(result.get("error", "")),
        "answer": _compact(result.get("answer", "")),
        "tool_calls": [_compact(call) for call in tool_calls],
        "changes": _extract_changes(tool_calls),
    }


class RunLogger:
    """Append full-LLM-mode turn records to a JSONL execution log."""

    def __init__(self, log_dir=None):
        self.log_dir = Path(log_dir) if log_dir else _default_log_dir()

    @property
    def log_file(self) -> Path:
        """The JSONL file turn records are appended to."""
        return self.log_dir / LOG_FILENAME

    def log_turn(self, record):
        """Append one turn record. Returns the log path, or ``None`` on failure.

        Logging must never break a chat turn, so all errors are swallowed.
        """
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, default=str, ensure_ascii=False)
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return self.log_file
        except Exception:
            return None

    def read_recent(self, limit=50):
        """Return up to ``limit`` most-recent records (for a console view)."""
        try:
            if not self.log_file.exists():
                return []
            lines = self.log_file.read_text(encoding="utf-8").splitlines()
            records = []
            for line in lines[-max(0, limit) :]:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
            return records
        except Exception:
            return []


__all__ = ["RunLogger", "build_turn_record", "LOG_FILENAME"]
