"""LM Studio lifecycle: start the server and load a model on demand.

Lets a host (the KADAS/QGIS dock) offer a "Local qwen" option that *just works* without
the user first alt-tabbing to LM Studio, starting the server and loading a model with the
right context length. Mirrors :mod:`geoagent.core.openai_codex`, which does the analogous
environment setup for the ChatGPT/Codex provider.

Everything here shells out to the ``lms`` CLI that ships with LM Studio, then talks to its
OpenAI-compatible REST API. GeoAgent reaches the loaded model through the existing
``litellm`` provider, so no new model plumbing is involved::

    from geoagent.core.lmstudio import ensure_model
    from geoagent.core import factory

    config = ensure_model("qwen2.5-7b-instruct")   # starts server + loads if needed
    agent = factory.for_kadas(iface, project, config=config)

**Context length is the whole point of the ``context_length`` argument.** LM Studio loads
models at a conservative default (8192 for qwen2.5-7b, whose real maximum is 32768). The
KADAS tool schemas alone are ~10.6k tokens, so an 8192-token load *cannot fit the agent's
own prompt*. Always load explicitly; do not trust the default.

Import-safe with no LM Studio installed: every entry point degrades to a clear error
rather than raising at import time.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from geoagent.core.config import GeoAgentConfig

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_MODEL = "qwen2.5-7b-instruct"

# LM Studio never validates the key, but the OpenAI client refuses to build without one.
PLACEHOLDER_API_KEY = "lm-studio"

# Unload the model after this long idle, so a laptop GPU is not held hostage by a KADAS
# session the user finished with an hour ago.
DEFAULT_TTL_SECONDS = 3600

# Where LM Studio installs its CLI when it is not on PATH.
_LMS_FALLBACK_PATHS = (
    Path.home() / ".lmstudio" / "bin" / "lms",
    Path.home() / ".cache" / "lm-studio" / "bin" / "lms",
)


class LMStudioError(RuntimeError):
    """LM Studio is missing, unreachable, or refused an operation."""


def lms_path() -> Optional[str]:
    """Return the ``lms`` executable path, or None if LM Studio is not installed.

    Checks PATH first, then LM Studio's default install location -- the installer does not
    always add itself to PATH, and a GUI app launched from a desktop menu often has a
    narrower PATH than the user's shell anyway.
    """
    found = shutil.which("lms")
    if found:
        return found
    for candidate in _LMS_FALLBACK_PATHS:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _run(args: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess:
    """Run an ``lms`` subcommand, raising LMStudioError if the CLI is absent."""
    executable = lms_path()
    if not executable:
        raise LMStudioError(
            "LM Studio CLI ('lms') not found. Install LM Studio from "
            "https://lmstudio.ai and run `lms bootstrap`, or start the server manually."
        )
    return subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def is_server_running(
    base_url: str = DEFAULT_BASE_URL, *, timeout: float = 2.0
) -> bool:
    """True when the OpenAI-compatible endpoint answers.

    Probes the REST API rather than ``lms server status`` because the API is what actually
    has to work; the CLI can report a healthy server the client cannot reach.
    """
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def start_server(
    base_url: str = DEFAULT_BASE_URL, *, wait_seconds: float = 20.0
) -> None:
    """Start the LM Studio server if it is not already answering.

    Idempotent: returns immediately when the server is already up.

    Raises:
        LMStudioError: If the CLI is missing or the server does not come up in time.
    """
    if is_server_running(base_url):
        return

    result = _run(["server", "start"], timeout=30.0)
    if result.returncode != 0:
        raise LMStudioError(
            f"`lms server start` failed: {(result.stderr or result.stdout).strip()[:300]}"
        )

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if is_server_running(base_url):
            return
        time.sleep(0.5)
    raise LMStudioError(
        f"LM Studio server did not become reachable at {base_url} within {wait_seconds}s."
    )


def list_models(
    base_url: str = DEFAULT_BASE_URL, *, timeout: float = 5.0
) -> list[dict[str, Any]]:
    """Return LM Studio's native model listing.

    Uses the native ``/api/v0/models`` route, not the OpenAI-compatible ``/v1/models``:
    only the native one reports ``quantization``, ``max_context_length``,
    ``loaded_context_length``, ``capabilities`` and ``state``, all of which callers need
    to decide whether a model is usable.
    """
    native = base_url.rstrip("/")
    if native.endswith("/v1"):
        native = native[: -len("/v1")]
    try:
        with urllib.request.urlopen(
            f"{native}/api/v0/models", timeout=timeout
        ) as handle:
            return json.load(handle).get("data", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise LMStudioError(f"Could not list LM Studio models: {exc}") from exc


def model_info(
    model_key: str, base_url: str = DEFAULT_BASE_URL
) -> Optional[dict[str, Any]]:
    """Return the entry for *model_key*, or None if LM Studio does not have it."""
    for entry in list_models(base_url):
        if entry.get("id") == model_key:
            return entry
    return None


def supports_tools(entry: dict[str, Any]) -> bool:
    """True when the model advertises tool/function calling.

    A model without this cannot drive GeoAgent at all: it will describe the tool call in
    prose instead of emitting one. Worth checking before a user waits for a 5 GB load.
    """
    return "tool_use" in (entry.get("capabilities") or [])


def max_context_for(model_key: str, base_url: str = DEFAULT_BASE_URL) -> Optional[int]:
    """Return the model's maximum supported context length, if known."""
    entry = model_info(model_key, base_url)
    if not entry:
        return None
    value = entry.get("max_context_length")
    return int(value) if value else None


def loaded_model(
    base_url: str = DEFAULT_BASE_URL, *, require_tools: bool = True
) -> Optional[str]:
    """Return the model key LM Studio currently has loaded, or None.

    This is what makes "lmstudio" a zero-configuration choice in a host UI: the user has
    already picked a model in LM Studio, so asking them to retype its key into a second
    text field is pure ceremony (and a typo away from an error).

    Preference order is deliberate: an already-**loaded** model first (it costs nothing to
    use, where any other choice pays a multi-second load), then any downloaded model that
    can call tools. ``require_tools`` filters both stages, because a model without tool
    use cannot drive GeoAgent at all -- picking one automatically would hand the user an
    agent that only ever talks.

    Returns None when LM Studio has nothing usable; callers should raise with the listing
    rather than guessing.
    """
    try:
        entries = [m for m in list_models(base_url) if m.get("type") == "llm"]
    except LMStudioError:
        return None
    usable = [m for m in entries if not require_tools or supports_tools(m)]
    for entry in usable:
        if entry.get("state") == "loaded" and entry.get("id"):
            return str(entry["id"])
    return str(usable[0]["id"]) if usable and usable[0].get("id") else None


def is_loaded(model_key: str, base_url: str = DEFAULT_BASE_URL) -> bool:
    """True when *model_key* is loaded and ready to serve."""
    entry = model_info(model_key, base_url)
    return bool(entry) and entry.get("state") == "loaded"


def load_model(
    model_key: str = DEFAULT_MODEL,
    *,
    context_length: Optional[int] = None,
    gpu: Optional[str] = None,
    ttl_seconds: Optional[int] = DEFAULT_TTL_SECONDS,
    timeout: float = 300.0,
) -> None:
    """Load *model_key* into LM Studio.

    Args:
        context_length: Tokens of context. ``None`` asks for the model's advertised
            maximum, which is almost always what you want: LM Studio's default is
            conservative (8192 for qwen2.5-7b vs a real 32768 maximum) and the KADAS tool
            schemas alone are ~10.6k tokens, so the default cannot fit the agent's prompt.
        gpu: Offload ratio -- "max", "off", or 0..1. **Leave as None.** Passing ``max``
            looks like the safe choice ("keep it fully on the GPU") but it *overrides* LM
            Studio's automatic offload planning and makes borderline loads fail outright.
            Verified 2026-07-16 on a 6 GiB RTX 4050: ``--gpu max -c 32768`` failed with an
            opaque "Error loading model", while the identical load with no ``--gpu`` flag
            succeeded in 3.3s and sat at 5,479 MiB. LM Studio's estimator is conservative
            (it projected 6.15 GiB for a load that really used 5.35 GiB), so let it plan.
        ttl_seconds: Idle seconds before LM Studio unloads the model, freeing VRAM.
            ``None`` keeps it loaded indefinitely.

    Raises:
        LMStudioError: If the CLI is missing or the load fails (commonly: out of VRAM at
            the requested context length).
    """
    args = ["load", model_key, "--yes"]
    if gpu:
        args += ["--gpu", gpu]
    if context_length:
        args += ["--context-length", str(context_length)]
    if ttl_seconds:
        args += ["--ttl", str(ttl_seconds)]

    result = _run(args, timeout=timeout)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[:400]
        raise LMStudioError(
            f"Failed to load '{model_key}'"
            + (f" at context {context_length:,}" if context_length else "")
            + f": {message}\n\nIf this is an out-of-memory error, retry with a smaller "
            "context_length -- KV cache grows linearly with it."
        )


def unload_model(model_key: str) -> None:
    """Unload *model_key*, freeing its VRAM. Best-effort; never raises."""
    try:
        _run(["unload", model_key], timeout=30.0)
    except LMStudioError:
        pass


def config_for(
    model_key: str = DEFAULT_MODEL,
    *,
    base_url: str = DEFAULT_BASE_URL,
    **overrides: Any,
) -> GeoAgentConfig:
    """Build a GeoAgentConfig pointing at a loaded LM Studio model.

    The ``openai/`` prefix is a LiteLLM routing directive meaning "speak the OpenAI
    protocol to this endpoint", not part of the model name. Without it LiteLLM cannot
    infer the dialect.
    """
    return GeoAgentConfig(
        provider="litellm",
        model=f"openai/{model_key}",
        litellm_base_url=base_url,
        client_args={"api_key": PLACEHOLDER_API_KEY},
        **overrides,
    )


def ensure_model(
    model_key: Optional[str] = None,
    *,
    base_url: str = DEFAULT_BASE_URL,
    context_length: Optional[int] = None,
    gpu: Optional[str] = None,
    ttl_seconds: Optional[int] = DEFAULT_TTL_SECONDS,
    require_tools: bool = True,
    reload_if_smaller_context: bool = True,
    progress: Optional[Any] = None,
) -> GeoAgentConfig:
    """Bring LM Studio to a ready state and return a config bound to *model_key*.

    The single entry point a host UI needs. Idempotent and safe to call on every agent
    construction: if the server is up and the model is loaded at an adequate context, it
    does nothing but a couple of cheap HTTP probes.

    Steps: start the server -> resolve the model -> verify tool support -> load it at the
    requested context (or its maximum) -> return a litellm config.

    Args:
        model_key: ``None`` (default) uses whatever LM Studio has loaded, falling back to
            any downloaded tool-capable model. This is the host-UI path: the user already
            chose a model in LM Studio, so no second selection is needed.
        context_length: ``None`` (default) requests the model's advertised maximum.
        require_tools: Fail fast when the model cannot call tools, rather than letting
            the user discover it through an agent that only ever talks.
        reload_if_smaller_context: Reload when the model is already loaded but at a
            *smaller* context than requested. LM Studio's default load is often 8192,
            which cannot fit the KADAS tool schemas -- silently accepting it would look
            like a model quality problem rather than a configuration one.
        progress: Optional callable taking a status string, for a UI to display.

    Raises:
        LMStudioError: LM Studio missing, model absent, no tool support, or load failed.
    """

    def report(message: str) -> None:
        if callable(progress):
            progress(message)

    report("Starting LM Studio server...")
    start_server(base_url)

    if not model_key:
        model_key = loaded_model(base_url, require_tools=require_tools)
        if not model_key:
            raise LMStudioError(
                "LM Studio has no usable model"
                + (" with tool support" if require_tools else "")
                + ". Download one in LM Studio (a tool-capable instruct model such as "
                "qwen2.5-7b-instruct), or run: lms get " + DEFAULT_MODEL
            )
        report(f"Using LM Studio's model: {model_key}")

    entry = model_info(model_key, base_url)
    if entry is None:
        available = [
            str(m.get("id"))
            for m in list_models(base_url)
            if m.get("type") == "llm" and m.get("id")
        ]
        raise LMStudioError(
            f"Model '{model_key}' is not downloaded in LM Studio.\n"
            f"Available: {', '.join(available) or '(none)'}\n"
            f"Download it in LM Studio, or run: lms get {model_key}"
        )

    if require_tools and not supports_tools(entry):
        raise LMStudioError(
            f"Model '{model_key}' does not support tool calling "
            f"(capabilities: {entry.get('capabilities') or 'none'}). GeoAgent needs it: "
            "without tool use the model can only describe actions, not perform them."
        )

    target_context = context_length or entry.get("max_context_length")

    needs_load = entry.get("state") != "loaded"
    if not needs_load and reload_if_smaller_context and target_context:
        loaded = entry.get("loaded_context_length") or 0
        if loaded < int(target_context):
            report(f"Reloading at {int(target_context):,} context (was {loaded:,})...")
            unload_model(model_key)
            needs_load = True

    if needs_load:
        report(f"Loading {model_key} at {int(target_context or 0):,} context...")
        load_model(
            model_key,
            context_length=int(target_context) if target_context else None,
            gpu=gpu,
            ttl_seconds=ttl_seconds,
        )

    report(f"{model_key} ready.")
    return config_for(model_key, base_url=base_url)


def status(base_url: str = DEFAULT_BASE_URL) -> dict[str, Any]:
    """Return a diagnostic snapshot, for a UI status line or a bug report."""
    installed = lms_path()
    if not installed:
        return {"cli": None, "server": False, "models": []}
    if not is_server_running(base_url):
        return {"cli": installed, "server": False, "models": []}
    try:
        models = [
            {
                "id": m.get("id"),
                "state": m.get("state"),
                "quantization": m.get("quantization"),
                "max_context": m.get("max_context_length"),
                "loaded_context": m.get("loaded_context_length"),
                "tools": supports_tools(m),
            }
            for m in list_models(base_url)
            if m.get("type") == "llm"
        ]
    except LMStudioError:
        models = []
    return {"cli": installed, "server": True, "models": models}


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m geoagent.core.lmstudio [--ensure MODEL]``."""
    import argparse

    parser = argparse.ArgumentParser(description="Inspect or prepare LM Studio")
    parser.add_argument(
        "--ensure",
        metavar="MODEL",
        nargs="?",
        const="auto",
        help="Prepare a model; omit MODEL to use whichever one LM Studio has loaded.",
    )
    parser.add_argument("--context", type=int, default=None)
    args = parser.parse_args(argv)

    if args.ensure:
        try:
            config = ensure_model(
                None if args.ensure == "auto" else args.ensure,
                context_length=args.context,
                progress=print,
            )
        except LMStudioError as exc:
            print(f"error: {exc}")
            return 1
        print(f"ready: provider={config.provider} model={config.model}")
        return 0

    snapshot = status()
    if not snapshot["cli"]:
        print("LM Studio CLI not found (install from https://lmstudio.ai)")
        return 1
    print(f"cli    : {snapshot['cli']}")
    print(f"server : {'running' if snapshot['server'] else 'stopped'}")
    for model in snapshot["models"]:
        print(
            f"  {model['id']:42s} {model['state']:11s} "
            f"ctx {str(model['loaded_context'] or '-'):>6s}/{model['max_context']:<6} "
            f"tools={'yes' if model['tools'] else 'NO'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
