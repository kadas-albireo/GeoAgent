"""Make a backend ready with one call — the CLI-underneath for requirement #7.

Requirement #7 wants "things from LM Studio spun up from the UI (some command line
underneath)". The command line underneath already exists as two idempotent entry points in
the shipped package; this module is the thin unifying wrapper the suite CLI and, later, the
dock button call:

    - LM Studio: ``geoagent.core.lmstudio.ensure_model`` — starts the server, loads the
      model at a context large enough for the KADAS tool schemas, returns a config.

``ensure_model`` takes a ``progress`` callback, so a Qt dock can show status without this module
knowing anything about Qt. That is the whole "UI → CLI underneath" contract: the UI passes
a callback, we drive the same code the CLI drives.

Import-safe: no network at import; every path degrades to a clear error when the backend
(``lms`` CLI, ssh) is absent.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

Progress = Optional[Callable[[str], None]]

TARGETS = ("lmstudio",)


def provision(
    target: str,
    *,
    model: str | None = None,
    context_length: int | None = None,
    progress: Progress = None,
) -> Any:
    """Bring *target* to a ready state and return its ``GeoAgentConfig``.

    Args:
        target: ``"lmstudio"`` (alias ``"local"``).
        model: LM Studio model key. ``None`` uses whatever LM Studio has loaded, else the
            first tool-capable downloaded model.
        context_length: LM Studio load context. ``None`` requests the model's maximum —
            important, because LM Studio's 8192 default cannot hold the KADAS tool schemas.

    Raises:
        ValueError: unknown target.
        LMStudioError: backend not ready and not auto-fixable (see the error text).
    """
    _canonical(target)  # validates; only lmstudio is supported
    from geoagent.core.lmstudio import ensure_model

    return ensure_model(model, context_length=context_length, progress=progress)


def status() -> dict[str, Any]:
    """Return a snapshot of the backend, for ``suite status`` or a dock status line.

    Never raises: a backend that is not installed reports ``available: False`` rather than
    blowing up the whole status call.
    """
    return {"lmstudio": _lmstudio_status()}


def _canonical(target: str) -> str:
    t = target.strip().lower()
    if t in ("lmstudio", "local", "lms"):
        return "lmstudio"
    raise ValueError(f"unknown provision target {target!r}; use one of {TARGETS}")


def _lmstudio_status() -> dict[str, Any]:
    try:
        from geoagent.core.lmstudio import status as lms_status

        snap = lms_status()
        snap["available"] = snap.get("cli") is not None
        return snap
    except Exception as exc:  # import or probe failure → degrade, don't crash status
        return {"available": False, "error": str(exc)}
