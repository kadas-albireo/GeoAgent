#!/usr/bin/env python3
"""Connection config + SSH tunnel manager for the ETH open-source cloud model.

Local machine runs KADAS/QGIS, the eval runner, screenshots and telemetry. The model runs
on an ETH D-INFK Slurm GPU node. An SSH local-forward bridges them::

    localhost:11434  ->  student-cluster2.inf.ethz.ch  ->  <slurm-node>:11434

Once forwarded, the remote server *looks local*, so the model plumbing is just ollama
pointed at ``http://localhost:11434``. This module manages the bridge; the
``eth-cluster`` provider in :mod:`geoagent.core.model` calls :func:`ensure_tunnel` and
then hands off to the ollama client. It mirrors :mod:`geoagent.core.lmstudio`, which does
the analogous "make it work without me setting it up" job for the local provider.

Standard library only, and import-safe with no ssh/cluster present: every entry point
degrades to a clear error rather than raising at import time.

Design notes, all from measurements against the live cluster (2026-07-16):

- **The Slurm node is dynamic.** ``active_slurm_node`` in config.json is a *cache*, not a
  fact: Slurm hands out a different node on each allocation, and a stale value produces a
  tunnel that connects and then refuses every request. :func:`discover_node` asks squeue.
- **An existing tunnel is adopted, never killed.** A hand-rolled ``ssh -L`` (exactly how
  this was first set up) is a perfectly good tunnel. Tearing down someone's working
  session to replace it with an identical one is hostile; ``up()`` detects and reuses.
- **Latency is a non-issue here.** Measured median round-trip through the tunnel: 7.6 ms.
  At ~6 model calls per agent turn that is ~45 ms total. Do not optimize it.

Usage::

    python -m geoagent.core.eth_cluster status
    python -m geoagent.core.eth_cluster login      # password once, reused for 8h
    python -m geoagent.core.eth_cluster up         # discover node, tunnel, verify
    python -m geoagent.core.eth_cluster down
    python -m geoagent.core.eth_cluster doctor     # diagnose a broken pipeline
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


# A *user* config path, not one next to this file: this module now ships inside the
# geoagent package, which lands in a venv's site-packages (read-only in principle, and
# blown away on every reinstall). $GEOAGENT_ETH_CONFIG overrides, which is what the eval
# runner and tests use.
def config_path() -> Path:
    """Where the connection config lives."""
    override = os.environ.get("GEOAGENT_ETH_CONFIG", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return Path(os.path.expanduser("~/.config/geoagent/eth_cluster.json"))


# Modes:
#   local       model served on this machine (LM Studio). No tunnel.
#   eth_hybrid  model on an ETH Slurm node, reached through an SSH local-forward.
CONNECTION_MODES = ("local", "eth_hybrid")


class ConnectionError_(RuntimeError):
    """The tunnel or the remote model server is unusable."""


@dataclass
class ConnectionConfig:
    """Persisted connection state (see :func:`config_path`)."""

    connection_mode: str = "eth_hybrid"
    eth_username: str = "achurchill"
    eth_login_host: str = "student-cluster2.inf.ethz.ch"
    # Cache of the last-known Slurm node. Refreshed by discover_node(); a stale value is
    # the single most common cause of "tunnel is up but nothing answers".
    active_slurm_node: str = "studgpu-node01"
    local_fallback_port: int = 11434
    remote_port: int = 11434
    # Only used if the key is actually authorized on the cluster. Verified 2026-07-16:
    # ~/.ssh/id_ed25519 is loaded in ssh-agent but is NOT accepted by
    # student-cluster2 ("Permission denied (publickey,password)") -- the cluster is
    # password-authenticated here. Hence control_path below.
    ssh_key_path: str = "~/.ssh/id_ed25519"
    # SSH connection multiplexing socket. This is what makes automation possible without
    # key auth: `eth_cluster login` authenticates ONCE (password typed at a terminal) and
    # leaves a master connection behind; every later ssh -- squeue, tunnel -- rides that
    # socket needing no credentials. Without it, BatchMode ssh cannot type a password and
    # every automated path fails.
    control_path: str = "~/.ssh/cm-geoagent-%r@%h-%p"
    # Model to use in eth_hybrid mode. MUST advertise tool support AND actually emit
    # Qwen's <tool_call> delimiters -- see the note in doctor().
    ollama_model: str = "qwen2.5:7b-instruct"

    @property
    def ssh_target(self) -> str:
        """``user@login-host``."""
        return f"{self.eth_username}@{self.eth_login_host}"

    @property
    def base_url(self) -> str:
        """Where the forwarded model server appears locally."""
        return f"http://localhost:{self.local_fallback_port}"

    def key_path(self) -> Path:
        """Expanded SSH key path."""
        return Path(os.path.expanduser(self.ssh_key_path))

    def control_socket(self) -> str:
        """Expanded ControlPath template (ssh expands the %r/%h/%p tokens itself)."""
        return os.path.expanduser(self.control_path)

    def master_socket(self) -> Path:
        """The concrete socket path for this target, for existence checks."""
        resolved = (
            self.control_socket()
            .replace("%r", self.eth_username)
            .replace("%h", self.eth_login_host)
            .replace("%p", "22")
        )
        return Path(resolved)


def load_config(path: Path | None = None) -> ConnectionConfig:
    """Load config.json, falling back to defaults for anything absent.

    Unknown keys are ignored rather than fatal, so an older/newer file still loads.
    """
    target = path or config_path()
    if not target.exists():
        return ConnectionConfig()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ConnectionConfig()
    known = {f for f in ConnectionConfig.__dataclass_fields__}
    return ConnectionConfig(**{k: v for k, v in raw.items() if k in known})


def save_config(config: ConnectionConfig, path: Path | None = None) -> Path:
    """Write config.json."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    return target


# -- Tunnel discovery / lifecycle --------------------------------------------


@dataclass
class TunnelInfo:
    """A running ``ssh -L`` process serving our local port."""

    pid: int
    local_port: int
    node: str
    remote_port: int
    command: str
    managed: bool = False  # started by this module (vs adopted from the user's shell)


def _ssh_processes() -> list[tuple[int, str]]:
    """Return ``(pid, command)`` for every ssh process owned by this user."""
    try:
        out = subprocess.run(
            ["ps", "-o", "pid=,args=", "-u", str(os.getuid())],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, args = line.partition(" ")
        if "ssh " in f" {args}" and "-L" in args:
            try:
                rows.append((int(pid), args.strip()))
            except ValueError:
                continue
    return rows


def find_tunnel(local_port: int = 11434) -> Optional[TunnelInfo]:
    """Return the ssh forward serving *local_port*, or None.

    Parses ``-L <local>:<node>:<remote>`` out of the command line, so a tunnel started by
    hand in a terminal is found exactly like one this module started. That is deliberate:
    the pipeline was originally set up with a bare ``ssh -L ...`` and that must keep
    working rather than be treated as a conflict.
    """
    pattern = re.compile(rf"-L\s*(?:\S*:)?{local_port}:([^:\s]+):(\d+)")
    for pid, command in _ssh_processes():
        match = pattern.search(command)
        if match:
            return TunnelInfo(
                pid=pid,
                local_port=local_port,
                node=match.group(1),
                remote_port=int(match.group(2)),
                command=command,
            )
    return None


def is_serving(base_url: str, *, timeout: float = 5.0) -> bool:
    """True when an ollama server answers at *base_url*."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def list_models(base_url: str, *, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Return the models the (tunnelled) ollama server has pulled."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as handle:
            return json.load(handle).get("models", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ConnectionError_(f"Could not list models at {base_url}: {exc}") from exc


def has_master(config: ConnectionConfig) -> bool:
    """True when a multiplexed master connection is alive for this target."""
    result = subprocess.run(
        [
            "ssh",
            "-O",
            "check",
            "-o",
            f"ControlPath={config.control_socket()}",
            config.ssh_target,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def start_master(config: ConnectionConfig, *, timeout: float = 180.0) -> None:
    """Open a multiplexed master connection, prompting for a password if needed.

    **Requires a terminal** -- this is the one interactive step, and it exists because the
    cluster does not accept our key (verified: ``Permission denied (publickey,password)``
    for ~/.ssh/id_ed25519). After this, ``squeue`` and the tunnel run unattended over the
    same socket.

    Deliberately does NOT pass BatchMode: the whole point is to let ssh ask for the
    password once.
    """
    socket = config.control_socket()
    Path(os.path.expanduser("~/.ssh")).mkdir(parents=True, exist_ok=True)
    command = [
        "ssh",
        "-M",  # become the master
        "-f",  # background once authenticated
        "-N",  # no remote command
        "-o",
        f"ControlPath={socket}",
        "-o",
        "ControlPersist=8h",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ServerAliveInterval=30",
        config.ssh_target,
    ]
    result = subprocess.run(command, timeout=timeout, check=False)
    if result.returncode != 0 or not has_master(config):
        raise ConnectionError_(
            f"Could not open a master connection to {config.ssh_target}.\n"
            "Run this yourself in a terminal (it will prompt for your password):\n"
            f"  {' '.join(command)}"
        )


def _ssh_base(config: ConnectionConfig) -> list[str]:
    """Common ssh args: reuse the master socket, no prompting, keepalives.

    Order of preference is deliberate:

    1. **ControlPath** -- ride an existing authenticated master. The only thing that works
       here, since the cluster rejects our key and BatchMode cannot type a password.
    2. **-i key** -- used when the key is genuinely authorized (other clusters, CI).

    ``BatchMode=yes`` keeps automated calls from hanging on a password prompt when neither
    is available: they fail fast with a message instead of blocking a GUI forever.
    """
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ControlPath={config.control_socket()}",
    ]
    key = config.key_path()
    if key.exists():
        args += ["-i", str(key)]
    return args


_AUTH_HINT = (
    "\nSSH could not authenticate without a prompt. Either:\n"
    "  1. Open a shared connection once (password typed once, reused for 8h):\n"
    "       python -m geoagent.core.eth_cluster login\n"
    "  2. Or authorize your key so nothing is interactive:\n"
    "       ssh-copy-id -i ~/.ssh/id_ed25519.pub {target}\n"
)


def discover_node(config: ConnectionConfig, *, timeout: float = 30.0) -> Optional[str]:
    """Ask Slurm which node this user's job is on. None when no job is running.

    ``squeue -u <user> -h -o %N`` prints the allocated node list for running jobs. This is
    the authoritative answer; ``config.active_slurm_node`` is only a cache of it, and a
    reservation that has been requeued will hand back a different node with no warning.
    """
    if not shutil.which("ssh"):
        raise ConnectionError_("ssh not found on PATH")
    command = _ssh_base(config) + [
        config.ssh_target,
        f"squeue -u {config.eth_username} -h -o '%N' -t RUNNING",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError_(
            f"Timed out asking {config.eth_login_host} for the Slurm node."
        ) from exc
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        if "Permission denied" in stderr or "publickey" in stderr:
            raise ConnectionError_(
                f"Cannot authenticate to {config.eth_login_host} non-interactively."
                + _AUTH_HINT.format(target=config.ssh_target)
            )
        raise ConnectionError_(
            f"squeue failed on {config.eth_login_host}: {stderr[:200]}"
        )
    nodes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not nodes:
        return None
    # A node list can be a range expression ("studgpu-node[01-02]"); take the first.
    first = nodes[0]
    match = re.match(r"([a-z0-9-]+?)\[(\d+)", first)
    return f"{match.group(1)}{match.group(2)}" if match else first


def start_tunnel(
    config: ConnectionConfig, node: str, *, wait_seconds: float = 20.0
) -> TunnelInfo:
    """Start a background ``ssh -N -L`` forward to *node* and wait for it to serve.

    ``-N`` (no remote command) is what makes this a pure forward rather than an
    interactive shell. ``ExitOnForwardFailure`` turns a port clash into an immediate
    non-zero exit instead of a tunnel that connects but forwards nothing.
    """
    command = _ssh_base(config) + [
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-L",
        f"{config.local_fallback_port}:{node}:{config.remote_port}",
        config.ssh_target,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = (process.stderr.read().decode() if process.stderr else "").strip()
            if "Permission denied" in stderr or "publickey" in stderr:
                raise ConnectionError_(
                    f"Cannot authenticate to {config.eth_login_host} non-interactively."
                    + _AUTH_HINT.format(target=config.ssh_target)
                )
            raise ConnectionError_(
                f"ssh exited immediately: {stderr[:300] or 'no error output'}"
            )
        if is_serving(config.base_url, timeout=2.0):
            return TunnelInfo(
                pid=process.pid,
                local_port=config.local_fallback_port,
                node=node,
                remote_port=config.remote_port,
                command=" ".join(command),
                managed=True,
            )
        time.sleep(0.5)

    process.terminate()
    raise ConnectionError_(
        f"Tunnel to {node} did not serve {config.base_url} within {wait_seconds:.0f}s. "
        "Is ollama running on that node?"
    )


def stop_tunnel(tunnel: TunnelInfo) -> None:
    """Terminate a tunnel process."""
    try:
        os.kill(tunnel.pid, 15)
    except (ProcessLookupError, PermissionError) as exc:
        raise ConnectionError_(f"Could not stop pid {tunnel.pid}: {exc}") from exc


def up(
    config: ConnectionConfig | None = None, *, force_restart: bool = False
) -> TunnelInfo:
    """Ensure a working tunnel and return it. Idempotent.

    Order matters: an existing, *serving* tunnel is adopted before any attempt to
    discover a node or start ssh. That keeps this fast in the common case and, more
    importantly, means running this never disturbs a tunnel the user set up by hand.

    Args:
        force_restart: Tear down an existing tunnel and rebuild it. Use when the Slurm
            node changed under a still-running forward.
    """
    cfg = config or load_config()
    if cfg.connection_mode != "eth_hybrid":
        raise ConnectionError_(
            f"connection_mode is {cfg.connection_mode!r}, not 'eth_hybrid'. "
            "In local mode the model is served by LM Studio; no tunnel is needed."
        )

    existing = find_tunnel(cfg.local_fallback_port)
    if existing and not force_restart:
        if is_serving(cfg.base_url):
            return existing
        # Connected but dead: almost always a stale node after a Slurm reallocation.
        raise ConnectionError_(
            f"A tunnel to {existing.node} (pid {existing.pid}) holds port "
            f"{cfg.local_fallback_port} but nothing answers at {cfg.base_url}.\n"
            "The Slurm node has probably changed. Re-run with --force to rebuild it, "
            "or stop that ssh process yourself."
        )
    if existing and force_restart:
        stop_tunnel(existing)
        time.sleep(1.0)

    node = discover_node(cfg)
    if not node:
        raise ConnectionError_(
            f"No RUNNING Slurm job for {cfg.eth_username}. Start your allocation "
            "(e.g. srun/sbatch with the GPU reservation) before opening the tunnel."
        )
    if node != cfg.active_slurm_node:
        cfg.active_slurm_node = node
        save_config(cfg)

    return start_tunnel(cfg, node)


def down(config: ConnectionConfig | None = None) -> bool:
    """Stop the tunnel serving our port. Returns False if there was none."""
    cfg = config or load_config()
    tunnel = find_tunnel(cfg.local_fallback_port)
    if not tunnel:
        return False
    stop_tunnel(tunnel)
    return True


def ensure_tunnel(
    config: ConnectionConfig | None = None,
    *,
    progress: Optional[Any] = None,
) -> ConnectionConfig:
    """Bring the tunnel to a serving state and return the config describing it.

    The single entry point a host UI or provider needs, and the analogue of
    :func:`geoagent.core.lmstudio.ensure_model`. Idempotent and cheap in the common case:
    a serving tunnel is adopted after one HTTP probe.

    The one thing this deliberately will NOT do is authenticate. Opening the master
    connection needs a password typed at a terminal (the cluster rejects our key), and a
    Qt dock has no terminal: prompting from a GUI thread would hang the application with
    an invisible prompt. So a missing master is an immediate, actionable error instead.

    Raises:
        ConnectionError_: Wrong mode, no master connection, no Slurm job, or no tunnel.
    """

    def report(message: str) -> None:
        if callable(progress):
            progress(message)

    cfg = config or load_config()
    if cfg.connection_mode != "eth_hybrid":
        raise ConnectionError_(
            f"connection_mode is {cfg.connection_mode!r}, not 'eth_hybrid'. "
            "Set it in the config, or use the 'lmstudio' provider for a local model."
        )

    report("Checking the ETH tunnel...")
    existing = find_tunnel(cfg.local_fallback_port)
    if existing and is_serving(cfg.base_url):
        report(f"Tunnel up: {cfg.base_url} -> {existing.node}:{existing.remote_port}")
        return cfg

    if not has_master(cfg):
        raise ConnectionError_(
            f"No authenticated SSH session for {cfg.ssh_target}, and one cannot be "
            "opened from the GUI (the cluster requires a password).\n\n"
            "Run this once in a terminal (it persists 8h):\n"
            "  python -m geoagent.core.eth_cluster login"
        )

    report("Discovering the Slurm node...")
    tunnel = up(cfg, force_restart=bool(existing))
    report(f"Tunnel up: {cfg.base_url} -> {tunnel.node}:{tunnel.remote_port}")
    return cfg


def geoagent_config(config: ConnectionConfig | None = None) -> Any:
    """Return a GeoAgentConfig bound to the model this connection exposes.

    eth_hybrid -> the ``eth-cluster`` provider, which opens the tunnel and then speaks
    ollama to the forwarded port. local -> LM Studio.
    """
    cfg = config or load_config()
    from geoagent.core.config import GeoAgentConfig

    if cfg.connection_mode == "eth_hybrid":
        return GeoAgentConfig(provider="eth-cluster", model=cfg.ollama_model)
    return GeoAgentConfig(provider="lmstudio")


# -- Diagnostics --------------------------------------------------------------


def model_emits_tool_calls(
    base_url: str, model: str, *, timeout: float = 120.0
) -> tuple[bool, str]:
    """Probe whether *model* actually returns structured tool calls.

    Advertising ``tools`` in /api/show is **not** sufficient, and this check exists
    because of a real failure: ``qwen2.5-coder:7b`` reports ``capabilities: [tools]`` and
    then answers with the correct call as *plain text* --

        content: '{"name": "get_weather", "arguments": {"city": "Zurich"}}'
        tool_calls: None

    -- because it omits the ``<tool_call></tool_call>`` delimiters its own chat template
    demands, so ollama parses nothing out. The agent then silently does nothing all day.
    Coder fine-tunes are prone to this; instruct models are the safe pick.

    Returns:
        ``(ok, detail)``.
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "What is the weather in Zurich?"}],
        "tools": tools,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as handle:
            message = json.load(handle).get("message", {})
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return False, f"probe failed: {exc}"

    if message.get("tool_calls"):
        return True, f"emitted {len(message['tool_calls'])} structured tool call(s)"
    content = str(message.get("content") or "")
    if '"name"' in content and '"arguments"' in content:
        return False, (
            "model returned the call as PLAIN TEXT, not a structured tool_call -- it is "
            "omitting the <tool_call> delimiters its template requires. Use an instruct "
            "model (e.g. qwen2.5:7b-instruct), not a coder fine-tune."
        )
    return False, f"no tool call; replied with prose: {content[:120]!r}"


# -- GPU probe + model management --------------------------------------------
#
# The point: the Slurm node's GPU is dynamic and its VRAM decides which model is worth
# running. `probe` reads the card over the shared SSH connection; `recommend` maps VRAM to
# a model; `pull`/`use` download and select it on the node. All of this rides the same
# master socket as the tunnel, so it needs no extra authentication once `login` has run.


def _ssh_capture(
    config: ConnectionConfig, remote_command: str, *, timeout: float, what: str
) -> str:
    """Run *remote_command* on the login host over the master socket; return stdout.

    Raises ConnectionError_ with the auth hint when the master is missing, matching
    discover_node's behaviour so every remote call fails the same, actionable way.
    """
    if not shutil.which("ssh"):
        raise ConnectionError_("ssh not found on PATH")
    command = _ssh_base(config) + [config.ssh_target, remote_command]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError_(f"Timed out {what} on {config.eth_login_host}.") from exc
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        if "Permission denied" in stderr or "publickey" in stderr:
            raise ConnectionError_(
                f"Cannot authenticate to {config.eth_login_host} non-interactively."
                + _AUTH_HINT.format(target=config.ssh_target)
            )
        raise ConnectionError_(f"{what} failed: {stderr[:200]}")
    return result.stdout


@dataclass
class GpuInfo:
    """One GPU on the compute node."""

    name: str
    total_mib: int
    free_mib: int

    @property
    def total_gib(self) -> float:
        return round(self.total_mib / 1024, 1)

    @property
    def free_gib(self) -> float:
        return round(self.free_mib / 1024, 1)


def probe_gpu(config: ConnectionConfig | None = None, *, timeout: float = 45.0) -> list[GpuInfo]:
    """Return the GPUs on the current Slurm node (via login host → node → nvidia-smi).

    Uses ``discover_node`` for the live node (never the cached value), then runs
    ``nvidia-smi`` there through a nested ssh. Empty list means the query worked but
    reported no GPU (a CPU node, or the allocation ended).
    """
    cfg = config or load_config()
    node = discover_node(cfg) or cfg.active_slurm_node
    query = (
        "nvidia-smi --query-gpu=name,memory.total,memory.free "
        "--format=csv,noheader,nounits"
    )
    # ssh login-host -> ssh node -> nvidia-smi. BatchMode so a node that needs a password
    # fails fast rather than hanging the GUI.
    remote = f"ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new {node} '{query}'"
    out = _ssh_capture(cfg, remote, timeout=timeout, what=f"probing GPU on {node}")
    gpus: list[GpuInfo] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            gpus.append(GpuInfo(parts[0], int(parts[1]), int(parts[2])))
    return gpus


@dataclass
class ModelRec:
    """A recommended model for a VRAM budget."""

    model: str  # ollama tag to `ollama pull`
    approx_vram_gib: float
    reason: str


# VRAM tier → ordered recommendations, best first. Qwen-family lead because they emit
# structured <tool_call> delimiters reliably, which this pipeline requires (see
# model_emits_tool_calls / doctor). PROVENANCE: model names/sizes are unverified priors
# from a 2026-07 web scan (sources in local_agent/RUNBOOK.md); tags drift, so `ollama pull`
# may need a nearby tag. The only authority is your own eval sweep — verify with the suite.
_MODEL_TIERS: list[tuple[float, list[ModelRec]]] = [
    (16, [
        ModelRec("qwen3:8b", 8, "Native tool-calling, snappy for ReAct loops; fits <16 GiB."),
        ModelRec("qwen2.5:7b-instruct", 6, "The current default; proven in this pipeline."),
    ]),
    (32, [
        ModelRec("qwen3-coder:30b", 19, "30B MoE (~3.3B active) — best quality per GiB at Q4."),
        ModelRec("qwen3:30b-a3b", 19, "30B MoE general; stays usable thanks to ~3B active params."),
    ]),
    (48, [
        ModelRec("qwen3.6:27b", 24, "Strong SWE-bench + reliable tool calls; 128k context headroom."),
        ModelRec("qwen3:32b", 20, "Dense 32B; steadier than 70B for strict tool-call schemas."),
    ]),
    (80, [
        ModelRec("llama3.3:70b", 43, "General workhorse; fits ~48 GiB+ at Q4."),
        ModelRec("qwen3.6:27b", 24, "Run at higher precision / long context if you prefer Qwen tool calls."),
    ]),
    (float("inf"), [
        ModelRec("llama3.3:70b", 43, "Comfortable at 80 GiB with long context."),
        ModelRec("deepseek-r1:70b", 43, "Reasoning distill; slightly less steady on strict tool schemas."),
    ]),
]


def recommend_models(vram_gib: float) -> list[ModelRec]:
    """Best-first model recommendations for a GPU with *vram_gib* of VRAM.

    Pure function (no SSH) so it is unit-testable. Picks the highest tier whose ceiling the
    VRAM clears, leaving ~20% headroom for the KV cache at a useful context length.
    """
    usable = vram_gib * 0.8
    for ceiling, recs in _MODEL_TIERS:
        if usable <= ceiling:
            return recs
    return _MODEL_TIERS[-1][1]


def installed_models(config: ConnectionConfig | None = None, *, timeout: float = 10.0) -> list[str]:
    """Model tags already pulled on the node's ollama server (via the forwarded port)."""
    cfg = config or load_config()
    return [str(m.get("name") or m.get("model") or m.get("id")) for m in list_models(cfg.base_url, timeout=timeout)]


def pull_model(
    config: ConnectionConfig | None, model: str, *, timeout: float = 3600.0,
    progress: Optional[Any] = None,
) -> None:
    """Run ``ollama pull <model>`` on the Slurm node. Long-running (multi-GB download)."""
    cfg = config or load_config()
    node = discover_node(cfg) or cfg.active_slurm_node
    if callable(progress):
        progress(f"Pulling {model} on {node} (this can take minutes)...")
    remote = f"ssh -o BatchMode=yes {node} 'ollama pull {model}'"
    _ssh_capture(cfg, remote, timeout=timeout, what=f"pulling {model} on {node}")


def use_model(config: ConnectionConfig | None, model: str) -> ConnectionConfig:
    """Persist *model* as the eth_hybrid model and return the updated config."""
    cfg = config or load_config()
    cfg.ollama_model = model
    save_config(cfg)
    return cfg


def report(config: ConnectionConfig | None = None) -> dict[str, Any]:
    """A snapshot for `eth_cluster probe` / a dock status line. Never raises."""
    cfg = config or load_config()
    snap: dict[str, Any] = {"node": cfg.active_slurm_node, "configured_model": cfg.ollama_model}
    try:
        snap["node"] = discover_node(cfg) or cfg.active_slurm_node
    except ConnectionError_ as exc:
        snap["error"] = str(exc)
        return snap
    try:
        snap["gpus"] = [
            {"name": g.name, "total_gib": g.total_gib, "free_gib": g.free_gib}
            for g in probe_gpu(cfg)
        ]
        if snap["gpus"]:
            best = max(snap["gpus"], key=lambda g: g["total_gib"])
            snap["recommended"] = [
                {"model": r.model, "approx_vram_gib": r.approx_vram_gib, "reason": r.reason}
                for r in recommend_models(best["total_gib"])
            ]
    except ConnectionError_ as exc:
        snap["gpu_error"] = str(exc)
    try:
        snap["installed_models"] = installed_models(cfg)
    except Exception as exc:  # server may not be reachable without the tunnel up
        snap["installed_models_error"] = str(exc)
    return snap


# -- Performance benchmark ----------------------------------------------------
#
# "Why is the agent slow" is answerable with numbers, not guesses. ollama's /api/generate
# returns timings that separate the two costs that matter:
#
#   prompt_eval_*  -> PREFILL: reading the prompt (system + ~10.6k tool schemas + history).
#                    Paid on EVERY model call in a turn; a turn is ~4-6 calls.
#   eval_*         -> GENERATION: producing the answer tokens. Memory-bandwidth bound, so
#                    a 70B on unified LPDDR (GB10) is inherently a few tok/s.
#
# load_duration > 0 means the model was NOT resident and had to be re-read from disk (tens
# of GB) -- the single worst, and most fixable, cause of a slow turn.


def _ollama_generate(
    base_url: str, model: str, prompt: str, *, num_predict: int = 48,
    keep_alive: str = "10m", timeout: float = 600.0,
) -> dict[str, Any]:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"num_predict": num_predict},
    }).encode()
    request = urllib.request.Request(
        f"{base_url}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as handle:
        return json.load(handle)


def ps(base_url: str, *, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Loaded (resident) models: size_vram, context, expiry. Empty if none loaded."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/ps", timeout=timeout) as handle:
            return json.load(handle).get("models", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []


def _rate(count: Any, duration_ns: Any) -> float:
    """tokens/sec from an ollama count + nanosecond duration."""
    try:
        secs = float(duration_ns) / 1e9
        return round(float(count) / secs, 1) if secs > 0 else 0.0
    except (TypeError, ZeroDivisionError, ValueError):
        return 0.0


def bench(
    base_url: str, model: str, *, filler_tokens: int = 2000, timeout: float = 600.0
) -> dict[str, Any]:
    """Measure prefill and generation speed, and whether the model is resident.

    Two calls: a warmup (loads the model, so the real numbers exclude load time), then a
    ~*filler_tokens* prompt that stands in for the tool-schema prefill the agent pays every
    call. No agent, no tools -- just the raw model speed the agent is bounded by.
    """
    out: dict[str, Any] = {"base_url": base_url, "model": model}
    # Warmup: pays the load cost so the measured call reflects a resident model.
    _ollama_generate(base_url, model, "Say OK.", num_predict=4, timeout=timeout)

    filler = ("The quick brown fox jumps over the lazy dog. " * (filler_tokens // 10 + 1))
    result = _ollama_generate(base_url, model, filler, num_predict=48, timeout=timeout)

    out["prefill_tok_per_s"] = _rate(
        result.get("prompt_eval_count"), result.get("prompt_eval_duration")
    )
    out["gen_tok_per_s"] = _rate(result.get("eval_count"), result.get("eval_duration"))
    out["load_seconds"] = round(float(result.get("load_duration", 0)) / 1e9, 2)
    out["prompt_eval_count"] = result.get("prompt_eval_count")
    out["eval_count"] = result.get("eval_count")

    # Cache-reuse probe: resend the SAME filler plus a few tokens. If the KV/prompt cache
    # is working, ollama prefills only the appended tokens (prompt_eval_count tiny); if the
    # cache is busted (keep_alive eviction, num_ctx overflow, slot churn), it re-prefills
    # the whole thing. This is the direct test of "am I paying for the prefix every call?".
    pe_first = int(result.get("prompt_eval_count") or 0)
    second = _ollama_generate(
        base_url, model, filler + " Now continue.", num_predict=8, timeout=timeout
    )
    pe_second = int(second.get("prompt_eval_count") or 0)
    out["prefill_count_first"] = pe_first
    out["prefill_count_second"] = pe_second
    # Reused when the second call re-evaluated far fewer tokens than the shared prefix.
    out["prefix_cache_reused"] = bool(
        pe_first and pe_second and pe_second < pe_first * 0.5
    )

    loaded = ps(base_url)
    if loaded:
        entry = loaded[0]
        out["resident"] = True
        out["size_vram_gib"] = round(int(entry.get("size_vram", 0)) / 1024**3, 1)
        out["expires_at"] = entry.get("expires_at")
        details = entry.get("details") or {}
        out["quant"] = details.get("quantization_level")
        # Newer ollama reports the loaded context window here.
        for key in ("context_length", "context", "num_ctx"):
            if key in entry:
                out["loaded_context"] = entry[key]
                break
    else:
        out["resident"] = False
    return out


def _bench_diagnosis(b: dict[str, Any]) -> list[str]:
    """Turn the raw numbers into ordered, actionable findings (biggest lever first)."""
    notes: list[str] = []
    gen = b.get("gen_tok_per_s") or 0
    prefill = b.get("prefill_tok_per_s") or 0

    if b.get("load_seconds", 0) > 1.0:
        notes.append(
            f"model was RELOADED from disk (load {b['load_seconds']}s) — it is not staying "
            "resident. Set keep_alive so it is not re-read every call: on the node run "
            "`OLLAMA_KEEP_ALIVE=-1 ollama serve`, or pass keep_alive:-1 per request."
        )
    if gen and gen < 8:
        notes.append(
            f"generation is {gen} tok/s — memory-bandwidth bound. A 70B on GB10 unified "
            "memory is inherently a few tok/s. The biggest win is a smaller model: "
            "`qwen2.5-coder:32b` (or a 7-8B) is typically 3-6x faster and, per this repo, "
            "more reliable at strict tool-calling. `eth_cluster use qwen2.5-coder:32b`."
        )
    if prefill:
        tool_prefill_s = round(10600 / prefill, 1)
        reused = b.get("prefix_cache_reused")
        if reused is False:
            # The bad case: the prefix is NOT cached, so the tool schemas ARE re-read every call.
            notes.append(
                f"prompt cache is NOT being reused: the second call re-prefilled "
                f"{b.get('prefill_count_second')} of {b.get('prefill_count_first')} tokens. So the "
                f"~10.6k tool schemas ARE re-read every call (~{tool_prefill_s}s each, ~5 calls/turn). "
                "This is the thing to fix — it is caused by keep_alive eviction, num_ctx too small, "
                "or num_parallel>1, not by the model itself. Set OLLAMA_KEEP_ALIVE=-1, "
                "OLLAMA_NUM_PARALLEL=1, and num_ctx large enough for tools+history."
            )
        elif reused:
            notes.append(
                f"prompt cache IS reused (second call prefilled only {b.get('prefill_count_second')} vs "
                f"{b.get('prefill_count_first')} tokens) — so the tool schemas are prefilled ONCE per "
                "turn, not per call. Prefill is not your main cost; generation throughput is. Fast "
                "mode still trims the first prefill and lets the model choose faster."
            )
        else:
            notes.append(
                f"prefill is {prefill} tok/s. If the prompt cache is not reused, the ~10.6k tool "
                f"schemas cost ~{tool_prefill_s}s per call — keep the model resident (keep_alive) and "
                "num_ctx large enough so the prefix stays cached, and use fast mode to shrink it."
            )
    if b.get("loaded_context") and isinstance(b["loaded_context"], int):
        if b["loaded_context"] > 40000:
            notes.append(
                f"the model is loaded at a {b['loaded_context']}-token context. A big context "
                "inflates KV-cache memory and prefill; right-size it to ~16-32k (enough for the "
                "tool schemas + history) unless you truly need 131k."
            )
    if not notes:
        notes.append("no obvious misconfiguration; speed is the model's raw throughput.")
    return notes


def _cmd_bench(args: argparse.Namespace) -> int:
    base_url = args.base_url or load_config().base_url
    model = args.model or load_config().ollama_model
    if not is_serving(base_url):
        print(f"no ollama server at {base_url}. Is the tunnel up and the port right "
              f"(you mentioned 11435)? Try --base-url http://localhost:11435", file=sys.stderr)
        return 1
    print(f"benchmarking {model} at {base_url} …", file=sys.stderr)
    try:
        b = bench(base_url, model, timeout=args.timeout)
    except (urllib.error.URLError, OSError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(f"resident         : {b.get('resident')}"
          + (f"  ({b.get('size_vram_gib')} GiB VRAM, quant {b.get('quant')})"
             if b.get("resident") else ""))
    if b.get("loaded_context"):
        print(f"loaded context   : {b['loaded_context']}")
    print(f"load time        : {b.get('load_seconds')}s  (want ~0 = resident)")
    print(f"prefill speed    : {b.get('prefill_tok_per_s')} tok/s  (reading the prompt)")
    print(f"generation speed : {b.get('gen_tok_per_s')} tok/s  (writing the answer)")
    print("\ndiagnosis:")
    for note in _bench_diagnosis(b):
        print(f"  • {note}")
    return 0


def doctor(config: ConnectionConfig | None = None) -> int:
    """Diagnose the pipeline end to end. Returns a process exit code."""
    cfg = config or load_config()
    ok = True

    print(f"mode          : {cfg.connection_mode}")
    if cfg.connection_mode != "eth_hybrid":
        print("(local mode -- no tunnel involved)")
        return 0

    print(f"ssh target    : {cfg.ssh_target}")
    master = has_master(cfg)
    print(f"ssh master    : {'UP (automation works)' if master else 'down'}")
    if not master:
        print("  -> without it, node discovery and starting a tunnel need a password,")
        print("     which non-interactive ssh cannot supply. Run: connection login")

    tunnel = find_tunnel(cfg.local_fallback_port)
    if tunnel:
        kind = "managed" if tunnel.managed else "adopted (started outside this tool)"
        print(
            f"tunnel        : pid {tunnel.pid} -> {tunnel.node}:{tunnel.remote_port} [{kind}]"
        )
    else:
        print(f"tunnel        : NONE on port {cfg.local_fallback_port}")
        ok = False

    serving = is_serving(cfg.base_url)
    print(
        f"model server  : {'reachable' if serving else 'NOT reachable'} at {cfg.base_url}"
    )
    ok &= serving

    if tunnel and not serving:
        print(
            "  -> tunnel exists but nothing answers: the Slurm node has likely changed."
        )
        print("     Fix: python -m geoagent.core.eth_cluster up --force")

    if serving:
        try:
            models = list_models(cfg.base_url)
        except ConnectionError_ as exc:
            print(f"  {exc}")
            return 1
        names = [m.get("name") for m in models]
        print(f"models pulled : {names or '(none)'}")
        if cfg.ollama_model not in names:
            ok = False
            print(
                f"  -> configured model {cfg.ollama_model!r} is NOT pulled on the node."
            )
            print(f"     Fix (on the node): ollama pull {cfg.ollama_model}")
        else:
            good, detail = model_emits_tool_calls(cfg.base_url, cfg.ollama_model)
            print(f"tool calling  : {'OK' if good else 'BROKEN'} -- {detail}")
            ok &= good

    print("\nverdict       :", "ready" if ok else "NOT ready")
    return 0 if ok else 1


# -- CLI ----------------------------------------------------------------------


def _cmd_status(_: argparse.Namespace) -> int:
    cfg = load_config()
    tunnel = find_tunnel(cfg.local_fallback_port)
    print(f"mode   : {cfg.connection_mode}")
    print(f"config : {config_path()}")
    if cfg.connection_mode == "eth_hybrid":
        print(f"target : {cfg.ssh_target} -> {cfg.active_slurm_node}:{cfg.remote_port}")
        if tunnel:
            print(f"tunnel : UP  pid={tunnel.pid} node={tunnel.node}")
        else:
            print("tunnel : DOWN")
        print(f"server : {'reachable' if is_serving(cfg.base_url) else 'unreachable'}")
    return 0


def _cmd_up(args: argparse.Namespace) -> int:
    try:
        tunnel = up(force_restart=args.force)
    except ConnectionError_ as exc:
        print(f"error: {exc}")
        return 1
    kind = "started" if tunnel.managed else "already up (adopted)"
    print(
        f"tunnel {kind}: pid={tunnel.pid} localhost:{tunnel.local_port} -> "
        f"{tunnel.node}:{tunnel.remote_port}"
    )
    return 0


def _cmd_down(_: argparse.Namespace) -> int:
    stopped = down()
    print("tunnel stopped" if stopped else "no tunnel was running")
    return 0


def _cmd_node(_: argparse.Namespace) -> int:
    cfg = load_config()
    try:
        node = discover_node(cfg)
    except ConnectionError_ as exc:
        print(f"error: {exc}")
        return 1
    if not node:
        print(f"no RUNNING Slurm job for {cfg.eth_username}")
        return 1
    print(node)
    if node != cfg.active_slurm_node:
        cfg.active_slurm_node = node
        save_config(cfg)
        print(f"(config updated: active_slurm_node -> {node})")
    return 0


def _cmd_doctor(_: argparse.Namespace) -> int:
    return doctor()


def _cmd_login(_: argparse.Namespace) -> int:
    """Open the shared master connection (prompts for a password once)."""
    cfg = load_config()
    if has_master(cfg):
        print(f"master connection already up for {cfg.ssh_target}")
        return 0
    try:
        start_master(cfg)
    except ConnectionError_ as exc:
        print(f"error: {exc}")
        return 1
    print(f"master connection up for {cfg.ssh_target} (persists 8h)")
    return 0


def _cmd_init(_: argparse.Namespace) -> int:
    path = save_config(load_config())
    print(f"wrote {path}")
    return 0


def _cmd_probe(_: argparse.Namespace) -> int:
    """Report the node's GPU + VRAM and the models worth running on it."""
    snap = report()
    print(f"node             : {snap.get('node')}")
    print(f"configured model : {snap.get('configured_model')}")
    if snap.get("error"):
        print(f"error            : {snap['error']}")
        return 1
    for gpu in snap.get("gpus", []) or ["(none reported)"]:
        if isinstance(gpu, dict):
            print(f"gpu              : {gpu['name']}  {gpu['total_gib']} GiB total, "
                  f"{gpu['free_gib']} GiB free")
    if snap.get("gpu_error"):
        print(f"gpu probe        : {snap['gpu_error']}")
    for rec in snap.get("recommended", []):
        print(f"  recommend      : {rec['model']:<22} ~{rec['approx_vram_gib']} GiB  "
              f"{rec['reason']}")
    installed = snap.get("installed_models")
    if installed is not None:
        print(f"installed        : {', '.join(installed) or '(none)'}")
    print("\nNext: `eth_cluster pull <model>` then `eth_cluster use <model>`.")
    return 0


def _cmd_models(_: argparse.Namespace) -> int:
    try:
        print("\n".join(installed_models()) or "(no models installed / server unreachable)")
    except ConnectionError_ as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _cmd_pull(args: argparse.Namespace) -> int:
    try:
        pull_model(None, args.model, progress=lambda m: print(f"  {m}", file=sys.stderr))
    except ConnectionError_ as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"pulled {args.model}. Select it with: eth_cluster use {args.model}")
    return 0


def _cmd_use(args: argparse.Namespace) -> int:
    cfg = use_model(None, args.model)
    print(f"eth_hybrid model set to {cfg.ollama_model} (saved to {config_path()}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func, help_text in (
        ("status", _cmd_status, "Show mode, tunnel and server state"),
        ("login", _cmd_login, "Open the shared SSH connection (password once, 8h)"),
        ("down", _cmd_down, "Stop the tunnel"),
        ("node", _cmd_node, "Ask Slurm for the current node"),
        ("probe", _cmd_probe, "Report the node GPU/VRAM + recommend a model"),
        ("models", _cmd_models, "List models installed on the node's ollama server"),
        ("doctor", _cmd_doctor, "Diagnose the pipeline end to end"),
        ("init", _cmd_init, "Write a default config.json"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)

    p_up = sub.add_parser("up", help="Discover the node and open the tunnel")
    p_up.add_argument(
        "--force",
        action="store_true",
        help="Rebuild an existing tunnel (use after the Slurm node changes)",
    )
    p_up.set_defaults(func=_cmd_up)

    p_pull = sub.add_parser("pull", help="Download a model on the node (ollama pull)")
    p_pull.add_argument("model", help="ollama tag, e.g. qwen3-coder:30b")
    p_pull.set_defaults(func=_cmd_pull)

    p_use = sub.add_parser("use", help="Set the eth_hybrid model")
    p_use.add_argument("model", help="ollama tag to select")
    p_use.set_defaults(func=_cmd_use)

    p_bench = sub.add_parser(
        "bench", help="Measure prefill/generation speed + diagnose slowness"
    )
    p_bench.add_argument(
        "--base-url", default=None,
        help="ollama base URL (default from config; use http://localhost:11435 for your tunnel)",
    )
    p_bench.add_argument("--model", default=None, help="model tag to benchmark")
    p_bench.add_argument("--timeout", type=float, default=600.0)
    p_bench.set_defaults(func=_cmd_bench)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
