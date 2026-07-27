"""Turn a sweep into a table — the reporting half of requirement #6.

Two inputs, one job (make the token / cost / context / latency numbers skimmable):

- plan rows from :func:`local_agent.suite.runner.run_plan` → :func:`render_plan`.
- live telemetry JSONL written by :class:`local_agent.telemetry.tracker.BenchmarkTracker`
  → :func:`summarize_live` (wraps ``tracker.summarize`` and adds a priced-cost roll-up).

Plain text tables on purpose: this is read in a terminal and pasted into notes, so no
dependency on rich/tabulate. Standard library only.
"""

from __future__ import annotations

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
