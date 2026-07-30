"""
LLM tracing for GeoAgent. Uses Strands hooks to record user and agent messages,
the model's thinking, the tool calls it runs (the exact code/command) and their
results into a JSONL log. Values are written raw — no truncation or reshaping.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


def _log_dir() -> Path:
    """Return the base log directory (``$GEOAGENT_LOG_DIR`` or ``~/.kadas``)."""
    base = os.environ.get("GEOAGENT_LOG_DIR")
    return Path(base) if base else Path.home() / ".kadas"


def default_log_path() -> Path:
    """Return the JSONL log path (``$GEOAGENT_LOG_DIR`` or ``~/.kadas``)."""
    return _log_dir() / "agent_execution.log"


def default_feedback_path() -> Path:
    """Return the JSONL path for Developer-Mode "Training AI" feedback."""
    return _log_dir() / "agent_feedback.log"


# Human feedback ("Training AI" telemetry)


# Allowed classifications for a "Training AI" feedback entry.
FEEDBACK_STATUSES = ("success", "failure", "unclassified")


class FeedbackLogger:
    """Append-only sink for Developer-Mode "Training AI" feedback.

    Each entry pairs a question/answer exchange with a human classification
    (success / failure / unclassified) and free-text notes, an ISO-8601 UTC
    timestamp and an epoch time. Entries are written as JSONL next to the
    execution trace (``~/.kadas/agent_feedback.log``) and — when running inside
    KADAS/QGIS — also mirrored to the native ``QgsMessageLog`` "GeoAgent" panel
    so reviewers see feedback in the application's own log without opening files.
    """

    def __init__(self, *, log_path: str | os.PathLike[str] | None = None) -> None:
        self._log_path = (
            Path(log_path) if log_path is not None else default_feedback_path()
        )
        self._lock = threading.Lock()

    @property
    def log_path(self) -> Path:
        """The JSONL file feedback entries are appended to."""
        return self._log_path

    @staticmethod
    def normalize_status(status: str | None) -> str:
        """Coerce a UI status label to one of :data:`FEEDBACK_STATUSES`."""
        value = str(status or "").strip().lower()
        return value if value in FEEDBACK_STATUSES else "unclassified"

    def record_feedback(
        self,
        *,
        status: str,
        feedback: str = "",
        question: str = "",
        answer: str = "",
        **extra: Any,
    ) -> dict[str, Any]:
        """Record one feedback entry and return the event that was written.

        Args:
            status: ``success`` / ``failure`` / ``unclassified`` (coerced).
            feedback: Free-text notes from the reviewer.
            question: The user prompt the feedback is about.
            answer: The agent answer the feedback is about.
            extra: Any additional JSON-serialisable fields (model, tools, ...).
        """
        now = time.time()
        event: dict[str, Any] = {
            "kind": "feedback",
            "time": now,
            "timestamp": _utc_isoformat(now),
            "status": self.normalize_status(status),
            "feedback": str(feedback or ""),
            "question": str(question or ""),
            "answer": str(answer or ""),
            **extra,
        }
        self._write(event)
        self._mirror_to_qgis(event)
        return event

    def _write(self, event: dict[str, Any]) -> None:
        """Append one event to the JSONL log (best-effort, never raises)."""
        try:
            line = json.dumps(event, default=str, ensure_ascii=False)
            with self._lock:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception:
            pass

    @staticmethod
    def _mirror_to_qgis(event: dict[str, Any]) -> None:
        """Echo a one-line summary into KADAS' native QgsMessageLog panel."""
        try:
            from qgis.core import (  # type: ignore[import-not-found]
                Qgis,
                QgsMessageLog,
            )

            status = event.get("status", "unclassified")
            note = (event.get("feedback") or "").strip()
            summary = f"[training:{status}] {note}" if note else f"[training:{status}]"
            level = {
                "failure": Qgis.MessageLevel.Warning,
                "success": Qgis.MessageLevel.Success,
            }.get(status, Qgis.MessageLevel.Info)
            QgsMessageLog.logMessage(summary, "GeoAgent", level)
        except Exception:
            pass


def _utc_isoformat(epoch: float) -> str:
    """Return an ISO-8601 UTC timestamp for an epoch time."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class AgentTracer:
    """Append-only JSONL sink for LLM-mode execution traces."""

    def __init__(self, *, log_path: str | os.PathLike[str] | None = None) -> None:
        self._log_path = Path(log_path) if log_path is not None else default_log_path()
        self._lock = threading.Lock()

    @property
    def log_path(self) -> Path:
        """The JSONL file events are appended to."""
        return self._log_path

    def record(self, kind: str, **data: Any) -> None:
        """Append one event to the log (best-effort, never raises into a turn)."""
        event = {"kind": kind, "time": time.time(), **data}
        try:
            line = json.dumps(event, default=str, ensure_ascii=False)
            with self._lock:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception:
            pass

    def log_session_start(self, *, system_prompt: str, tools: list[str]) -> None:
        """Record the agent's system prompt and tool names, once."""
        self.record(
            "session_start", system_prompt=system_prompt, tools=list(tools or [])
        )

    def log_turn_start(self, task: Any) -> None:
        """Record the user task that opens a turn."""
        self.record("turn_start", task=task)

    def log_thinking(self, text: str) -> None:
        """Record the model's reasoning ("backend thinking") for a turn."""
        self.record("thinking", text=text)

    def log_message(self, role: str, content: Any) -> None:
        """Record one transcript message (role + raw content blocks)."""
        self.record("message", role=role, content=content)

    def log_tool_call(self, name: str, tool_input: Any) -> None:
        """Record a tool invocation: its name and exact input args.

        For the execution tools this is the code/command the agent ran, e.g.
        ``run_pyqgis_script`` -> ``{"code": ...}``, ``run_command`` ->
        ``{"command": ...}``, ``run_processing_algorithm`` ->
        ``{"algorithm_id": ..., "parameters": ...}``.
        """
        self.record("tool_call", name=name, input=tool_input)

    def log_tool_result(
        self, name: str, result: Any, exception: str | None = None
    ) -> None:
        """Record a tool's return value (or the exception it raised)."""
        data: dict[str, Any] = {"name": name, "result": result}
        if exception:
            data["exception"] = exception
        self.record("tool_result", **data)

    def log_turn_end(self, answer: Any, *, stop_reason: str = "") -> None:
        """Record the final answer and stop reason that close a turn."""
        self.record("turn_end", answer=answer, stop_reason=stop_reason)

    def log_error(self, message: str) -> None:
        """Record a turn-level error (a crash that bypassed ``turn_end``)."""
        self.record("error", message=message)


# Strands hook provider


class TraceHookProvider:
    """Strands ``HookProvider`` that records the whole turn lifecycle.

    It subscribes to the real Strands hooks and turns each into one event:

    * ``AgentInitializedEvent`` -> ``session_start`` (system prompt + tools)
    * ``BeforeInvocationEvent`` -> ``turn_start`` (the user task)
    * ``MessageAddedEvent``     -> ``thinking`` (model reasoning, when present)
      and ``message`` (the full transcript message)
    * ``BeforeToolCallEvent``   -> ``tool_call`` (name + exact input args, i.e.
      the code/command the agent runs)
    * ``AfterToolCallEvent``    -> ``tool_result`` (the tool's return value)
    * ``AfterInvocationEvent``  -> ``turn_end`` (final answer + stop reason)
    """

    def __init__(self, tracer: AgentTracer) -> None:
        self._tracer = tracer

    def register_hooks(self, registry: Any, **kwargs: Any) -> None:  # noqa: ARG002
        """Subscribe to the Strands lifecycle hooks that build the trace."""
        from strands.hooks import (
            AfterInvocationEvent,
            AfterToolCallEvent,
            AgentInitializedEvent,
            BeforeInvocationEvent,
            BeforeToolCallEvent,
            MessageAddedEvent,
        )

        registry.add_callback(AgentInitializedEvent, self._on_init)
        registry.add_callback(BeforeInvocationEvent, self._on_turn_start)
        registry.add_callback(MessageAddedEvent, self._on_message)
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)
        registry.add_callback(AfterInvocationEvent, self._on_turn_end)

    def _on_init(self, event: Any) -> None:
        """Record the agent's system prompt and tool inventory once."""
        try:
            agent = getattr(event, "agent", None)
            self._tracer.log_session_start(
                system_prompt=str(getattr(agent, "system_prompt", "") or ""),
                tools=list(getattr(agent, "tool_names", []) or []),
            )
        except Exception:
            pass

    def _on_turn_start(self, event: Any) -> None:
        """Record the user task that opens the turn."""
        try:
            self._tracer.log_turn_start(_last_user_text(getattr(event, "messages", [])))
        except Exception:
            pass

    def _on_message(self, event: Any) -> None:
        """Record the model's thinking (if any) and the transcript message."""
        try:
            message = getattr(event, "message", None)
            if not isinstance(message, dict):
                return
            thinking = _reasoning_text(message)
            if thinking:
                self._tracer.log_thinking(thinking)
            self._tracer.log_message(message.get("role", ""), message.get("content"))
        except Exception:
            pass

    def _on_turn_end(self, event: Any) -> None:
        """Record the final answer and stop reason that close the turn."""
        try:
            result = getattr(event, "result", None)
            answer = _message_text(getattr(result, "message", None))
            self._tracer.log_turn_end(
                answer, stop_reason=str(getattr(result, "stop_reason", "") or "")
            )
        except Exception:
            pass

    def _before_tool(self, event: Any) -> None:
        """Record the tool call: its name and exact input arguments."""
        try:
            use = event.tool_use
            self._tracer.log_tool_call(str(use.get("name", "")), use.get("input"))
        except Exception:
            pass

    def _after_tool(self, event: Any) -> None:
        """Record the tool's return value (or the exception it raised)."""
        try:
            use = event.tool_use
            exc = getattr(event, "exception", None)
            self._tracer.log_tool_result(
                str(use.get("name", "")),
                getattr(event, "result", None),
                exception=str(exc) if exc is not None else None,
            )
        except Exception:
            pass


def _reasoning_text(message: dict[str, Any]) -> str:
    """Return the model's reasoning text from a Strands assistant message.

    Reasoning arrives as ``reasoningContent`` -> ``reasoningText`` -> ``text``
    content blocks (Claude extended thinking). Empty when the model emits none.
    """
    parts = []
    for block in message.get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("reasoningContent"), dict):
            reasoning_text = block["reasoningContent"].get("reasoningText")
            if isinstance(reasoning_text, dict) and isinstance(
                reasoning_text.get("text"), str
            ):
                parts.append(reasoning_text["text"])
    return "\n".join(parts)


def _message_text(message: Any) -> str:
    """Return the concatenated ``text`` blocks of a Strands message dict."""
    if not isinstance(message, dict):
        return str(message or "")
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = [
        block["text"]
        for block in content or []
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    return "\n".join(parts)


def _last_user_text(messages: Any) -> str:
    """Return the text of the most recent user message (skips tool results).

    Tool results arrive as ``user``-role messages carrying only ``toolResult``
    blocks; those have no text, so the last user message *with* text is the task.
    """
    for message in reversed(list(messages or [])):
        if isinstance(message, dict) and message.get("role") == "user":
            text = _message_text(message)
            if text.strip():
                return text
    return ""


__all__ = [
    "AgentTracer",
    "TraceHookProvider",
    "FeedbackLogger",
    "FEEDBACK_STATUSES",
    "default_log_path",
    "default_feedback_path",
]
