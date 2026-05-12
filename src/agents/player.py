"""LLM and human player implementations for the dialogue runtime."""

from __future__ import annotations

from pathlib import Path

from langgraph.prebuilt import create_react_agent

from src.agents.runtime_common import (
    PROMPTS_DIR,
    build_default_player_llm,
    final_ai_text,
    invoke_tool,
    load_prompt,
    render_prompt,
)
from src.tools.tools import (
    PLAYER_IDS,
    append_dialogue_history,
    lookup_player_reference_index,
    nominate_next_speaker,
    query_odyssey_player_handbook,
    query_phb_documents,
    read_player_reference_page,
    read_player_reference_section,
    read_player_notebook,
    request_interrupt,
    search_player_reference,
    search_player_notebook,
    jump_player_notebook,
    update_player_notebook,
)

PLAYER_PROMPT_NAME = "llm_player.prompt"
HUMAN_PROMPT_NAME = "human_player_turn.prompt"

PLAYER_TOOLS = [
    request_interrupt,
    nominate_next_speaker,
    append_dialogue_history,
    read_player_reference_page,
    read_player_reference_section,
    search_player_reference,
    lookup_player_reference_index,
    query_phb_documents,
    query_odyssey_player_handbook,
    read_player_notebook,
    search_player_notebook,
    jump_player_notebook,
    update_player_notebook,
]


class LLMPlayerAgent:
    """LLM-controlled player that can only operate on its own turn."""

    def __init__(self, actor_id: str, *, llm=None, prompts_dir: Path | None = None) -> None:
        if actor_id not in PLAYER_IDS or actor_id == "human_player":
            raise ValueError("LLMPlayerAgent actor_id must be one of llm_player_1..3.")
        self.actor_id = actor_id
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self.llm = llm or build_default_player_llm()

    def get_prompt_text(self) -> str:
        return load_prompt(PLAYER_PROMPT_NAME, prompts_dir=self.prompts_dir)

    def build_prompt(self, *, active_speaker: str, upcoming_order: str = "", extra_context: str = "") -> str:
        template = self.get_prompt_text().strip()
        return render_prompt(
            template,
            {
                "actor_id": self.actor_id,
                "active_speaker": active_speaker,
                "upcoming_order": upcoming_order or "unknown",
                "extra_context": extra_context.strip() or "(none)",
            },
        )

    def build_agent(self, *, active_speaker: str, upcoming_order: str = "", extra_context: str = ""):
        prompt = self.build_prompt(
            active_speaker=active_speaker,
            upcoming_order=upcoming_order,
            extra_context=extra_context,
        )
        return create_react_agent(self.llm, PLAYER_TOOLS, prompt=prompt, name=f"{self.actor_id}_dialogue_agent")

    def take_turn(self, user_message: str, *, active_speaker: str, upcoming_order: str = "", extra_context: str = "") -> str:
        if active_speaker != self.actor_id:
            raise ValueError(f"{self.actor_id} cannot act when active_speaker is {active_speaker!r}.")
        agent = self.build_agent(
            active_speaker=active_speaker,
            upcoming_order=upcoming_order,
            extra_context=extra_context,
        )
        result = agent.invoke({"messages": [("user", user_message)]})
        return final_ai_text(result["messages"])


class HumanPlayer:
    """Wrapper for the real player's turn and notebook access."""

    def __init__(self, actor_id: str = "human_player", *, prompts_dir: Path | None = None) -> None:
        if actor_id != "human_player":
            raise ValueError("HumanPlayer must use actor_id='human_player'.")
        self.actor_id = actor_id
        self.prompts_dir = prompts_dir or PROMPTS_DIR

    def get_prompt_text(self) -> str:
        return load_prompt(HUMAN_PROMPT_NAME, prompts_dir=self.prompts_dir)

    def submit_turn(self, message: str) -> str:
        if not message.strip():
            raise ValueError("Human player turn message must not be empty.")
        return invoke_tool(append_dialogue_history, speaker_id=self.actor_id, message=message)

    def request_interrupt(self, reason: str = "") -> str:
        return invoke_tool(request_interrupt, actor_id=self.actor_id, reason=reason)

    def nominate_next_speaker(self, next_speaker: str, reason: str = "") -> str:
        return invoke_tool(nominate_next_speaker, actor_id=self.actor_id, next_speaker=next_speaker, reason=reason)

    def read_my_notebook(self, notebook_name: str) -> str:
        return invoke_tool(read_player_notebook, actor_id=self.actor_id, owner_id=self.actor_id, notebook_name=notebook_name)

    def update_my_notebook(self, notebook_name: str, content: str, mode: str = "append", heading: str = "") -> str:
        return invoke_tool(
            update_player_notebook,
            actor_id=self.actor_id,
            owner_id=self.actor_id,
            notebook_name=notebook_name,
            content=content,
            mode=mode,
            heading=heading,
        )
