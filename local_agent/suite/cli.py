"""Single entry point for the suite: ``python -m local_agent.suite <cmd>``.

Commands
--------
``list``       Show the agent registry (agents.json overlaid on defaults).
``status``     Snapshot both backends (LM Studio + ETH tunnel). Requirement #7.
``provision``  Make a backend ready: ``provision lmstudio`` / ``provision eth``. #7.
``budget``     Context footprint of a prompt across agents; no model called. #4/#5/#6.
``run``        Sweep scenarios across agents. ``--mode plan`` (default) or ``--mode live``.
``report``     Aggregate live telemetry JSONL into a token/cost/latency table. #6.

``budget`` and ``run --mode plan`` need **no backend** — that is the minimal-setup path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from local_agent.suite import agents as agents_mod
from local_agent.suite import budget as budget_mod
from local_agent.suite import provision as provision_mod
from local_agent.suite import report as report_mod
from local_agent.suite import runner as runner_mod


def _cmd_list(args: argparse.Namespace) -> int:
    registry = agents_mod.load_agents()
    if args.json:
        print(json.dumps([s.to_dict() for s in registry.values()], indent=2))
        return 0
    for spec in registry.values():
        tags = [k for k in ("local", "api_docs", "upskill", "fast", "plan") if getattr(spec, k)]
        win = spec.context_window or "?"
        print(f"{spec.name:<16} {spec.provider:<10} {spec.model:<26} ctx={win} "
              f"[{','.join(tags) or '-'}]")
        if spec.note:
            print(f"{'':<16} {spec.note}")
    return 0


def _cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(provision_mod.status(), indent=2))
    return 0


def _cmd_provision(args: argparse.Namespace) -> int:
    try:
        config = provision_mod.provision(
            args.target,
            model=args.model,
            context_length=args.context,
            progress=lambda m: print(f"  {m}", file=sys.stderr),
        )
    except Exception as exc:
        print(f"provision failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"ready: provider={config.provider} model={config.model}")
    return 0


def _cmd_budget(args: argparse.Namespace) -> int:
    specs = agents_mod.resolve(args.agents)
    rows = runner_mod.run_plan(
        specs,
        [{"id": "prompt", "prompt": args.prompt, "difficulty": "-"}],
        adapt=not args.no_adapt,
    )
    print(report_mod.render_plan(rows))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    specs = agents_mod.resolve(args.agents)
    scenarios = runner_mod.load_scenarios(difficulty=args.difficulty, ids=args.ids)
    if not scenarios:
        print("no scenarios matched.", file=sys.stderr)
        return 1
    if args.mode == "plan":
        rows = runner_mod.run_plan(specs, scenarios, adapt=not args.no_adapt)
        print(report_mod.render_plan(rows))
        return 0
    tracker_dir = Path(args.out) if args.out else None
    records = runner_mod.run_live(
        specs, scenarios, tracker_dir=tracker_dir, adapt=not args.no_adapt,
        progress=lambda m: print(f"  {m}", file=sys.stderr),
    )
    passed = sum(1 for r in records if r.get("status") == "pass")
    print(f"{passed}/{len(records)} advisory-pass. Telemetry in {tracker_dir or 'default log dir'}.")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.logs]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        print(f"no such log(s): {', '.join(map(str, missing))}", file=sys.stderr)
        return 1
    print(report_mod.summarize_live(paths))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m local_agent.suite", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="show the agent registry")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=_cmd_list)

    ps = sub.add_parser("status", help="snapshot LM Studio + ETH backends")
    ps.set_defaults(func=_cmd_status)

    pp = sub.add_parser("provision", help="make a backend ready")
    pp.add_argument("target", choices=list(provision_mod.TARGETS) + ["local", "cluster"])
    pp.add_argument("--model", default=None)
    pp.add_argument("--context", type=int, default=None)
    pp.set_defaults(func=_cmd_provision)

    pb = sub.add_parser("budget", help="context footprint of a prompt across agents")
    pb.add_argument("prompt")
    pb.add_argument("--agents", nargs="*", default=None)
    pb.add_argument("--no-adapt", action="store_true")
    pb.set_defaults(func=_cmd_budget)

    pr = sub.add_parser("run", help="sweep scenarios across agents")
    pr.add_argument("--agents", nargs="*", default=None)
    pr.add_argument("--mode", choices=["plan", "live"], default="plan")
    pr.add_argument("--difficulty", default=None)
    pr.add_argument("--ids", nargs="*", default=None)
    pr.add_argument("--out", default=None, help="telemetry dir for live mode")
    pr.add_argument("--no-adapt", action="store_true")
    pr.set_defaults(func=_cmd_run)

    prep = sub.add_parser("report", help="aggregate live telemetry JSONL")
    prep.add_argument("logs", nargs="+")
    prep.set_defaults(func=_cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
