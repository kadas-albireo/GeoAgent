"""Tests for the ETH hybrid connection config and SSH tunnel manager.

The parsing tests use the *real* command line observed on the dev box:

    ssh -L 11434:studgpu-node01:11434 achurchill@student-cluster2.inf.ethz.ch

Adoption of a hand-started tunnel is the primary path, not a fallback: the cluster does
not accept our key (verified: "Permission denied (publickey,password)"), so the tunnel is
normally opened interactively with a password. If find_tunnel() failed to recognise it,
the manager would try to start a duplicate and fail on the busy port.

No cluster access required: subprocess and HTTP are faked.
"""

from __future__ import annotations

import json

import pytest

from geoagent.core import eth_cluster as connection

# Config


def test_defaults_match_the_documented_schema() -> None:
    """The config keys the pipeline is specified around must exist."""
    cfg = connection.ConnectionConfig()

    assert cfg.connection_mode in connection.CONNECTION_MODES
    assert cfg.eth_username == "achurchill"
    assert cfg.local_fallback_port == 11434
    assert cfg.ssh_key_path.endswith("id_ed25519")


def test_round_trips_through_json(tmp_path) -> None:
    """Saving then loading preserves every field."""
    path = tmp_path / "config.json"
    cfg = connection.ConnectionConfig(active_slurm_node="studgpu-node07")
    connection.save_config(cfg, path)

    assert json.loads(path.read_text())["active_slurm_node"] == "studgpu-node07"
    assert connection.load_config(path).active_slurm_node == "studgpu-node07"


def test_unknown_keys_are_ignored(tmp_path) -> None:
    """A config written by a newer/older version still loads."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"eth_username": "someone", "future_field": 1}))

    assert connection.load_config(path).eth_username == "someone"


def test_missing_or_corrupt_config_falls_back_to_defaults(tmp_path) -> None:
    """A broken file must not break the runner that imports this at module level."""
    missing = tmp_path / "nope.json"
    assert connection.load_config(missing).eth_username == "achurchill"

    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json")
    assert connection.load_config(corrupt).eth_username == "achurchill"


def test_derived_urls() -> None:
    cfg = connection.ConnectionConfig(local_fallback_port=9999)

    assert cfg.ssh_target == "achurchill@student-cluster2.inf.ethz.ch"
    assert cfg.base_url == "http://localhost:9999"


# find_tunnel


def _fake_processes(monkeypatch, rows):
    monkeypatch.setattr(connection, "_ssh_processes", lambda: rows)


def test_finds_the_real_hand_started_tunnel(monkeypatch) -> None:
    """The exact command line seen in production must be recognised."""
    _fake_processes(
        monkeypatch,
        [
            (
                495687,
                "ssh -L 11434:studgpu-node01:11434 achurchill@student-cluster2.inf.ethz.ch",
            )
        ],
    )
    tunnel = connection.find_tunnel(11434)

    assert tunnel is not None
    assert tunnel.pid == 495687
    assert tunnel.node == "studgpu-node01"
    assert tunnel.remote_port == 11434
    assert tunnel.managed is False


def test_finds_a_bind_address_qualified_forward(monkeypatch) -> None:
    """``-L localhost:11434:node:11434`` is the same forward, spelled differently."""
    _fake_processes(
        monkeypatch,
        [(1, "ssh -N -L localhost:11434:studgpu-node02:11434 u@host")],
    )
    tunnel = connection.find_tunnel(11434)

    assert tunnel is not None
    assert tunnel.node == "studgpu-node02"


def test_ignores_a_forward_on_a_different_port(monkeypatch) -> None:
    """Someone else's tunnel must not be mistaken for ours."""
    _fake_processes(monkeypatch, [(1, "ssh -N -L 8080:other-node:80 u@host")])

    assert connection.find_tunnel(11434) is None


def test_no_tunnel_returns_none(monkeypatch) -> None:
    _fake_processes(monkeypatch, [])

    assert connection.find_tunnel(11434) is None


# discover_node


def _fake_run(monkeypatch, stdout="", stderr="", returncode=0):
    import subprocess as sp

    def run(*_a, **_k):
        return sp.CompletedProcess([], returncode, stdout, stderr)

    monkeypatch.setattr(connection.subprocess, "run", run)


def test_discover_node_parses_squeue(monkeypatch) -> None:
    _fake_run(monkeypatch, stdout="studgpu-node03\n")

    assert connection.discover_node(connection.ConnectionConfig()) == "studgpu-node03"


def test_discover_node_handles_a_range_expression(monkeypatch) -> None:
    """squeue can print a node list like 'studgpu-node[01-02]'; take the first."""
    _fake_run(monkeypatch, stdout="studgpu-node[03-05]\n")

    assert connection.discover_node(connection.ConnectionConfig()) == "studgpu-node03"


def test_discover_node_returns_none_without_a_running_job(monkeypatch) -> None:
    """No allocation is a normal state, not an error."""
    _fake_run(monkeypatch, stdout="\n")

    assert connection.discover_node(connection.ConnectionConfig()) is None


def test_discover_node_explains_an_auth_failure(monkeypatch) -> None:
    """The cluster rejects our key; the error must say what to do about it."""
    _fake_run(
        monkeypatch,
        stderr="achurchill@student-cluster2.inf.ethz.ch: Permission denied (publickey,password).",
        returncode=255,
    )
    with pytest.raises(connection.ConnectionError_, match="eth_cluster login"):
        connection.discover_node(connection.ConnectionConfig())


# up()


def test_up_adopts_a_working_tunnel_without_touching_ssh(monkeypatch) -> None:
    """Never disturb a tunnel the user opened by hand; never re-auth needlessly."""
    _fake_processes(monkeypatch, [(495687, "ssh -L 11434:studgpu-node01:11434 u@h")])
    monkeypatch.setattr(connection, "is_serving", lambda *a, **k: True)

    def fail(*_a, **_k):
        raise AssertionError("must not touch ssh when a working tunnel exists")

    monkeypatch.setattr(connection, "discover_node", fail)
    monkeypatch.setattr(connection, "start_tunnel", fail)

    tunnel = connection.up(connection.ConnectionConfig())
    assert tunnel.pid == 495687


def test_up_diagnoses_a_stale_node(monkeypatch) -> None:
    """Tunnel up but nothing answering is the classic Slurm-reallocation symptom."""
    _fake_processes(monkeypatch, [(1, "ssh -L 11434:studgpu-node01:11434 u@h")])
    monkeypatch.setattr(connection, "is_serving", lambda *a, **k: False)

    with pytest.raises(connection.ConnectionError_, match="--force"):
        connection.up(connection.ConnectionConfig())


def test_up_refuses_in_local_mode() -> None:
    """A tunnel makes no sense when the model is served locally."""
    cfg = connection.ConnectionConfig(connection_mode="local")

    with pytest.raises(connection.ConnectionError_, match="local"):
        connection.up(cfg)


def test_up_reports_when_no_slurm_job_is_running(monkeypatch) -> None:
    _fake_processes(monkeypatch, [])
    monkeypatch.setattr(connection, "discover_node", lambda *a, **k: None)

    with pytest.raises(connection.ConnectionError_, match="No RUNNING Slurm job"):
        connection.up(connection.ConnectionConfig())


def test_up_refreshes_a_stale_node_in_config(monkeypatch, tmp_path) -> None:
    """The config's node is a cache; discovery is the authority."""
    _fake_processes(monkeypatch, [])
    monkeypatch.setattr(connection, "discover_node", lambda *a, **k: "studgpu-node09")
    monkeypatch.setenv("GEOAGENT_ETH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(
        connection,
        "start_tunnel",
        lambda cfg, node, **k: connection.TunnelInfo(1, 11434, node, 11434, "", True),
    )

    cfg = connection.ConnectionConfig(active_slurm_node="studgpu-node01")
    tunnel = connection.up(cfg)

    assert tunnel.node == "studgpu-node09"
    assert cfg.active_slurm_node == "studgpu-node09"


# geoagent_config wiring


def test_eth_hybrid_maps_to_the_eth_cluster_provider() -> None:
    """Selecting the cluster must route through the provider that opens the tunnel."""
    cfg = connection.ConnectionConfig(
        connection_mode="eth_hybrid", ollama_model="qwen2.5:7b-instruct"
    )
    agent_cfg = connection.geoagent_config(cfg)

    assert agent_cfg.provider == "eth-cluster"
    assert agent_cfg.model == "qwen2.5:7b-instruct"


def test_local_mode_maps_to_lmstudio() -> None:
    cfg = connection.ConnectionConfig(connection_mode="local")

    assert connection.geoagent_config(cfg).provider == "lmstudio"


# Tool-call probe


def _fake_chat_response(monkeypatch, message):
    import io

    def urlopen(*_a, **_k):
        payload = json.dumps({"message": message}).encode()
        return io.BytesIO(payload)

    monkeypatch.setattr(connection.urllib.request, "urlopen", urlopen)


def test_probe_accepts_structured_tool_calls(monkeypatch) -> None:
    _fake_chat_response(
        monkeypatch, {"tool_calls": [{"function": {"name": "get_weather"}}]}
    )
    ok, _ = connection.model_emits_tool_calls("http://x", "good-model")

    assert ok


def test_probe_rejects_a_plain_text_tool_call(monkeypatch) -> None:
    """The qwen2.5-coder:7b failure: right JSON, wrong channel.

    It emits the call in `content` without the <tool_call> delimiters its template
    requires, so ollama parses nothing and the agent silently never acts. /api/show
    still advertises `tools`, which is why capability alone cannot be trusted.
    """
    _fake_chat_response(
        monkeypatch,
        {
            "content": '{"name": "get_weather", "arguments": {"city": "Zurich"}}',
            "tool_calls": None,
        },
    )
    ok, detail = connection.model_emits_tool_calls("http://x", "qwen2.5-coder:7b")

    assert not ok
    assert "PLAIN TEXT" in detail
    assert "instruct" in detail


def test_probe_rejects_prose(monkeypatch) -> None:
    _fake_chat_response(
        monkeypatch, {"content": "I cannot check the weather.", "tool_calls": None}
    )
    ok, detail = connection.model_emits_tool_calls("http://x", "chatty")

    assert not ok
    assert "prose" in detail


# ensure_tunnel / provider wiring


def test_ensure_tunnel_adopts_a_serving_tunnel(monkeypatch) -> None:
    """The fast path: one HTTP probe, no ssh, no re-auth."""
    _fake_processes(monkeypatch, [(1, "ssh -L 11434:studgpu-node01:11434 u@h")])
    monkeypatch.setattr(connection, "is_serving", lambda *a, **k: True)

    def fail(*_a, **_k):
        raise AssertionError("must not touch ssh when a working tunnel exists")

    monkeypatch.setattr(connection, "has_master", fail)
    monkeypatch.setattr(connection, "up", fail)

    cfg = connection.ensure_tunnel(connection.ConnectionConfig())
    assert cfg.connection_mode == "eth_hybrid"


def test_ensure_tunnel_refuses_to_prompt_for_a_password(monkeypatch) -> None:
    """A GUI has no terminal: an ssh password prompt there hangs the app invisibly.

    So a missing master connection must be an immediate, actionable error naming the
    command to run, not an attempt to authenticate.
    """
    _fake_processes(monkeypatch, [])
    monkeypatch.setattr(connection, "is_serving", lambda *a, **k: False)
    monkeypatch.setattr(connection, "has_master", lambda *a, **k: False)

    def fail(*_a, **_k):
        raise AssertionError("must not attempt an interactive ssh from ensure_tunnel")

    monkeypatch.setattr(connection, "start_master", fail)
    monkeypatch.setattr(connection, "up", fail)

    with pytest.raises(connection.ConnectionError_, match="eth_cluster login"):
        connection.ensure_tunnel(connection.ConnectionConfig())


def test_ensure_tunnel_refuses_in_local_mode() -> None:
    cfg = connection.ConnectionConfig(connection_mode="local")

    with pytest.raises(connection.ConnectionError_, match="lmstudio"):
        connection.ensure_tunnel(cfg)


def test_ensure_tunnel_reports_progress(monkeypatch) -> None:
    """The dock shows these while the user waits on an ssh round trip."""
    _fake_processes(monkeypatch, [(1, "ssh -L 11434:studgpu-node01:11434 u@h")])
    monkeypatch.setattr(connection, "is_serving", lambda *a, **k: True)
    messages: list[str] = []

    connection.ensure_tunnel(connection.ConnectionConfig(), progress=messages.append)

    assert any("Tunnel up" in m for m in messages)


def test_eth_cluster_provider_opens_the_tunnel_then_speaks_ollama(monkeypatch) -> None:
    """resolve_model must ensure the bridge before handing off to the ollama client."""
    import sys
    import types

    class FakeOllamaModel:
        def __init__(self, host, **kwargs):
            self.host = host
            self.kwargs = kwargs

    module = types.ModuleType("strands.models.ollama")
    module.OllamaModel = FakeOllamaModel
    monkeypatch.setitem(sys.modules, "strands", types.ModuleType("strands"))
    monkeypatch.setitem(
        sys.modules, "strands.models", types.ModuleType("strands.models")
    )
    monkeypatch.setitem(sys.modules, "strands.models.ollama", module)

    calls: list[str] = []
    monkeypatch.setattr(
        connection, "ensure_tunnel", lambda cfg, **k: calls.append("ensured") or cfg
    )
    monkeypatch.setattr(
        connection,
        "load_config",
        lambda *a, **k: connection.ConnectionConfig(ollama_model="qwen2.5:7b-instruct"),
    )

    from geoagent.core.config import GeoAgentConfig
    from geoagent.core.model import resolve_model

    model = resolve_model(GeoAgentConfig(provider="eth-cluster"))

    assert calls == ["ensured"], "the tunnel must be opened before the model is built"
    assert isinstance(model, FakeOllamaModel)
    assert model.host == "http://localhost:11434"
    assert model.kwargs["model_id"] == "qwen2.5:7b-instruct"
