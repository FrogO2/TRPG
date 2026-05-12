"""Thin service layer for the local TRPG web UI."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from src.agents import DialogueCoordinator, GMAgent, HumanPlayer, LLMPlayerAgent
from src.agents.runtime_common import invoke_tool
from src.tools.tools import (
    PLAYER_IDS,
    answer_rule_query,
    approve_interrupt,
    append_dialogue_history,
    compile_rules_summary,
    get_upcoming_speakers,
    jump_player_notebook,
    nominate_next_speaker,
    read_player_notebook,
    request_interrupt,
    search_player_notebook,
    summarize_dialogue_history,
    update_player_notebook,
)

NOTEBOOK_NAMES = ["character_sheet", "events", "private_notes"]
LLM_PLAYER_IDS = [actor_id for actor_id in PLAYER_IDS if actor_id != "human_player"]
ALL_WEB_ACTORS = ["gm", *PLAYER_IDS]


@dataclass(slots=True)
class RuntimeSnapshot:
    state: dict[str, Any]
    upcoming: str
    history: str


class RuntimeWebService:
    """App-facing orchestration around the existing GM-driven runtime."""

    def __init__(self) -> None:
        self.dialogue = DialogueCoordinator()
        self._lock = threading.Lock()

    def initialize(self, default_order: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            message = self.dialogue.initialize(default_order)
            return {
                "message": message,
                "snapshot": self.snapshot(),
            }

    def snapshot(self, *, history_window: int = 20, lookahead: int = 5) -> dict[str, Any]:
        state = self.dialogue.state()
        return {
            "state": state,
            "upcoming": invoke_tool(get_upcoming_speakers, lookahead=lookahead),
            "history": invoke_tool(summarize_dialogue_history, window=history_window),
            "notebook_names": NOTEBOOK_NAMES,
            "llm_player_ids": LLM_PLAYER_IDS,
            "all_actors": ALL_WEB_ACTORS,
        }

    def _require_active_speaker(self, expected: str) -> dict[str, Any]:
        state = self.dialogue.state()
        actual = state.get("active_speaker")
        if actual != expected:
            raise ValueError(f"Current active speaker is {actual!r}, not {expected!r}.")
        return state

    def _shared_context(self, extra_context: str = "", *, window: int = 12) -> str:
        parts: list[str] = []
        history = invoke_tool(summarize_dialogue_history, window=window).strip()
        if history and history != "No dialogue history yet.":
            parts.append(history)
        if extra_context.strip():
            parts.append(extra_context.strip())
        return "\n\n".join(parts)

    def advance(self) -> dict[str, Any]:
        with self._lock:
            message = self.dialogue.advance()
            return {"message": message, "snapshot": self.snapshot()}

    def set_temporary_order(self, order: list[str], *, reason: str = "") -> dict[str, Any]:
        with self._lock:
            message = self.dialogue.set_temporary_order(order, reason=reason)
            return {"message": message, "snapshot": self.snapshot()}

    def human_turn(self, message: str, *, no_advance: bool = False) -> dict[str, Any]:
        with self._lock:
            self._require_active_speaker("human_player")
            human = HumanPlayer()
            result = human.submit_turn(message)
            advance_message = ""
            if not no_advance:
                advance_message = self.dialogue.advance()
            return {
                "message": result,
                "advance_message": advance_message,
                "snapshot": self.snapshot(),
            }

    def player_turn(
        self,
        actor_id: str,
        message: str = "",
        *,
        extra_context: str = "",
        no_advance: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._require_active_speaker(actor_id)
            player = LLMPlayerAgent(actor_id)
            prompt = message or "请基于当前共享历史、你的个人 notebook 和记忆，以玩家身份给出本回合的发言或行动。"
            reply = player.take_turn(
                prompt,
                active_speaker=actor_id,
                upcoming_order=invoke_tool(get_upcoming_speakers, lookahead=5),
                extra_context=self._shared_context(extra_context),
            )
            invoke_tool(append_dialogue_history, speaker_id=actor_id, message=reply)
            advance_message = ""
            if not no_advance:
                advance_message = self.dialogue.advance()
            return {
                "message": reply,
                "advance_message": advance_message,
                "snapshot": self.snapshot(),
            }

    def gm_turn(self, message: str, *, extra_context: str = "", no_advance: bool = False) -> dict[str, Any]:
        with self._lock:
            self._require_active_speaker("gm")
            gm = GMAgent()
            reply = gm.take_turn(
                message,
                active_speaker="gm",
                upcoming_order=invoke_tool(get_upcoming_speakers, lookahead=5),
                extra_context=self._shared_context(extra_context),
            )
            invoke_tool(append_dialogue_history, speaker_id="gm", message=reply)
            advance_message = ""
            if not no_advance:
                advance_message = self.dialogue.advance()
            return {
                "message": reply,
                "advance_message": advance_message,
                "snapshot": self.snapshot(),
            }

    def request_interrupt(self, actor_id: str, *, reason: str = "") -> dict[str, Any]:
        with self._lock:
            message = invoke_tool(request_interrupt, actor_id=actor_id, reason=reason)
            return {"message": message, "snapshot": self.snapshot()}

    def approve_interrupt(self, actor_id: str) -> dict[str, Any]:
        with self._lock:
            message = invoke_tool(approve_interrupt, actor_id="gm", speaker_id=actor_id)
            return {"message": message, "snapshot": self.snapshot()}

    def nominate_next(self, actor_id: str, next_speaker: str, *, reason: str = "") -> dict[str, Any]:
        with self._lock:
            message = invoke_tool(
                nominate_next_speaker,
                actor_id=actor_id,
                next_speaker=next_speaker,
                reason=reason,
            )
            return {"message": message, "snapshot": self.snapshot()}

    def read_notebook(self, actor_id: str, owner_id: str, notebook_name: str) -> dict[str, Any]:
        content = invoke_tool(
            read_player_notebook,
            actor_id=actor_id,
            owner_id=owner_id,
            notebook_name=notebook_name,
        )
        return {
            "content": content,
            "owner_id": owner_id,
            "actor_id": actor_id,
            "notebook_name": notebook_name,
        }

    def search_notebook(self, actor_id: str, owner_id: str, notebook_name: str, query: str) -> dict[str, Any]:
        content = invoke_tool(
            search_player_notebook,
            actor_id=actor_id,
            owner_id=owner_id,
            notebook_name=notebook_name,
            query=query,
        )
        return {"content": content}

    def jump_notebook(self, actor_id: str, owner_id: str, notebook_name: str, heading: str) -> dict[str, Any]:
        content = invoke_tool(
            jump_player_notebook,
            actor_id=actor_id,
            owner_id=owner_id,
            notebook_name=notebook_name,
            heading=heading,
        )
        return {"content": content}

    def update_notebook(
        self,
        actor_id: str,
        owner_id: str,
        notebook_name: str,
        content: str,
        *,
        mode: str = "append",
        heading: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            message = invoke_tool(
                update_player_notebook,
                actor_id=actor_id,
                owner_id=owner_id,
                notebook_name=notebook_name,
                content=content,
                mode=mode,
                heading=heading,
            )
            notebook = self.read_notebook(actor_id, owner_id, notebook_name)
            return {
                "message": message,
                "notebook": notebook,
                "snapshot": self.snapshot(),
            }

    def rule_query(self, query: str, *, doc_ids: str = "", top_k: int = 5) -> dict[str, Any]:
        answer = invoke_tool(answer_rule_query, query=query, doc_ids=doc_ids, top_k=top_k)
        return {"message": answer}

    def compile_rules(self, *, doc_ids: str = "", output_path: str = "") -> dict[str, Any]:
        answer = invoke_tool(compile_rules_summary, doc_ids=doc_ids, output_path=output_path)
        return {"message": answer}
