"""Turn a sweep into a table — the reporting half of requirement #6.

Two inputs, one job (make the token / cost / context / latency numbers skimmable):

- plan rows from :func:`local_agent.suite.runner.run_plan` → :func:`render_plan`.
- live telemetry JSONL written by :class:`local_agent.telemetry.tracker.BenchmarkTracker`
  → :func:`summarize_live` (wraps ``tracker.summarize`` and adds a priced-cost roll-up).

Plain text tables on purpose: this is read in a terminal and pasted into notes, so no
dependency on rich/tabulate. Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _table(headers: list[str], rows: list[list[str]]) -> str:
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    sep = "  ".join("-" * w for w in widths)
    body = [
        "  ".join(str(c).ljust(w) for c, w in zip(row, widths)) for row in rows
    ]
    return "\n".join([line, sep, *body])


def render_plan(rows: list[dict[str, Any]]) -> str:
    """Per-(agent, scenario) footprint table + a per-agent roll-up."""
    if not rows:
        return "no plan rows."
    detail = _table(
        ["agent", "test", "model", "overhead", "window", "fits", "$/turn", "notes"],
        [
            [
                r["agent"],
                r["test_id"] or "-",
                r["model"][:22],
                str(r["fixed_overhead"]),
                str(r["window"]),
                "yes" if r["fits"] else "NO",
                _usd(r["usd_per_turn"], r["priced"]),
                _notes(r),
            ]
            for r in rows
        ],
    )

    # Per-agent roll-up: worst-case fit and mean cost across the scenarios.
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_agent.setdefault(r["agent"], []).append(r)
    summary_rows = []
    for agent, rs in by_agent.items():
        n = len(rs)
        fit = sum(1 for r in rs if r["fits"])
        mean_over = sum(r["fixed_overhead"] for r in rs) // n
        mean_usd = sum(r["usd_per_turn"] for r in rs) / n
        priced = any(r["priced"] for r in rs)
        summary_rows.append(
            [agent, f"{fit}/{n}", str(mean_over), _usd(round(mean_usd, 6), priced)]
        )
    summary = _table(
        ["agent", "fits", "mean overhead", "mean $/turn"], summary_rows
    )
    return f"Context footprint (no model called)\n\n{detail}\n\nPer-agent\n\n{summary}"


def _usd(value: float, priced: bool) -> str:
    if not priced:
        return "n/a"
    if value == 0:
        return "$0 (local)"
    return f"${value:.5f}"


def _notes(row: dict[str, Any]) -> str:
    bits: list[str] = []
    if row.get("adaptations"):
        bits.append("adapted:" + ",".join(row["adaptations"])[:40])
    if row.get("recommendations"):
        bits.append(row["recommendations"][0][:48])
    return "; ".join(bits)


def summarize_live(paths: list[Path]) -> str:
    """Aggregate live telemetry: pass rate + latency (via tracker) and priced cost."""
    from local_agent.suite import cost as cost_mod
    from local_agent.telemetry.tracker import read_records, summarize

    base = summarize(paths)

    total_usd = 0.0
    any_priced = False
    for path in paths:
        for rec in read_records(path):
            tok = rec.get("tokens") or {}
            est = cost_mod.estimate(
                model=rec.get("model_id", ""),
                input_tokens=int(tok.get("input_accumulated", 0)),
                output_tokens=int(tok.get("output_accumulated", 0)),
                local=False,  # price everything; local rows just resolve to $0 in the table
            )
            if est.priced:
                any_priced = True
                total_usd += est.usd
    cost_line = (
        f"\n\nEstimated cost across priced records: ${total_usd:.4f} "
        "(priors; verify against live pricing)"
        if any_priced
        else "\n\nNo priced records (all local, or model not in cost table)."
    )
    return base + cost_line


# -- agent execution trace ---------------------------------------------------


def summarize_trace(log_path: Path, run_id: str | None = "latest") -> str:
    """Per-agent table of one suite sweep, read from the agent execution log.

    ``run_id="latest"`` picks the most recent sweep in the log; ``None`` takes
    every suite record. Token columns are the provider's real counts from
    ``model_call`` records; ``first``/``peak`` are input tokens of the first and
    largest request in a query, averaged over queries.
    """
    records = []
    with Path(log_path).open(encoding="utf-8") as handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("source") == "suite":
                records.append(rec)
    if run_id == "latest" and records:
        run_id = records[-1].get("run_id")
    if run_id:
        records = [r for r in records if r.get("run_id") == run_id]
    if not records:
        return "no suite records in the log."

    queries: dict[str, dict[str, Any]] = {}
    for rec in records:
        q = queries.setdefault(
            rec["query_id"], {"config": rec.get("config", "?"), "calls": [], "turn": None}
        )
        if rec.get("kind") == "model_call":
            q["calls"].append(rec)
        elif rec.get("kind") == "turn":
            q["turn"] = rec

    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    by_config: dict[str, list[dict[str, Any]]] = {}
    for q in queries.values():
        by_config.setdefault(q["config"], []).append(q)

    rows = []
    for config, qs in by_config.items():
        errors = sum(1 for q in qs if q["turn"] and not q["turn"].get("success"))
        with_calls = [q for q in qs if q["calls"]]

        def inputs(q: dict[str, Any]) -> list[int]:
            return [(c.get("usage") or {}).get("inputTokens") or 0 for c in q["calls"]]

        first = [q["calls"][0].get("context_chars") or {} for q in with_calls]
        rows.append(
            [
                config,
                str(len(qs)),
                str(errors),
                f"{mean([len(q['calls']) for q in with_calls]):.1f}",
                f"{mean([inputs(q)[0] for q in with_calls]):,.0f}",
                f"{mean([max(inputs(q)) for q in with_calls]):,.0f}",
                f"{mean([sum(inputs(q)) for q in with_calls]):,.0f}",
                f"{mean([sum((c.get('usage') or {}).get('outputTokens') or 0 for c in q['calls']) for q in with_calls]):,.0f}",
                f"{mean([f.get('system_prompt', 0) for f in first]):,.0f}",
                f"{mean([f.get('tool_specs', 0) for f in first]):,.0f}",
                f"{mean([f.get('messages', 0) for f in first]):,.0f}",
            ]
        )
    headers = [
        "config", "queries", "errors", "req/q", "first in", "peak in", "billed in/q",
        "out/q", "sys chars", "tool chars", "msg chars (1st)",
    ]
    return f"run {run_id}\n" + _table(headers, rows)
