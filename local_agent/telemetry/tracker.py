#!/usr/bin/env python3
"""Model-scoped, date-stamped telemetry for benchmark runs.

Distinct from ``geoagent.core.telemetry``, which traces a *live* KADAS session into one
``~/.kadas/agent_execution.log``. This module is for *comparing agents*, so it partitions
by model and day::

    local_agent/telemetry/<model>_telemetry_<YYYY-MM-DD>.log

One JSONL record per benchmark test. Each record carries everything needed to (a) compare
agents and (b) author a SKILL.md from the failures, without re-running anything:

- ``agent_name``   the exact model string that produced the result
- ``latency_ms``   wall-clock for the turn
- ``tokens``       usage if the provider reported it (local backends often do not).
                   **Accumulated over the agent loop, not context occupancy** -- see
                   ``run_evals._extract_tokens``. Divide by ``tokens['cycles']`` for the
                   per-model-call figure comparable to the context window.
- ``status``       pass / fail / error  -- ADVISORY, see below
- ``screenshot``   path to the capture for this step
- ``raw_output``   the agent's full untruncated response, for gap analysis
- ``tool_calls``   the tools it actually invoked, in order

**On ``status``:** it is a triage hint from mechanical checks, never a verdict. The
authoritative signal is a human reading ``raw_output`` and the screenshot. Records carry
``advisory: true`` to keep that honest in downstream analysis.

Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

TELEMETRY_DIR = Path(__file__).resolve().parent

# Mechanical outcome of a test. 'error' means the harness or agent raised; 'fail' means it
# ran but the advisory checks did not pass.
STATUSES = ("pass", "fail", "error")


def sanitize_model_name(name: str) -> str:
    """Return a filesystem-safe form of a model id.

    Model ids carry separators that are illegal or awkward in filenames
    (``openai/qwen2.5-7b-instruct``, ``us.anthropic.claude-sonnet-4-6``). Collapse
    anything outside ``[A-Za-z0-9._-]`` to a hyphen so the log path stays predictable.

    >>> sanitize_model_name("openai/qwen2.5-7b-instruct")
    'openai-qwen2.5-7b-instruct'
    >>> sanitize_model_name("claude sonnet 4.6")
    'claude-sonnet-4.6'
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name).strip())
    return cleaned.strip("-.") or "unknown-model"


def log_path_for(
    model: str, *, day: date | None = None, directory: Path | None = None
) -> Path:
    """Return ``<dir>/<model>_telemetry_<YYYY-MM-DD>.log`` for *model*."""
    base = directory or Path(os.environ.get("LOCAL_AGENT_TELEMETRY_DIR", TELEMETRY_DIR))
    stamp = (day or date.today()).isoformat()
    return base / f"{sanitize_model_name(model)}_telemetry_{stamp}.log"


class BenchmarkTracker:
    """Append-only JSONL sink for one agent's benchmark run.

    One tracker per agent config; the log path is fixed at construction from the model
    name and today's date, so a sweep across three agents yields three files.
    """

    def __init__(
        self,
        agent_name: str,
        *,
        model_id: str | None = None,
        directory: Path | None = None,
        run_id: str | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.model_id = model_id or agent_name
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._path = log_path_for(self.model_id, directory=directory)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def log_path(self) -> Path:
        """The JSONL file records are appended to."""
        return self._path

    def record(
        self,
        *,
        test_id: str,
        difficulty: str,
        category: str,
        prompt: str,
        status: str,
        latency_ms: float,
        raw_output: str = "",
        screenshot: str | os.PathLike[str] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tokens: dict[str, int] | None = None,
        checks: dict[str, Any] | None = None,
        error: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Append one benchmark record and return the event written.

        Args:
            status: One of :data:`STATUSES`. Advisory only.
            raw_output: The agent's complete response. Deliberately **not truncated** --
                this is the raw material for gap analysis and skill authoring.
            screenshot: Path to this step's capture, or None if capture failed.
            checks: Which advisory criteria passed, for triage.
        """
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {status!r}")

        event: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "model_id": self.model_id,
            "test_id": test_id,
            "difficulty": difficulty,
            "category": category,
            "prompt": prompt,
            "status": status,
            "advisory": True,
            "latency_ms": round(latency_ms, 1),
            "tokens": tokens or {},
            "screenshot": str(screenshot) if screenshot else None,
            "tool_calls": tool_calls or [],
            "checks": checks or {},
            "raw_output": raw_output,
        }
        if error:
            event["error"] = error
        event.update(extra)

        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return event


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read a telemetry JSONL file, skipping malformed lines.

    A partially-written final line is expected if a run was interrupted; that should not
    render the whole log unreadable.
    """
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def summarize(paths: list[Path]) -> str:
    """Render a comparison table across agents' telemetry logs.

    Groups by agent so a sweep reads as "who did better", which is the whole point.
    """
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        for record in read_records(path):
            by_agent.setdefault(record.get("agent_name", "?"), []).append(record)

    if not by_agent:
        return "(no telemetry records found)"

    lines = [
        "",
        f"{'agent':28s} {'pass':>5s} {'fail':>5s} {'err':>4s} {'median ms':>10s}",
        "-" * 56,
    ]
    for agent, records in sorted(by_agent.items()):
        counts = {s: sum(1 for r in records if r.get("status") == s) for s in STATUSES}
        latencies = sorted(r.get("latency_ms", 0) for r in records)
        median = latencies[len(latencies) // 2] if latencies else 0
        lines.append(
            f"{agent[:28]:28s} {counts['pass']:5d} {counts['fail']:5d} "
            f"{counts['error']:4d} {median:10,.0f}"
        )
    lines += [
        "-" * 56,
        "pass/fail are ADVISORY mechanical checks. Review the screenshots",
        "and raw_output before drawing any conclusion.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Summarize today's telemetry, or whichever logs are passed."""
    import argparse

    parser = argparse.ArgumentParser(description="Summarize benchmark telemetry")
    parser.add_argument(
        "logs", nargs="*", type=Path, help="Log files (default: all in telemetry dir)"
    )
    args = parser.parse_args(argv)
    paths = args.logs or sorted(TELEMETRY_DIR.glob("*_telemetry_*.log"))
    print(summarize(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
