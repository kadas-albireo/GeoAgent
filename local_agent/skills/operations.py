#!/usr/bin/env python3
"""Context-adaptive operations injection — thin delegate to the shipped guide.

The guide moved into the shipped package (``geoagent.core.operations_guide``) so the
KADAS/QGIS *plugin* can inject it too (the plugin cannot import ``local_agent``). This
module keeps the old import path working for the suite and the CLI preview; all real logic
lives in the shipped module, so there is a single source of truth
(``geoagent/core/kadas_operations_guide.md``).

Usage::

    python local_agent/skills/operations.py --max-tokens 400   # what a small model sees
    python local_agent/skills/operations.py                    # the whole guide
"""

from __future__ import annotations

from geoagent.core.operations_guide import (  # noqa: F401
    build_block,
    estimate_tokens,
    load_tiers,
    selected_tiers,
)


def build_operations_block(max_tokens: int | None = None, *, path=None) -> str:
    """Back-compat alias for :func:`geoagent.core.operations_guide.build_block`.

    ``path`` is accepted and ignored: the guide now has one shipped location.
    """
    return build_block(max_tokens)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Preview context-adaptive operations injection.")
    p.add_argument("--max-tokens", type=int, default=None)
    args = p.parse_args(argv)
    block = build_block(args.max_tokens)
    print(f"# tiers: {selected_tiers(args.max_tokens) or '(none fit)'}  "
          f"~{estimate_tokens(block)} tok\n")
    print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
