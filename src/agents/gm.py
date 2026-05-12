"""GM agent for the GM-driven TRPG runtime."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from src.agents.runtime_common import (
    PROMPTS_DIR,
    build_default_gm_llm,
    final_ai_text,
    invoke_tool,
    load_prompt,
    render_prompt,
)
from src.tools.tools import NOTEBOOKS_DIR
from src.tools.tools import ALL_TOOLS, initialize_dialogue_state

GM_PROMPT_NAME = "gm_session.prompt"
DEFAULT_GM_LOG_PATH = NOTEBOOKS_DIR / "history" / "debug" / "gm_dialogue_agent.log.md"


class GMAgent:
    """Primary controller for dialogue, narration, and notebook maintenance."""

    def __init__(self, *, llm=None, prompts_dir: Path | None = None, log_path: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self.llm = llm or build_default_gm_llm()
        self.log_path = log_path or DEFAULT_GM_LOG_PATH

    def get_prompt_text(self) -> str:
        return load_prompt(GM_PROMPT_NAME, prompts_dir=self.prompts_dir)

    def initialize_runtime(self, default_order: list[str] | None = None) -> str:
        return invoke_tool(initialize_dialogue_state, default_order_csv=",".join(default_order) if default_order else "")

    def build_prompt(self, *, active_speaker: str = "gm", upcoming_order: str = "", extra_context: str = "") -> str:
        template = self.get_prompt_text().strip()
        return render_prompt(
            template,
            {
                "active_speaker": active_speaker,
                "upcoming_order": upcoming_order or "unknown",
                "extra_context": extra_context.strip() or "(none)",
            },
        )

    def build_agent(self, *, active_speaker: str = "gm", upcoming_order: str = "", extra_context: str = ""):
        prompt = self.build_prompt(
            active_speaker=active_speaker,
            upcoming_order=upcoming_order,
            extra_context=extra_context,
        )
        return create_react_agent(self.llm, ALL_TOOLS, prompt=prompt, name="gm_dialogue_agent")

    @staticmethod
    def _count_tool_calls(messages: list[BaseMessage]) -> int:
        return sum(len(getattr(message, "tool_calls", []) or []) for message in messages if isinstance(message, AIMessage))

    @staticmethod
    def _collect_usage(messages: list[BaseMessage]) -> dict[str, Any]:
        usages: list[dict[str, Any]] = []
        for index, message in enumerate(messages, start=1):
            usage = getattr(message, "usage_metadata", None)
            if usage:
                usages.append({"message_index": index, **dict(usage)})
                continue
            response_metadata = getattr(message, "response_metadata", None) or {}
            token_usage = response_metadata.get("token_usage")
            if token_usage:
                usages.append({"message_index": index, **dict(token_usage)})

        totals = {
            "input_tokens": sum(int(item.get("input_tokens", 0) or 0) for item in usages),
            "output_tokens": sum(int(item.get("output_tokens", 0) or 0) for item in usages),
            "total_tokens": sum(
                int(item.get("total_tokens", (item.get("input_tokens", 0) or 0) + (item.get("output_tokens", 0) or 0)) or 0)
                for item in usages
            ),
            "per_message": usages,
        }
        return totals

    def _append_log(
        self,
        *,
        prompt_text: str,
        inputs: dict[str, Any],
        messages: list[BaseMessage],
        result_summary: dict[str, Any],
    ) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            f"## {timestamp} | gm_turn",
            "",
            f"- prompt_file: `{GM_PROMPT_NAME}`",
            "- log_scope: prompt snapshot + user input + tool calls + tool outputs + visible assistant messages + token usage",
            "",
            "### Inputs",
            "",
            "```json",
            json.dumps(inputs, ensure_ascii=False, indent=2),
            "```",
            "",
            "### Prompt Snapshot",
            "",
            "```text",
            prompt_text.strip() or "<empty prompt>",
            "```",
            "",
            "### Message Trace",
            "",
        ]

        for index, message in enumerate(messages, start=1):
            if isinstance(message, HumanMessage):
                lines.append(f"#### Message {index} | HumanMessage")
                lines.append("")
                lines.append(str(message.content).strip() or "<empty>")
                lines.append("")
                continue

            if isinstance(message, AIMessage):
                lines.append(f"#### Message {index} | AIMessage")
                lines.append("")
                content = str(message.content).strip()
                if content:
                    lines.append("Visible assistant content:")
                    lines.append("")
                    lines.append(content)
                    lines.append("")
                tool_calls = getattr(message, "tool_calls", []) or []
                if tool_calls:
                    lines.append("Tool calls:")
                    lines.append("")
                    for tool_call in tool_calls:
                        lines.append(f"- {tool_call.get('name')}({json.dumps(tool_call.get('args', {}), ensure_ascii=False)})")
                    lines.append("")
                usage = getattr(message, "usage_metadata", None) or getattr(message, "response_metadata", {}).get("token_usage")
                if usage:
                    lines.append("Token usage:")
                    lines.append("")
                    lines.append("```json")
                    lines.append(json.dumps(usage, ensure_ascii=False, indent=2))
                    lines.append("```")
                    lines.append("")
                continue

            if isinstance(message, ToolMessage):
                lines.append(f"#### Message {index} | ToolMessage")
                lines.append("")
                lines.append(f"- tool_name: `{message.name}`")
                lines.append("")
                lines.append(str(message.content).strip() or "<empty>")
                lines.append("")
                continue

            lines.append(f"#### Message {index} | {type(message).__name__}")
            lines.append("")
            lines.append(str(getattr(message, 'content', '')).strip() or "<empty>")
            lines.append("")

        lines.extend(["### Result Summary", "", "```json", json.dumps(result_summary, ensure_ascii=False, indent=2), "```", "", "---", ""])
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

    def take_turn(self, user_message: str, *, active_speaker: str = "gm", upcoming_order: str = "", extra_context: str = "") -> str:
        if active_speaker != "gm":
            raise ValueError(f"GMAgent can only act on the GM turn, not {active_speaker!r}.")
        prompt_text = self.build_prompt(
            active_speaker=active_speaker,
            upcoming_order=upcoming_order,
            extra_context=extra_context,
        )
        agent = self.build_agent(
            active_speaker=active_speaker,
            upcoming_order=upcoming_order,
            extra_context=extra_context,
        )
        result = agent.invoke({"messages": [("user", user_message)]})
        messages = result["messages"]
        final_response = final_ai_text(messages)
        self._append_log(
            prompt_text=prompt_text,
            inputs={
                "user_message": user_message,
                "active_speaker": active_speaker,
                "upcoming_order": upcoming_order,
                "extra_context": extra_context,
            },
            messages=messages,
            result_summary={
                "tool_call_count": self._count_tool_calls(messages),
                "message_count": len(messages),
                "token_usage": self._collect_usage(messages),
                "final_response": final_response,
                "log_path": str(self.log_path),
            },
        )
        return final_response
