"""Apertus (Swiss AI) over an OpenAI-compatible endpoint.

Imported lazily by :func:`geoagent.core.model.resolve_model`, so the top-level
``strands`` import is safe.
"""

from __future__ import annotations

import json
from typing import Any

from strands.models.openai import OpenAIModel

DEFAULT_BASE_URL = "https://api.publicai.co/v1"
DEFAULT_MODEL = "swiss-ai/apertus-v1.5-70b"
# Stands in for "no arguments" in replayed tool calls; see ApertusModel.
EMPTY_ARGUMENTS = '{"_": null}'


class ApertusModel(OpenAIModel):
    """OpenAI model that replays argument-less tool calls in a form Apertus accepts.

    The served Apertus chat template rejects any history containing a tool call
    whose arguments are ``{}`` ("Invalid tool call", HTTP 400), so every agent
    turn after a no-argument tool (e.g. ``list_project_layers``) fails. Verified
    against PublicAI's ``swiss-ai/apertus-v1.5-70b`` on 2026-10-21; non-empty
    arguments pass. Tools ignore the placeholder key: it only lives in history.
    """

    def format_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        request = super().format_request(*args, **kwargs)
        for message in request["messages"]:
            for call in message.get("tool_calls") or ():
                function = call["function"]
                if not json.loads(function["arguments"] or "{}"):
                    function["arguments"] = EMPTY_ARGUMENTS
        return request
