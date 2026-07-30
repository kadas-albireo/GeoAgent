"""local_agent.suite — the unified AI testing + debugging harness.

One package that ties together the pieces that used to live scattered across
``local_agent/`` and ``geoagent/core/``:

- :mod:`.agents`     — declarative multi-agent registry (Claude / LM Studio / ETH / …).
- :mod:`.provision`  — make a backend ready (start LM Studio, bring up the ETH tunnel).
- :mod:`.budget`     — adapt the tool surface + doc injection to a model's context window.
- :mod:`.cost`       — token → USD estimation (prices are unverified priors; see the file).
- :mod:`.runner`     — run a scenario across agents, **headless** (mock hosts) or in KADAS.
- :mod:`.report`     — aggregate telemetry into a token / cost / latency / context table.
- :mod:`.cli`        — a single entry point: ``python -m local_agent.suite <cmd>``.

Design rules (inherited from ``local_agent/CLAUDE.md``):

- **Nothing here is imported by the shipped ``geoagent`` package or the plugins.** This
  scope may import *from* ``geoagent``; the reverse is forbidden.
- **Import-safe without QGIS/KADAS.** Modules must import with no ``qgis`` present; QGIS
  symbols are imported lazily inside function bodies. This keeps ``budget``/``cost``/
  ``report`` runnable on any box and unit-testable in CI.
- **Reuse, don't duplicate.** This layer orchestrates existing modules
  (``geoagent.core.lmstudio``, ``geoagent.core.eth_cluster``, ``geoagent.core.context_docs``,
  ``local_agent.skills.selector``, ``local_agent.telemetry.tracker``,
  ``local_agent.tests.evaluators``) rather than reimplementing them.
"""

from __future__ import annotations

__all__ = ["agents", "budget", "cost", "provision", "report", "runner"]
