"""Enable ``python -m local_agent.suite ...``."""

from __future__ import annotations

from local_agent.suite.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
