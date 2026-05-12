"""Dialogue coordinator for the GM-driven runtime."""

from __future__ import annotations

import json
from typing import Any, Sequence

from src.tools.tools import (
    DIALOGUE_STATE_PATH,
    append_dialogue_history,
    get_upcoming_speakers,
    initialize_dialogue_state,
    read_dialogue_state,
    set_temporary_speaking_order,
    advance_turn,
)
from src.agents.runtime_common import invoke_tool


class DialogueCoordinator:
    """Thin wrapper over dialogue tools for app-level orchestration."""

    def initialize(self, default_order: Sequence[str] | None = None) -> str:
        return invoke_tool(initialize_dialogue_state, default_order_csv=",".join(default_order) if default_order else "")

    def state(self) -> dict[str, Any]:
        return json.loads(invoke_tool(read_dialogue_state))

    def active_speaker(self) -> str:
        return self.state().get("active_speaker", "")

    def upcoming_order(self, lookahead: int = 5) -> list[str]:
        preview = invoke_tool(get_upcoming_speakers, lookahead=lookahead)
        return [part.strip() for part in preview.split("->") if part.strip()]

    def set_temporary_order(self, order: Sequence[str], *, reason: str = "") -> str:
        return invoke_tool(set_temporary_speaking_order, actor_id="gm", order_csv=",".join(order), reason=reason)

    def record_dialogue(self, speaker_id: str, message: str) -> str:
        return invoke_tool(append_dialogue_history, speaker_id=speaker_id, message=message)

    def advance(self) -> str:
        return invoke_tool(advance_turn)

    def state_path(self) -> str:
        return str(DIALOGUE_STATE_PATH)
