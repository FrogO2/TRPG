#!/usr/bin/env python3
"""LangGraph/React implementation of the Rule Retreival Agent.

The agent uses a real planning loop backed by ``create_react_agent`` and the
project's markdown-first rulebook tools.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS_DIR = PROJECT_ROOT / "documents"
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DEFAULT_SUMMARY_PATH = NOTEBOOKS_DIR / "rules_summary.md"
DEFAULT_LOG_PATH = NOTEBOOKS_DIR / "history" / "debug" / "rule_retrieval_agent.log.md"
DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_RULE_AGENT_MODEL = "qwen3-max"
DEFAULT_RULE_SUMMARIZER_MODEL = "qwen3.5-flash"
DEFAULT_NOTE_SOURCE_CHAR_LIMIT = 6000
DEFAULT_PAGE_READ_CHAR_LIMIT = 2200
DEFAULT_SECTION_READ_CHAR_LIMIT = 2600

BOOTSTRAP_PROMPT_NAME = "rule_retreival_bootstrap.prompt"
SEARCH_PROMPT_NAME = "rule_retreival_search.prompt"

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_space(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip())


def _stringify_content(content: Any) -> str:
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


def _extract_excerpt(text: str, query: str = "", *, width: int = 220) -> str:
    stripped = _normalize_space(text)
    if not stripped:
        return ""
    if not query:
        return stripped[:width] + ("..." if len(stripped) > width else "")

    lower_text = stripped.lower()
    lower_query = query.lower().strip()
    idx = lower_text.find(lower_query)
    if idx < 0:
        return stripped[:width] + ("..." if len(stripped) > width else "")

    start = max(0, idx - width // 3)
    end = min(len(stripped), idx + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(stripped) else ""
    return prefix + stripped[start:end].strip() + suffix


def _truncate_text(text: str, *, limit: int, suffix: str = "\n\n...[truncated]") -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    trimmed = text[: max(limit - len(suffix), 0)].rstrip()
    return trimmed + suffix


def _page_range_label(pages: Sequence[int]) -> str:
    if not pages:
        return "unknown"
    ordered = sorted(set(int(page) for page in pages))
    if len(ordered) == 1:
        return str(ordered[0])
    return f"{ordered[0]}-{ordered[-1]}"


def _build_toc_entries(blocks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int]] = set()
    for block in blocks:
        page_num = int(block.get("page_num", -1))
        for level, title in enumerate(block.get("sections", []), start=1):
            key = (page_num, title, level)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"page_num": page_num, "title": title, "heading_level": level})
    return entries


class RuleRetrievalAgent:
    """A LangGraph/React agent for rule compilation and rule lookup."""

    def __init__(
        self,
        *,
        llm: BaseChatModel | None = None,
        summary_llm: BaseChatModel | None = None,
        prompts_dir: Path | None = None,
        notebooks_dir: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self.notebooks_dir = notebooks_dir or NOTEBOOKS_DIR
        self.log_path = log_path or DEFAULT_LOG_PATH
        self.llm = llm or self._build_default_llm()
        self.summary_llm = summary_llm

    def list_available_doc_ids(self) -> list[str]:
        return sorted(path.stem for path in DOCUMENTS_DIR.glob("*.md"))

    def get_log_path(self) -> Path:
        return self.log_path

    def get_prompt_text(self, mode: str) -> str:
        return self._load_prompt(self._prompt_name(mode))

    def compile_rules_summary(
        self,
        *,
        doc_ids: Sequence[str] | None = None,
        output_path: str | Path | None = None,
        invocation_source: str = "direct",
    ) -> dict[str, Any]:
        selected_doc_ids = self._select_doc_ids(doc_ids)
        destination = Path(output_path) if output_path else DEFAULT_SUMMARY_PATH
        destination.parent.mkdir(parents=True, exist_ok=True)
        compressed_notes = self._build_compressed_rule_notes(selected_doc_ids)

        prompt_text = self._compose_prompt(
            "bootstrap",
            selected_doc_ids,
            destination=destination,
            compressed_note_count=len(compressed_notes),
        )
        agent = create_react_agent(
            self.llm,
            self._build_tools(
                mode="bootstrap",
                doc_ids=selected_doc_ids,
                destination=destination,
                compressed_notes=compressed_notes,
            ),
            prompt=prompt_text,
            name="rule_retreival_bootstrap",
        )
        user_message = self._bootstrap_request(selected_doc_ids, destination, len(compressed_notes))
        result = agent.invoke({"messages": [("user", user_message)]})
        messages = result["messages"]

        if not destination.exists():
            raise RuntimeError("Rule Retreival Agent did not call write_rules_summary; no summary file was produced.")

        self._append_log(
            mode="bootstrap",
            prompt_name=BOOTSTRAP_PROMPT_NAME,
            prompt_text=prompt_text,
            invocation_source=invocation_source,
            inputs={
                "doc_ids": selected_doc_ids,
                "output_path": str(destination),
                "compressed_note_count": len(compressed_notes),
                "compressed_note_ids": [note["note_id"] for note in compressed_notes],
                "compression_model": self._model_name(self.summary_llm or self._build_summary_llm()),
                "user_message": user_message,
            },
            messages=messages,
            result_summary={
                "output_path": str(destination),
                "compressed_note_count": len(compressed_notes),
                "tool_call_count": self._count_tool_calls(messages),
                "final_response": self._final_ai_text(messages),
            },
        )

        return {
            "output_path": str(destination),
            "log_path": str(self.log_path),
            "doc_ids": selected_doc_ids,
            "compressed_note_count": len(compressed_notes),
            "tool_call_count": self._count_tool_calls(messages),
            "message_count": len(messages),
        }

    def answer_rule_query(
        self,
        query: str,
        *,
        doc_ids: Sequence[str] | None = None,
        top_k: int = 5,
        invocation_source: str = "direct",
    ) -> str:
        if not query.strip():
            raise ValueError("query must not be empty")

        selected_doc_ids = self._select_doc_ids(doc_ids)
        prompt_text = self._compose_prompt("search", selected_doc_ids)
        agent = create_react_agent(
            self.llm,
            self._build_tools(mode="search", doc_ids=selected_doc_ids),
            prompt=prompt_text,
            name="rule_retreival_search",
        )
        user_message = self._search_request(query, selected_doc_ids, top_k)
        result = agent.invoke({"messages": [("user", user_message)]})
        messages = result["messages"]
        final_response = self._final_ai_text(messages)
        if not final_response.strip():
            raise RuntimeError("Rule Retreival Agent produced no final response for the search request.")

        self._append_log(
            mode="search",
            prompt_name=SEARCH_PROMPT_NAME,
            prompt_text=prompt_text,
            invocation_source=invocation_source,
            inputs={
                "query": query,
                "doc_ids": selected_doc_ids,
                "top_k": top_k,
                "user_message": user_message,
            },
            messages=messages,
            result_summary={
                "tool_call_count": self._count_tool_calls(messages),
                "final_response": final_response,
            },
        )
        return final_response

    def _build_default_llm(self) -> BaseChatModel:
        model_name = os.getenv("TRPG_RULE_AGENT_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_RULE_AGENT_MODEL
        enable_thinking = os.getenv("TRPG_RULE_AGENT_ENABLE_THINKING", "true").strip().lower() not in {"0", "false", "no"}
        return self._build_chat_llm(model_name=model_name, enable_thinking=enable_thinking)

    def _build_summary_llm(self) -> BaseChatModel:
        model_name = os.getenv("TRPG_RULE_SUMMARIZER_MODEL") or DEFAULT_RULE_SUMMARIZER_MODEL
        enable_thinking = os.getenv("TRPG_RULE_SUMMARIZER_ENABLE_THINKING", "false").strip().lower() not in {"0", "false", "no"}
        return self._build_chat_llm(model_name=model_name, enable_thinking=enable_thinking)

    def _build_chat_llm(self, *, model_name: str, enable_thinking: bool) -> BaseChatModel:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ImportError(
                "langchain-openai is required to create the default Rule Retreival Agent model. Install it or pass an explicit llm instance."
            ) from exc

        api_key = (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("TRPG_RULE_AGENT_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
        )
        if not api_key:
            raise ValueError(
                "To build the default Rule Retreival Agent, set TRPG_RULE_AGENT_API_KEY, DASHSCOPE_API_KEY, or OPENAI_API_KEY, or pass an explicit llm object."
            )

        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "model": model_name,
            "temperature": float(os.getenv("TRPG_RULE_AGENT_TEMPERATURE", "0")),
            "extra_body": {"enable_thinking": enable_thinking},
        }
        base_url = (
            os.getenv("TRPG_RULE_AGENT_BASE_URL")
            or os.getenv("TRPG_OPENAI_BASE_URL")
            or os.getenv("TRPG_DASHSCOPE_API_BASE")
            or DEFAULT_DASHSCOPE_BASE_URL
        )
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    def _build_tools(
        self,
        *,
        mode: str,
        doc_ids: Sequence[str],
        destination: Path | None = None,
        compressed_notes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[Any]:
        allowed_doc_ids = list(doc_ids)
        allowed_set = set(allowed_doc_ids)
        bootstrap_notes = list(compressed_notes or [])
        note_map = {note["note_id"]: note for note in bootstrap_notes}

        @tool
        def list_rule_documents() -> str:
            """List the rule documents currently in scope for this task."""
            return "\n".join(allowed_doc_ids)

        @tool
        def lookup_rule_index(doc_id: str, keyword: str) -> str:
            """Find matching headings and page numbers for a keyword in one rule document."""
            error = self._ensure_allowed_doc_id(doc_id, allowed_set)
            if error:
                return error
            blocks = self._load_blocks(doc_id)
            if not blocks:
                return f"Document '{doc_id}' not found."
            matches = [entry for entry in _build_toc_entries(blocks) if keyword.lower() in entry["title"].lower()]
            if not matches:
                return f"No TOC entries matching '{keyword}' in '{doc_id}'."
            lines = [f"TOC matches for '{keyword}' in '{doc_id}':"]
            for entry in matches[:12]:
                lines.append(f"- {'#' * entry['heading_level']} {entry['title']} -> page {entry['page_num']}")
            return "\n".join(lines)

        @tool
        def search_rule_document(doc_id: str, query: str, top_k: int = 5) -> str:
            """Search a rule document for exact text matches and short context snippets."""
            error = self._ensure_allowed_doc_id(doc_id, allowed_set)
            if error:
                return error
            blocks = self._load_blocks(doc_id)
            if not blocks:
                return f"Document '{doc_id}' not found."
            needle = query.lower()
            scored: list[tuple[int, int, list[str], str]] = []
            for block in blocks:
                sections = block.get("sections", [])
                markdown = block.get("markdown", "")
                haystack = "\n".join([*sections, markdown]).lower()
                count = haystack.count(needle)
                if count > 0:
                    scored.append((count, int(block.get("page_num", -1)), list(sections), markdown))
            if not scored:
                return f"No matches for '{query}' in '{doc_id}'."
            scored.sort(key=lambda item: (-item[0], item[1]))
            lines = [f"Found '{query}' in '{doc_id}'. Showing top {min(top_k, len(scored))} matches:"]
            for count, page_num, sections, markdown in scored[:top_k]:
                section_label = " > ".join(sections[:4]) if sections else "未标注章节"
                lines.append(f"- page {page_num} | {section_label} | hits={count} | {_extract_excerpt(markdown, query)}")
            return "\n".join(lines)

        @tool
        def read_rule_page(doc_id: str, page: int, max_chars: int = DEFAULT_PAGE_READ_CHAR_LIMIT) -> str:
            """Read all markdown blocks belonging to one page of a rule document."""
            error = self._ensure_allowed_doc_id(doc_id, allowed_set)
            if error:
                return error
            blocks = [block for block in self._load_blocks(doc_id) if int(block.get("page_num", -1)) == page]
            if not blocks:
                return f"Page {page} not found in '{doc_id}'."
            lines = [f"[{doc_id} · page {page}]"]
            for block in blocks:
                section_label = " > ".join(block.get("sections", [])[:4]) if block.get("sections") else "未标注章节"
                lines.append(f"\n§ {section_label}\n{block.get('markdown', '').strip()}")
            rendered = "\n\n---\n\n".join(lines)
            return _truncate_text(rendered, limit=max_chars)

        @tool
        def read_rule_section(doc_id: str, section_title: str, max_chars: int = DEFAULT_SECTION_READ_CHAR_LIMIT) -> str:
            """Read blocks whose heading hierarchy matches a requested section title."""
            error = self._ensure_allowed_doc_id(doc_id, allowed_set)
            if error:
                return error
            blocks = self._load_blocks(doc_id)
            if not blocks:
                return f"Document '{doc_id}' not found."
            needle = section_title.lower()
            hits = []
            for block in blocks:
                if any(needle in heading.lower() for heading in block.get("sections", [])):
                    section_label = " > ".join(block.get("sections", [])[:4]) if block.get("sections") else "未标注章节"
                    hits.append(f"[{doc_id} · page {block.get('page_num', -1)} · {section_label}]\n{block.get('markdown', '')}")
            if not hits:
                return f"No section matching '{section_title}' found in '{doc_id}'."
            return _truncate_text("\n\n---\n\n".join(hits[:8]), limit=max_chars)

        @tool
        def read_existing_rules_summary() -> str:
            """Read the current GM-facing rules summary markdown if it already exists."""
            if not DEFAULT_SUMMARY_PATH.exists():
                return "No existing rules_summary.md file yet."
            return DEFAULT_SUMMARY_PATH.read_text(encoding="utf-8")

        tools: list[Any] = [
            list_rule_documents,
            lookup_rule_index,
            search_rule_document,
            read_rule_page,
            read_rule_section,
            read_existing_rules_summary,
        ]

        if mode == "bootstrap":
            if destination is None:
                raise ValueError("bootstrap mode requires a destination path")

            @tool
            def list_compressed_rule_notes() -> str:
                """List the compressed rule notes prepared by the small summarizer model."""
                if not bootstrap_notes:
                    return "No compressed rule notes available."
                lines = [f"Compressed rule notes ({len(bootstrap_notes)}):"]
                for note in bootstrap_notes[:16]:
                    lines.append(
                        f"- {note['note_id']} | {note['doc_id']} | pages {note['page_range']} | {note['section_title']} | {_extract_excerpt(note['summary'], width=140)}"
                    )
                if len(bootstrap_notes) > 16:
                    lines.append(f"... {len(bootstrap_notes) - 16} more notes omitted")
                return "\n".join(lines)

            @tool
            def read_compressed_rule_note(note_id: str) -> str:
                """Read one compressed rule note generated by the small summarizer model."""
                note = note_map.get(note_id)
                if note is None:
                    return f"Compressed note '{note_id}' not found."
                return "\n".join(
                    [
                        f"note_id: {note['note_id']}",
                        f"doc_id: {note['doc_id']}",
                        f"section_title: {note['section_title']}",
                        f"page_range: {note['page_range']}",
                        f"headings: {' > '.join(note['headings']) if note['headings'] else '(none)'}",
                        "summary:",
                        note['summary'],
                    ]
                )

            tools.extend([list_compressed_rule_notes, read_compressed_rule_note])

            @tool
            def write_rules_summary(markdown: str) -> str:
                """Write the final GM-facing rules summary markdown to the requested output path."""
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(markdown.strip() + "\n", encoding="utf-8")
                return f"rules_summary written to {destination}"

            tools.append(write_rules_summary)

        return tools

    def _compose_prompt(
        self,
        mode: str,
        doc_ids: Sequence[str],
        *,
        destination: Path | None = None,
        compressed_note_count: int = 0,
    ) -> str:
        base_prompt = self.get_prompt_text(mode).strip()
        runtime_rules = [
            f"当前可用文档范围：{', '.join(doc_ids)}。",
            "你必须只使用提供的工具读取、定位和确认规则，不要凭空编造页码或章节。",
            "不要输出隐藏 chain-of-thought；如果需要说明过程，只输出可审计的简短依据。",
        ]
        if mode == "bootstrap":
            runtime_rules.extend(
                [
                    f"本次任务的最终产物必须写入 {destination}。",
                    f"当前已经准备了 {compressed_note_count} 条由小模型生成的压缩规则笔记。",
                    "优先使用 list_compressed_rule_notes 和 read_compressed_rule_note 消化压缩笔记，只有在需要确认例外、页码或原文措辞时才调用原文阅读工具。",
                    "在确认摘要可交付前，必须调用 write_rules_summary 工具。",
                    "如果规则存在例外或冲突，请在最终 Markdown 中明确标记待 GM 复核。",
                ]
            )
        else:
            runtime_rules.extend(
                [
                    "最终回答必须先给结论，再给依据和引用。",
                    "如果证据不足或存在冲突，需要明确说明需要 GM 最终裁定。",
                ]
            )
        return "\n\n".join(part for part in [base_prompt, "\n".join(runtime_rules)] if part)

    def _bootstrap_request(self, doc_ids: Sequence[str], destination: Path, compressed_note_count: int) -> str:
        return (
            "请作为 Rule Retreival Agent 的开局整理模式工作。\n"
            f"本次允许使用的文档只有：{', '.join(doc_ids)}。\n"
            f"系统已经先用小模型为你准备了 {compressed_note_count} 条压缩规则笔记。\n"
            "请优先基于这些压缩笔记组织摘要，只在关键细节需要复核时再回看原文。\n"
            f"最终必须调用 write_rules_summary，把完整 Markdown 写到 {destination}。"
        )

    def _search_request(self, query: str, doc_ids: Sequence[str], top_k: int) -> str:
        return (
            "请作为 Rule Retreival Agent 的运行期规则调查模式工作。\n"
            f"问题：{query}\n"
            f"文档范围：{', '.join(doc_ids)}\n"
            f"请自主使用工具定位、回看并确认规则。最多引用 {top_k} 组关键证据。"
        )

    @staticmethod
    def _prompt_name(mode: str) -> str:
        if mode == "bootstrap":
            return BOOTSTRAP_PROMPT_NAME
        if mode == "search":
            return SEARCH_PROMPT_NAME
        raise ValueError(f"Unsupported mode: {mode}")

    def _load_prompt(self, prompt_name: str) -> str:
        prompt_path = self.prompts_dir / prompt_name
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return ""

    @staticmethod
    def _ensure_allowed_doc_id(doc_id: str, allowed_doc_ids: set[str]) -> str | None:
        if doc_id not in allowed_doc_ids:
            return f"Document '{doc_id}' is outside the current agent scope. Allowed docs: {sorted(allowed_doc_ids)}"
        return None

    def _select_doc_ids(self, doc_ids: Sequence[str] | None) -> list[str]:
        selected = list(doc_ids or self.list_available_doc_ids())
        if not selected:
            raise ValueError("No markdown rule documents are available.")
        return selected

    @staticmethod
    def _load_blocks(doc_id: str) -> list[dict[str, Any]]:
        from src.rag.rag import _iter_markdown_blocks, _resolve_markdown_path

        markdown_path = _resolve_markdown_path(doc_id)
        if markdown_path is None:
            return []
        return _iter_markdown_blocks(doc_id, markdown_path)

    def _build_compressed_rule_notes(self, doc_ids: Sequence[str]) -> list[dict[str, Any]]:
        summarizer = self.summary_llm or self._build_summary_llm()
        self.summary_llm = summarizer
        notes: list[dict[str, Any]] = []
        for doc_id in doc_ids:
            blocks = self._load_blocks(doc_id)
            for group_index, group in enumerate(self._build_note_groups(doc_id, blocks), start=1):
                prompt = self._compression_request(group)
                response = summarizer.invoke([HumanMessage(content=prompt)])
                summary = _stringify_content(getattr(response, "content", response)).strip()
                notes.append(
                    {
                        "note_id": f"{doc_id}::note::{group_index}",
                        "doc_id": doc_id,
                        "section_title": group["section_title"],
                        "page_range": _page_range_label(group["pages"]),
                        "pages": sorted(set(group["pages"])),
                        "headings": group["headings"],
                        "summary": summary or "(empty summary)",
                    }
                )
        if not notes:
            raise ValueError("No compressed rule notes could be built from the selected markdown documents.")
        return notes

    def _build_note_groups(self, doc_id: str, blocks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for block in blocks:
            page_num = int(block.get("page_num", -1))
            headings = [heading for heading in block.get("sections", []) if heading]
            section_title = headings[0] if headings else f"untitled-pages-{max(page_num, 0) // 4}"
            rendered = self._render_block_for_note(block)
            should_split = (
                current is None
                or current["section_title"] != section_title
                or current["char_count"] + len(rendered) > DEFAULT_NOTE_SOURCE_CHAR_LIMIT
            )
            if should_split:
                if current is not None:
                    groups.append(current)
                current = {
                    "doc_id": doc_id,
                    "section_title": section_title,
                    "pages": [],
                    "headings": [],
                    "source_parts": [],
                    "char_count": 0,
                }
            current["pages"].append(page_num)
            for heading in headings[:4]:
                if heading not in current["headings"]:
                    current["headings"].append(heading)
            current["source_parts"].append(rendered)
            current["char_count"] += len(rendered)
        if current is not None:
            groups.append(current)
        return groups

    @staticmethod
    def _render_block_for_note(block: Mapping[str, Any]) -> str:
        section_label = " > ".join(block.get("sections", [])[:4]) if block.get("sections") else "未标注章节"
        body = _truncate_text(str(block.get("markdown", "")).strip(), limit=1400, suffix="\n...[block truncated]")
        return f"[page {int(block.get('page_num', -1))}] {section_label}\n{body}"

    def _compression_request(self, group: Mapping[str, Any]) -> str:
        source_text = "\n\n---\n\n".join(group["source_parts"])
        base_prompt = self.get_prompt_text("bootstrap").strip()
        return "\n\n".join(
            [
                base_prompt,
                "补充说明：你现在处于小模型压缩笔记阶段，不直接生成最终 GM 备忘录，而是为后续大模型整理准备中间规则笔记。",
                f"文档：{group['doc_id']}",
                f"主题：{group['section_title']}",
                f"页码范围：{_page_range_label(group['pages'])}",
                "输出要求：",
                "1. 只保留 GM 在开局和运行流程中最需要记住的流程、限制、例外和待复核点。",
                "2. 使用简洁中文 Markdown 项目符号。",
                "3. 每条尽量附页码。",
                "4. 不要长段抄原文。",
                "5. 不要输出最终成稿式大纲，只输出给后续大模型复用的压缩笔记。",
                "原文材料：",
                "```text",
                source_text,
                "```",
            ]
        )

    @staticmethod
    def _model_name(llm: BaseChatModel) -> str:
        return str(getattr(llm, "model_name", getattr(llm, "model", llm.__class__.__name__)))

    @staticmethod
    def _final_ai_text(messages: Sequence[BaseMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
                content = _stringify_content(message.content).strip()
                if content:
                    return content
        return ""

    @staticmethod
    def _count_tool_calls(messages: Sequence[BaseMessage]) -> int:
        return sum(len(getattr(message, "tool_calls", []) or []) for message in messages if isinstance(message, AIMessage))

    def _append_log(
        self,
        *,
        mode: str,
        prompt_name: str,
        prompt_text: str,
        invocation_source: str,
        inputs: Mapping[str, Any],
        messages: Sequence[BaseMessage],
        result_summary: Mapping[str, Any],
    ) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            f"## {timestamp} | {mode}",
            "",
            f"- invocation_source: `{invocation_source}`",
            f"- prompt_file: `{prompt_name}`",
            "- log_scope: prompt snapshot + user input + tool calls + tool outputs + visible assistant messages",
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
                lines.append(_stringify_content(message.content).strip() or "<empty>")
                lines.append("")
                continue

            if isinstance(message, AIMessage):
                lines.append(f"#### Message {index} | AIMessage")
                lines.append("")
                content = _stringify_content(message.content).strip()
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
                continue

            if isinstance(message, ToolMessage):
                lines.append(f"#### Message {index} | ToolMessage")
                lines.append("")
                lines.append(f"- tool_name: `{message.name}`")
                lines.append("")
                lines.append(_stringify_content(message.content).strip() or "<empty>")
                lines.append("")
                continue

            lines.append(f"#### Message {index} | {type(message).__name__}")
            lines.append("")
            lines.append(_stringify_content(getattr(message, 'content', '')).strip() or "<empty>")
            lines.append("")

        lines.extend(["### Result Summary", "", "```json", json.dumps(result_summary, ensure_ascii=False, indent=2), "```", "", "---", ""])
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))


RuleRetreivalAgent = RuleRetrievalAgent


def compile_rules_summary(
    doc_ids: Sequence[str] | None = None,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    agent = RuleRetrievalAgent()
    return agent.compile_rules_summary(
        doc_ids=doc_ids,
        output_path=output_path,
        invocation_source="module:compile_rules_summary",
    )


def answer_rule_query(
    query: str,
    *,
    doc_ids: Sequence[str] | None = None,
    top_k: int = 5,
) -> str:
    agent = RuleRetrievalAgent()
    return agent.answer_rule_query(
        query,
        doc_ids=doc_ids,
        top_k=top_k,
        invocation_source="module:answer_rule_query",
    )