"""Make a backend ready with one call — the CLI-underneath for requirement #7.

Requirement #7 wants "things from LM Studio spun up from the UI (some command line
underneath)". The command line underneath already exists as two idempotent entry points in
the shipped package; this module is the thin unifying wrapper the suite CLI and, later, the
dock button call:

    - LM Studio: ``geoagent.core.lmstudio.ensure_model`` — starts the server, loads the
      model at a context large enough for the KADAS tool schemas, returns a config.
    - ETH cluster: ``geoagent.core.eth_cluster.ensure_tunnel`` — adopts or opens the SSH
      forward to the Slurm node, returns the connection config.

Both take a ``progress`` callback, so a Qt dock can show status without this module
knowing anything about Qt. That is the whole "UI → CLI underneath" contract: the UI passes
a callback, we drive the same code the CLI drives.

Import-safe: no network at import; every path degrades to a clear error when the backend
(``lms`` CLI, ssh) is absent.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

Progress = Optional[Callable[[str], None]]

TARGETS = ("lmstudio", "eth")


def provision(
    target: str,
    *,
    model: str | None = None,
    context_length: int | None = None,
    progress: Progress = None,
) -> Any:
    """Bring *target* to a ready state and return its ``GeoAgentConfig``.

    Args:
        target: ``"lmstudio"`` (alias ``"local"``) or ``"eth"`` (alias ``"cluster"``).
        model: LM Studio model key. ``None`` uses whatever LM Studio has loaded, else the
            first tool-capable downloaded model. Ignored for ETH (the node serves one).
        context_length: LM Studio load context. ``None`` requests the model's maximum —
            important, because LM Studio's 8192 default cannot hold the KADAS tool schemas.

    Raises:
        ValueError: unknown target.
        LMStudioError / ConnectionError_: backend not ready and not auto-fixable (e.g. the
            ETH master session needs an interactive password — see the error text).
    """
    t = _canonical(target)
    if t == "lmstudio":
        from geoagent.core.lmstudio import ensure_model

        return ensure_model(
            model, context_length=context_length, progress=progress
        )
    from geoagent.core.eth_cluster import ensure_tunnel, geoagent_config

    ensure_tunnel(progress=progress)
    return geoagent_config()


def status() -> dict[str, Any]:
    """Return a snapshot of both backends, for ``suite status`` or a dock status line.

    Never raises: a backend that is not installed reports ``available: False`` rather than
    blowing up the whole status call.
    """
    return {"lmstudio": _lmstudio_status(), "eth": _eth_status()}


def _canonical(target: str) -> str:
    t = target.strip().lower()
    if t in ("lmstudio", "local", "lms"):
        return "lmstudio"
    if t in ("eth", "cluster", "eth-cluster", "ollama"):
        return "eth"
    raise ValueError(f"unknown provision target {target!r}; use one of {TARGETS}")


def _lmstudio_status() -> dict[str, Any]:
    try:
        from geoagent.core.lmstudio import status as lms_status

        snap = lms_status()
        snap["available"] = snap.get("cli") is not None
        return snap
    except Exception as exc:  # import or probe failure → degrade, don't crash status
        return {"available": False, "error": str(exc)}


def _eth_status() -> dict[str, Any]:
    try:
        from geoagent.core import eth_cluster

        cfg = eth_cluster.load_config()
        tunnel = eth_cluster.find_tunnel(cfg.local_fallback_port)
        serving = eth_cluster.is_serving(cfg.base_url) if tunnel else False
        return {
            "available": True,
            "mode": cfg.connection_mode,
            "base_url": cfg.base_url,
            "tunnel": bool(tunnel),
            "serving": serving,
            "node": tunnel.node if tunnel else cfg.active_slurm_node,
            "model": cfg.ollama_model,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}
