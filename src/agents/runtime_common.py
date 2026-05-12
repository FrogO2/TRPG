"""Shared runtime helpers for GM and player agents."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def load_prompt(prompt_name: str, *, prompts_dir: Path | None = None) -> str:
    prompt_path = (prompts_dir or PROMPTS_DIR) / prompt_name
    if not prompt_path.exists():
        return ""
    return prompt_path.read_text(encoding="utf-8")


def render_prompt(template: str, replacements: Mapping[str, Any]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def build_default_chat_llm(
    *,
    model_name: str,
    enable_thinking: bool,
) -> BaseChatModel:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError("langchain-openai is required to build the GM/player chat models.") from exc

    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("TRPG_RULE_AGENT_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
    )
    if not api_key:
        raise ValueError(
            "Set OPENAI_API_KEY, TRPG_RULE_AGENT_API_KEY, or DASHSCOPE_API_KEY to create runtime chat models."
        )

    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "model": model_name,
        "temperature": float(os.getenv("TRPG_DIALOGUE_TEMPERATURE", "0.2")),
        "extra_body": {"enable_thinking": enable_thinking},
    }
    base_url = (
        os.getenv("TRPG_DIALOGUE_BASE_URL")
        or os.getenv("TRPG_OPENAI_BASE_URL")
        or os.getenv("TRPG_DASHSCOPE_API_BASE")
        or DEFAULT_DASHSCOPE_BASE_URL
    )
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def build_default_gm_llm() -> BaseChatModel:
    return build_default_chat_llm(
        model_name=os.getenv("TRPG_GM_MODEL") or os.getenv("TRPG_DIALOGUE_MODEL") or "deepseek-v4-flash",
        enable_thinking=os.getenv("TRPG_GM_ENABLE_THINKING", "true").strip().lower() not in {"0", "false", "no"},
    )


def build_default_player_llm() -> BaseChatModel:
    return build_default_chat_llm(
        model_name=os.getenv("TRPG_PLAYER_MODEL") or os.getenv("TRPG_DIALOGUE_MODEL") or "deepseek-v4-flash",
        enable_thinking=os.getenv("TRPG_PLAYER_ENABLE_THINKING", "true").strip().lower() not in {"0", "false", "no"},
    )


def stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or json.dumps(item, ensure_ascii=False)))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def final_ai_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = stringify_content(message.content).strip()
            if content:
                return content
    return ""


def invoke_tool(tool_obj: Any, /, **kwargs: Any) -> Any:
    if hasattr(tool_obj, "invoke"):
        return tool_obj.invoke(kwargs)
    return tool_obj(**kwargs)
