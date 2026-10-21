"""Trace ids: session/query ids on every event, request_index per model call."""

import json

from strands import Agent
from strands.models import Model

from geoagent.core.telemetry import AgentTracer, TraceHookProvider


class _OneShotModel(Model):
    """Minimal Strands model that answers every request with one text block."""

    def update_config(self, **kwargs):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, *args, **kwargs):
        yield {}

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"text": "ok"}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 5, "outputTokens": 1, "totalTokens": 6},
                "metrics": {"latencyMs": 1},
            }
        }


def _run_query(log, ids, prompts):
    tracer = AgentTracer(log_path=log, ids=ids)
    agent = Agent(
        model=_OneShotModel(),
        hooks=[TraceHookProvider(tracer)],
        callback_handler=None,
    )
    for prompt in prompts:
        agent(prompt)


def test_ids_on_every_event_and_request_index_per_agent(tmp_path):
    log = tmp_path / "trace.jsonl"
    _run_query(log, {"session_id": "s1", "query_id": "q1"}, ["a", "b"])
    _run_query(log, {"session_id": "s1", "query_id": "q2"}, ["c"])

    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert all(e["session_id"] == "s1" for e in events)
    calls = [
        (e["query_id"], e["request_index"]) for e in events if e["kind"] == "model_call"
    ]
    assert calls == [("q1", 1), ("q1", 2), ("q2", 1)]


def test_no_ids_keeps_events_unchanged(tmp_path):
    log = tmp_path / "trace.jsonl"
    AgentTracer(log_path=log).record("note", value=1)
    (event,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert set(event) == {"kind", "time", "value"}


def test_last_request_usage_is_the_provider_report(tmp_path):
    from geoagent import GeoAgent, GeoAgentConfig

    agent = GeoAgent(
        config=GeoAgentConfig(provider="anthropic", model="m"),
        model=_OneShotModel(),
    )
    assert agent.last_request_usage() is None  # nothing sent yet
    agent.chat("hello")
    assert agent.last_request_usage() == {
        "inputTokens": 5,
        "outputTokens": 1,
        "totalTokens": 6,
    }
