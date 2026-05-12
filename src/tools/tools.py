#!/usr/bin/env python3
"""TRPG agent tool layer.

All callables are decorated with LangChain's @tool so they can be passed
directly to a LangGraph / LangChain agent.  Import ALL_TOOLS for convenient
wiring::

    from src.tools.tools import ALL_TOOLS
    from langgraph.prebuilt import create_react_agent
    agent = create_react_agent(llm, ALL_TOOLS)

Tool groups
-----------
Dice        roll_dice
Document    read_document_page · read_document_section
            search_document · lookup_index
RAG         query_rules_tool · query_lore_tool
Rule Agent  compile_rules_summary · answer_rule_query
Notebook    read_notebook · update_notebook
            append_log · summarize_log
Dialogue    initialize_dialogue_state · read_dialogue_state
            get_upcoming_speakers · set_temporary_speaking_order
            request_interrupt · approve_interrupt
            nominate_next_speaker · append_dialogue_history
            summarize_dialogue_history · read_player_notebook
            search_player_notebook · jump_player_notebook
            update_player_notebook
Turn        advance_turn

Notebook layout (data/notebooks/)
----------------------------------
  scene_state.json      – mode, round, active_speaker, scene/initiative order
  party_state.json      – player HP, spell slots, conditions, inventory
  npc_registry.json     – NPC profiles, attitudes, relationships
  combat_state.json     – active combatants, HP, conditions, pending actions
  memory_index.json     – summary pointers, update timestamps
  campaign_summary.md   – chapter summaries, story milestones
    rules_summary.md      – GM-facing rules digest compiled from rulebooks
  log/game.log          – timestamped event stream

Dialogue layout (notebooks/)
----------------------------
    dialogue_state.json                 – current speaker order and overrides
    shared/dialogue_history.md          – append-only shared dialogue record
    shared/dialogue_summary.md          – rolling compressed shared history
    gm/campaign_brief.md                – GM-facing runtime notes
    players/human_player/*.md           – real player's notebook placeholders
    players/llm_player_1/*.md           – LLM player 1 notebooks
    players/llm_player_2/*.md           – LLM player 2 notebooks
    players/llm_player_3/*.md           – LLM player 3 notebooks
"""

from __future__ import annotations

import datetime
import importlib
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

try:
    tool = importlib.import_module("langchain_core.tools").tool
except ImportError:
    class _CompatTool:
        def __init__(self, func):
            self.func = func
            self.__name__ = getattr(func, "__name__", "tool")
            self.__doc__ = getattr(func, "__doc__", None)

        def __call__(self, *args, **kwargs):
            return self.func(*args, **kwargs)

        def invoke(self, input_data=None, **kwargs):
            if isinstance(input_data, dict):
                return self.func(**input_data)
            if input_data is None:
                return self.func(**kwargs)
            if kwargs:
                raise TypeError("Compat tool invoke does not support mixed positional and keyword input")
            return self.func(input_data)

    def tool(func=None, *args, **kwargs):
        if func is not None and callable(func) and not args and not kwargs:
            return _CompatTool(func)

        def decorator(inner):
            return _CompatTool(inner)

        return decorator

# ---------------------------------------------------------------------------
# Path constants  (all anchored to project root = two levels above this file)
# ---------------------------------------------------------------------------
PROJECT_ROOT    = Path(__file__).resolve().parents[2]
DATA_DIR        = PROJECT_ROOT / "data"
DOCUMENTS_DIR   = PROJECT_ROOT / "documents"
NOTEBOOKS_DIR   = PROJECT_ROOT / "notebooks"
LOG_DIR         = NOTEBOOKS_DIR / "log"
DIALOGUE_STATE_PATH = NOTEBOOKS_DIR / "dialogue_state.json"
SHARED_DIR = NOTEBOOKS_DIR / "shared"
PLAYERS_DIR = NOTEBOOKS_DIR / "players"
GM_DIR = NOTEBOOKS_DIR / "gm"
SHARED_HISTORY_PATH = SHARED_DIR / "dialogue_history.md"
SHARED_SUMMARY_PATH = SHARED_DIR / "dialogue_summary.md"

DEFAULT_DIALOGUE_ORDER = [
    "gm",
    "human_player",
    "llm_player_1",
    "llm_player_2",
    "llm_player_3",
]
PLAYER_IDS = ["human_player", "llm_player_1", "llm_player_2", "llm_player_3"]
ALL_ACTOR_IDS = [*PLAYER_IDS, "gm"]
PLAYER_NOTEBOOK_FILES = {
    "character_sheet": "5eDnD_角色卡_中译.md",
    "events": "events.md",
    "private_notes": "private_notes.md",
}
PLAYER_REFERENCE_DOCUMENTS = {
    "5eDnD_玩家手册PHB_中译v1.72版": "5eDnD_玩家手册PHB_中译v1.72版.md",
    "龙之君主的奥德赛-玩家手册": "龙之君主的奥德赛-玩家手册.md",
}
PLAYER_REFERENCE_INDEX_ALIASES = {
    "phb_documents": ["phb_documents", "phb_documents_qwen"],
    "odyssey_player_handbook": ["odyssey_player_handbook"],
}

# Mapping: section name → (filename, format)
_SECTIONS: dict[str, tuple[str, str]] = {
    "scene_state":      ("scene_state.json",    "json"),
    "party_state":      ("party_state.json",    "json"),
    "npc_registry":     ("npc_registry.json",   "json"),
    "combat_state":     ("combat_state.json",   "json"),
    "memory_index":     ("memory_index.json",   "json"),
    "campaign_summary": ("campaign_summary.md", "md"),
    "rules_summary":    ("rules_summary.md",    "md"),
}

VALID_SECTIONS = ", ".join(f"``{s}``" for s in _SECTIONS)


def _ensure_dirs() -> None:
    NOTEBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    GM_DIR.mkdir(parents=True, exist_ok=True)
    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)


def _load_player_character_sheet_template() -> str:
    template_path = DOCUMENTS_DIR / PLAYER_NOTEBOOK_FILES["character_sheet"]
    if template_path.exists():
        return template_path.read_text(encoding="utf-8").strip() + "\n"
    return (
        "# 角色卡\n\n"
        "## 角色\n\n"
        "### 角色名\n"
    )


def _ensure_dialogue_placeholders(*, reset_player_character_sheets: bool = False) -> None:
    _ensure_dirs()
    campaign_brief = GM_DIR / "campaign_brief.md"
    if not campaign_brief.exists():
        campaign_brief.write_text(
            "# Campaign Brief\n\n"
            "- System: TBD\n"
            "- Tone: TBD\n"
            "- Current scene: TBD\n"
            "- GM notes: fill during play.\n",
            encoding="utf-8",
        )

    if not SHARED_HISTORY_PATH.exists():
        SHARED_HISTORY_PATH.write_text("# Shared Dialogue History\n", encoding="utf-8")
    if not SHARED_SUMMARY_PATH.exists():
        SHARED_SUMMARY_PATH.write_text("# Shared Dialogue Summary\n", encoding="utf-8")

    for player_id in PLAYER_IDS:
        player_dir = PLAYERS_DIR / player_id
        player_dir.mkdir(parents=True, exist_ok=True)
        character_sheet_filename = PLAYER_NOTEBOOK_FILES["character_sheet"]
        character_sheet_path = player_dir / character_sheet_filename
        legacy_character_sheet_path = player_dir / "character_sheet.md"
        placeholders = {
            "events.md": (
                f"# {player_id} Events\n\n"
                "## Highlights\n\n"
                "- None yet.\n\n"
                "## Arc\n\n"
                "- None yet.\n\n"
                "## Setbacks\n\n"
                "- None yet.\n"
            ),
            "private_notes.md": (
                f"# {player_id} Private Notes\n\n"
                "- Keep this notebook in-character.\n"
            ),
        }

        if reset_player_character_sheets or not character_sheet_path.exists():
            character_sheet_path.write_text(_load_player_character_sheet_template(), encoding="utf-8")
        if legacy_character_sheet_path.exists() and legacy_character_sheet_path != character_sheet_path:
            legacy_character_sheet_path.unlink()

        for filename, content in placeholders.items():
            path = player_dir / filename
            if not path.exists():
                path.write_text(content, encoding="utf-8")


def _reset_dialogue_history_files() -> None:
    _ensure_dirs()
    SHARED_HISTORY_PATH.write_text("# Shared Dialogue History\n", encoding="utf-8")
    SHARED_SUMMARY_PATH.write_text("# Shared Dialogue Summary\n", encoding="utf-8")


def _default_dialogue_state() -> dict[str, Any]:
    return {
        "default_order": DEFAULT_DIALOGUE_ORDER,
        "current_order": DEFAULT_DIALOGUE_ORDER,
        "active_speaker": DEFAULT_DIALOGUE_ORDER[0],
        "round": 1,
        "turn_index": 0,
        "temporary_order": [],
        "temporary_reason": "",
        "pending_interrupts": [],
        "pending_next_speaker": None,
        "last_completed_speaker": None,
    }


def _ensure_dialogue_state_file() -> dict[str, Any]:
    _ensure_dialogue_placeholders()
    if DIALOGUE_STATE_PATH.exists():
        try:
            state = json.loads(DIALOGUE_STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = _default_dialogue_state()
    else:
        state = _default_dialogue_state()
        DIALOGUE_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def _write_dialogue_state(state: dict[str, Any]) -> None:
    DIALOGUE_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_actor_id(actor_id: str) -> None:
    if actor_id not in ALL_ACTOR_IDS:
        raise ValueError(f"Unknown actor_id {actor_id!r}. Allowed actors: {ALL_ACTOR_IDS}")


def _player_notebook_path(owner_id: str, notebook_name: str) -> Path:
    if owner_id not in PLAYER_IDS:
        raise ValueError(f"Unknown player notebook owner {owner_id!r}. Allowed owners: {PLAYER_IDS}")
    if notebook_name not in PLAYER_NOTEBOOK_FILES:
        raise ValueError(
            f"Unknown notebook_name {notebook_name!r}. Allowed notebooks: {sorted(PLAYER_NOTEBOOK_FILES)}"
        )
    return PLAYERS_DIR / owner_id / PLAYER_NOTEBOOK_FILES[notebook_name]


def _enforce_notebook_access(actor_id: str, owner_id: str) -> None:
    _validate_actor_id(actor_id)
    if actor_id != "gm" and actor_id != owner_id:
        raise PermissionError(f"Actor '{actor_id}' cannot access notebook owned by '{owner_id}'.")


def _read_markdown_heading_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    needle = heading.strip().lstrip("# ").lower()
    start = None
    level = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("# ").strip().lower()
        if title == needle:
            start = index
            level = len(stripped) - len(stripped.lstrip("#"))
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            next_level = len(stripped) - len(stripped.lstrip("#"))
            if next_level <= level:
                end = index
                break
    return "\n".join(lines[start:end]).strip()


def _section_path(section: str) -> tuple[Path, str]:
    """Return (absolute path, format) for a notebook section name."""
    if section not in _SECTIONS:
        raise KeyError(
            f"Unknown section {section!r}. Valid sections: {sorted(_SECTIONS)}"
        )
    fname, fmt = _SECTIONS[section]
    path = NOTEBOOKS_DIR / fname
    if path.exists() or fmt != "md" or section != "rules_summary":
        return path, fmt

    candidates = sorted(
        NOTEBOOKS_DIR.glob("rules_summary*.md"),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0], fmt
    return path, fmt


def _upcoming_speakers(state: dict[str, Any], lookahead: int = 5) -> list[str]:
    order = state.get("current_order") or state.get("default_order") or DEFAULT_DIALOGUE_ORDER
    if not order:
        return []
    start = int(state.get("turn_index", 0)) % len(order)
    return [order[(start + offset) % len(order)] for offset in range(min(lookahead, len(order)))]


def _rotate_to_speaker(state: dict[str, Any], speaker_id: str) -> None:
    order = state.get("current_order") or []
    if speaker_id not in order:
        raise ValueError(f"Speaker '{speaker_id}' is not in current_order: {order}")
    state["turn_index"] = order.index(speaker_id)
    state["active_speaker"] = speaker_id


def _restore_default_order(state: dict[str, Any]) -> None:
    state["current_order"] = list(state.get("default_order") or DEFAULT_DIALOGUE_ORDER)
    state["temporary_order"] = []
    state["temporary_reason"] = ""
    _rotate_to_speaker(state, "gm")


# ---------------------------------------------------------------------------
# 1. Dice
# ---------------------------------------------------------------------------

def _parse_and_roll(expr: str) -> tuple[int, list[str]]:
    """Parse a dice expression and return (total, human-readable detail parts).

    Supported notation::
        1d20          – roll one 20-sided die
        2d6+3         – roll two d6, add flat modifier
        1d20-2        – roll one d20, subtract modifier
        4d6kh3        – roll four d6, keep highest three (e.g. character creation)
        1d20+1d4-2    – combine multiple dice groups
    """
    expr = expr.strip().lower().replace(" ", "")
    # Each token: optional leading sign, then XdY[khN] or plain integer
    tokens = re.findall(r"[+-]?(?:\d+d\d+(?:kh\d+)?|\d+)", expr)
    if not tokens:
        raise ValueError(f"Cannot parse dice expression: {expr!r}")

    total = 0
    parts: list[str] = []

    for token in tokens:
        negative = token.startswith("-")
        if token[0] in "+-":
            token = token[1:]
        sign = -1 if negative else 1
        sign_chr = "−" if negative else "+"

        m = re.fullmatch(r"(\d+)d(\d+)(?:kh(\d+))?", token)
        if m:
            n, sides = int(m.group(1)), int(m.group(2))
            keep = int(m.group(3)) if m.group(3) else n
            if n < 1 or sides < 1 or keep < 1:
                raise ValueError(f"Invalid dice parameters in token {token!r}")
            rolls = [random.randint(1, sides) for _ in range(n)]
            kept = sorted(rolls, reverse=True)[:keep]
            sub = sum(kept)
            label = f"{sign_chr}[{n}d{sides}"
            if keep < n:
                label += f"kh{keep}: rolled{rolls} kept{kept}"
            else:
                label += f": {rolls}"
            label += f" = {sub}]"
            total += sign * sub
            parts.append(label)
        elif re.fullmatch(r"\d+", token):
            mod = int(token)
            total += sign * mod
            parts.append(f"{sign_chr}{mod}")
        else:
            raise ValueError(f"Unrecognised token {token!r} in {expr!r}")

    return total, parts


@tool
def roll_dice(expression: str) -> str:
    """Roll dice using standard TRPG dice notation and return the result.

    Supports ``1d20``, ``2d6+3``, ``4d6kh3`` (keep highest 3),
    ``1d20+1d4-2``, and other combinations of multiple dice groups.

    Args:
        expression: Dice expression such as ``"1d20+5"``, ``"8d6"``,
                    ``"4d6kh3"``, or ``"2d6+1d4-1"``.

    Returns:
        A string showing each roll and the final total.
    """
    try:
        total, parts = _parse_and_roll(expression)
        detail = "  ".join(parts)
        return f"🎲 {expression}  →  {detail}  =  **{total}**"
    except ValueError as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# 2. Document reading tools
#    (operate on markdown documents resolved by src/rag/rag.py)
# ---------------------------------------------------------------------------

def _load_document_blocks(doc_id: str) -> tuple[Path | None, list[dict[str, Any]]]:
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.rag.rag import _iter_markdown_blocks, _resolve_markdown_path

    markdown_path = _resolve_markdown_path(doc_id)
    if markdown_path is None:
        return None, []
    return markdown_path, _iter_markdown_blocks(doc_id, markdown_path)


def _format_block_header(doc_id: str, page_num: int, sections: list[str]) -> str:
    header = f"[{doc_id}  ·  page {page_num}]"
    if sections:
        header += f"  §  {' > '.join(sections[:4])}"
    return header


def _format_page_blocks(doc_id: str, page_num: int, blocks: list[dict[str, Any]]) -> str:
    page_header = f"[{doc_id}  ·  page {page_num}]"
    rendered: list[str] = []
    for block in blocks:
        sections = block.get("sections", [])
        body = block.get("markdown", "").strip()
        if not body:
            continue
        if sections:
            rendered.append(f"§ {' > '.join(sections[:4])}\n\n{body}")
        else:
            rendered.append(body)
    if not rendered:
        return f"Page {page_num} in document '{doc_id}' is empty."
    return f"{page_header}\n\n" + "\n\n---\n\n".join(rendered)


def _build_toc_entries(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for block in blocks:
        page_num = block.get("page_num", -1)
        for level, title in enumerate(block.get("sections", []), start=1):
            key = (page_num, title)
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "heading_level": level,
                "title": title,
                "page_num": page_num,
            })
    return entries

@tool
def read_document_page(doc_id: str, page: int) -> str:
    """Read all markdown blocks that belong to one page number.

    Use this when you already know the page number, e.g. after a
    ``lookup_index`` call or because the GM is following along page by page.

    Args:
        doc_id: Document identifier – the markdown filename stem or a stem that
                resolves through ``src.rag.rag._resolve_markdown_path``.
        page:   Page number recorded in the markdown page marker, e.g. the
                value from ``{63}------------------------------------------------``.

    Returns:
        The markdown text for that page, or an error message if not found.
    """
    _, blocks = _load_document_blocks(doc_id)
    if not blocks:
        return (
            f"Document '{doc_id}' not found under documents/ or data/clean_markdown/. "
            "Build or convert the markdown source first."
        )
    page_blocks = [block for block in blocks if block.get("page_num") == page]
    if page_blocks:
        return _format_page_blocks(doc_id, page, page_blocks)
    return f"Page {page} not found in document '{doc_id}'."


@tool
def read_document_section(doc_id: str, section_title: str) -> str:
    """Read markdown blocks whose heading hierarchy matches a section title.

    Useful for jumping directly to a named chapter, spell entry, monster
    stat-block, or rule section without knowing the exact page number.

    Args:
        doc_id:        Document identifier (e.g. ``"城主指南2024"``).
        section_title: Heading text to find; substring match,
                       e.g. ``"Fireball"``, ``"Chapter 3"``, ``"Goblins"``.

    Returns:
        Concatenated markdown text of all matching pages (separated by
        horizontal rules), or a not-found message.
    """
    _, blocks = _load_document_blocks(doc_id)
    if not blocks:
        return f"Document '{doc_id}' not found under documents/ or data/clean_markdown/."

    needle = section_title.lower()
    hits: list[str] = []
    for block in blocks:
        if any(needle in heading.lower() for heading in block.get("sections", [])):
            hits.append(
                f"{_format_block_header(doc_id, block.get('page_num', -1), block.get('sections', []))}\n\n"
                f"{block.get('markdown', '')}"
            )

    if not hits:
        return f"No section matching '{section_title}' found in '{doc_id}'."
    return "\n\n---\n\n".join(hits)


@tool
def search_document(doc_id: str, query: str, top_k: int = 5) -> str:
    """Search for a keyword or phrase within a document using exact text matching.

    Unlike the semantic RAG tools, this performs a precise string search.
    Use it for known names (spell names, NPC names, place names, rule terms)
    when you need guaranteed exact matches rather than fuzzy relevance.

    Args:
        doc_id: Document identifier (e.g. ``"城主指南2024"``).
        query:  Search string; case-insensitive.
        top_k:  Maximum number of result pages to return (default 5).

    Returns:
        Formatted text showing matching pages (ranked by hit count) with a
        short context snippet around the first match on each page.
    """
    _, blocks = _load_document_blocks(doc_id)
    if not blocks:
        return f"Document '{doc_id}' not found under documents/ or data/clean_markdown/."

    needle = query.lower()
    scored: list[tuple[int, int, list[str], str]] = []
    for block in blocks:
        sections = block.get("sections", [])
        markdown = block.get("markdown", "")
        haystack = "\n".join([*sections, markdown]).lower()
        count = haystack.count(needle)
        if count > 0:
            scored.append((count, block.get("page_num", -1), sections, markdown))

    if not scored:
        return f"No matches for '{query}' in '{doc_id}'."

    scored.sort(key=lambda x: -x[0])
    lines: list[str] = [
        f"Found '{query}' on {len(scored)} page(s) of '{doc_id}'. "
        f"Showing top {min(top_k, len(scored))}:\n"
    ]
    for hit_count, page_num, sections, text in scored[:top_k]:
        idx = text.lower().find(needle)
        if idx < 0:
            idx = 0
        start, end = max(0, idx - 120), min(len(text), idx + 320)
        snippet = ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")
        header = f"Page {page_num}  ({hit_count} hit(s))"
        if sections:
            header += f"  § {' > '.join(sections[:4])}"
        lines.append(f"{header}:\n{snippet}")
    return "\n\n---\n\n".join(lines)


@tool
def lookup_index(doc_id: str, keyword: str) -> str:
    """Look up a keyword in the document's derived table of contents.

    Use this as the first step when you want to find a named chapter, rule,
    creature, or NPC – it returns page numbers without loading page text.

    Args:
        doc_id:  Document identifier (e.g. ``"城主指南2024"``).
        keyword: Name or title to search for; case-insensitive substring.

    Returns:
        Matching TOC entries with heading level and page numbers, or a
        not-found message.
    """
    _, blocks = _load_document_blocks(doc_id)
    if not blocks:
        return f"Document '{doc_id}' not found under documents/ or data/clean_markdown/."

    toc = _build_toc_entries(blocks)
    needle = keyword.lower()
    matches = [e for e in toc if needle in e.get("title", "").lower()]

    if not matches:
        return f"No TOC entries matching '{keyword}' in '{doc_id}'."

    header = f"TOC matches for '{keyword}' in '{doc_id}'  ({len(matches)} found):"
    entries = [
        f"  {'#' * e.get('heading_level', 1)} {e['title']}  → page {e.get('page_num', '?')}"
        for e in matches
    ]
    return "\n".join([header] + entries)


@tool
def read_player_reference_page(doc_id: str, page: int) -> str:
    """Read one page from the allowed player-facing handbooks only."""
    try:
        canonical_doc_id = _normalize_player_reference_doc_id(doc_id)
    except ValueError as exc:
        return str(exc)
    return _invoke_local_tool(read_document_page, doc_id=canonical_doc_id, page=page)


@tool
def read_player_reference_section(doc_id: str, section_title: str) -> str:
    """Read one section from the allowed player-facing handbooks only."""
    try:
        canonical_doc_id = _normalize_player_reference_doc_id(doc_id)
    except ValueError as exc:
        return str(exc)
    return _invoke_local_tool(read_document_section, doc_id=canonical_doc_id, section_title=section_title)


@tool
def search_player_reference(doc_id: str, query: str, top_k: int = 5) -> str:
    """Search within the allowed player-facing handbooks only."""
    try:
        canonical_doc_id = _normalize_player_reference_doc_id(doc_id)
    except ValueError as exc:
        return str(exc)
    return _invoke_local_tool(search_document, doc_id=canonical_doc_id, query=query, top_k=top_k)


@tool
def lookup_player_reference_index(doc_id: str, keyword: str) -> str:
    """Look up headings in the allowed player-facing handbooks only."""
    try:
        canonical_doc_id = _normalize_player_reference_doc_id(doc_id)
    except ValueError as exc:
        return str(exc)
    return _invoke_local_tool(lookup_index, doc_id=canonical_doc_id, keyword=keyword)


# ---------------------------------------------------------------------------
# 3. RAG query tools  (semantic search via LlamaIndex, built in src/rag/rag.py)
# ---------------------------------------------------------------------------

def _format_rag(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        secs = " > ".join(r["sections"][:3]) if r["sections"] else "(no headings)"
        header = (
            f"[{i}] {r['doc_id']}  p{r['page_num']}  "
            f"§{secs}  score={r['score']:.3f}"
        )
        parts.append(f"{header}\n{r['text'][:600]}")
    return "\n\n---\n\n".join(parts)


def _split_csv_values(raw: str) -> list[str]:
    return [value.strip() for value in raw.split(",") if value.strip()]


def _invoke_local_tool(tool_obj: Any, /, **kwargs: Any) -> Any:
    if hasattr(tool_obj, "invoke"):
        return tool_obj.invoke(kwargs)
    return tool_obj(**kwargs)


def _normalize_player_reference_doc_id(doc_id: str) -> str:
    raw = doc_id.strip()
    stem = raw[:-3] if raw.lower().endswith(".md") else raw
    if stem in PLAYER_REFERENCE_DOCUMENTS:
        return PLAYER_REFERENCE_DOCUMENTS[stem]
    allowed = ", ".join(PLAYER_REFERENCE_DOCUMENTS.values())
    raise ValueError(f"Player reference doc_id must be one of: {allowed}")


def _resolve_player_reference_index(index_alias: str) -> str | None:
    for candidate in PLAYER_REFERENCE_INDEX_ALIASES.get(index_alias, []):
        if (DATA_DIR / "indices" / candidate).exists():
            return candidate
    return None


@tool
def query_rules_tool(query: str, top_k: int = 5) -> str:
    """Search the rules index using semantic (vector) search.

    Use for game-mechanics questions: spell effects, attack rules, ability
    checks, conditions, equipment stats, class features.

    Requires the rules index to have been built first::

        python -m src.rag.rag build rules <doc_id> [<doc_id> ...]

    Args:
        query:  Natural-language question or keyword phrase.
        top_k:  Number of passages to retrieve (default 5).

    Returns:
        Formatted passages with source, page, and relevance score.
    """
    # Lazy import so the module works even without llama-index at import time.
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from src.rag.rag import query_rules
        results = query_rules(query, top_k=top_k)
    except FileNotFoundError:
        return (
            "Rules index not built yet.\n"
            "  python -m src.rag.rag build rules <doc_id> ..."
        )
    except (ImportError, Exception) as exc:
        return f"RAG error: {exc}"

    if not results:
        return f"No rule passages found for: {query!r}"
    return _format_rag(results)


@tool
def query_lore_tool(query: str, top_k: int = 5) -> str:
    """Search the lore index using semantic (vector) search.

    Use for world/story questions: NPCs, locations, quest objectives, history,
    campaign events, faction relationships.

    Requires the lore index to have been built first::

        python -m src.rag.rag build lore <doc_id> [<doc_id> ...]

    Args:
        query:  Natural-language question or keyword phrase.
        top_k:  Number of passages to retrieve (default 5).

    Returns:
        Formatted passages with source, page, and relevance score.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from src.rag.rag import query_lore
        results = query_lore(query, top_k=top_k)
    except FileNotFoundError:
        return (
            "Lore index not built yet.\n"
            "  python -m src.rag.rag build lore <doc_id> ..."
        )
    except (ImportError, Exception) as exc:
        return f"RAG error: {exc}"

    if not results:
        return f"No lore passages found for: {query!r}"
    return _format_rag(results)


def _query_player_reference_index(index_alias: str, query_text: str, top_k: int = 5) -> str:
    index_name = _resolve_player_reference_index(index_alias)
    if not index_name:
        expected = ", ".join(PLAYER_REFERENCE_INDEX_ALIASES.get(index_alias, []))
        return f"Player reference index not built yet. Expected one of: {expected}"

    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from src.rag.rag import query

        results = query(index_name, query_text, top_k=top_k)
    except FileNotFoundError:
        return f"Index '{index_name}' not found under data/indices/."
    except Exception as exc:
        return f"RAG error: {exc}"

    if not results:
        return f"No passages found for: {query_text!r}"
    return _format_rag(results)


@tool
def query_phb_documents(query: str, top_k: int = 5) -> str:
    """Query the player-facing PHB index (`phb_documents` / `phb_documents_qwen`)."""
    return _query_player_reference_index("phb_documents", query, top_k=top_k)


@tool
def query_odyssey_player_handbook(query: str, top_k: int = 5) -> str:
    """Query the player-facing Odyssey handbook index (`odyssey_player_handbook`)."""
    return _query_player_reference_index("odyssey_player_handbook", query, top_k=top_k)


@tool
def compile_rules_summary(doc_ids: str = "", output_path: str = "") -> str:
    """Run the LangGraph/React Rule Retreival Agent in bootstrap mode.

    This entrypoint constructs the Rule Retreival Agent with its default chat
    model, lets the agent plan its own document-reading sequence, and requires
    it to write a GM-facing rules summary markdown file.

    Args:
        doc_ids:     Optional comma-separated document ids. When empty, all
                     markdown files under ``documents/`` are considered.
        output_path: Optional custom output path. When empty, writes to
                     ``notebooks/rules_summary.md``.

    Returns:
        A confirmation message describing where the summary was written and
        where the execution log was recorded.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from src.agents.rule_retrieval import compile_rules_summary as _compile_rules_summary

        result = _compile_rules_summary(
            doc_ids=_split_csv_values(doc_ids) or None,
            output_path=output_path.strip() or None,
        )
    except Exception as exc:
        return f"Rule summary compilation error: {exc}"

    return (
        f"Rules summary written to {result['output_path']}\n"
        f"Documents: {', '.join(result['doc_ids'])}\n"
        f"Compressed notes: {result['compressed_note_count']}\n"
        f"Log: {result['log_path']}"
    )


@tool
def answer_rule_query(query: str, doc_ids: str = "", top_k: int = 5) -> str:
    """Run the LangGraph/React Rule Retreival Agent in search mode.

    The agent plans its own retrieval steps using the markdown reading and
    search tools, then returns a cited answer for the requested rule question.

    Args:
        query:   Natural-language rules question.
        doc_ids: Optional comma-separated document ids. When empty, searches
                 all available markdown rulebooks.
        top_k:   Maximum number of cited passages to return.

    Returns:
        A markdown answer with the top cited rule passages.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from src.agents.rule_retrieval import answer_rule_query as _answer_rule_query

        return _answer_rule_query(
            query,
            doc_ids=_split_csv_values(doc_ids) or None,
            top_k=top_k,
        )
    except Exception as exc:
        return f"Rule query error: {exc}"


# ---------------------------------------------------------------------------
# 4. Notebook tools
# ---------------------------------------------------------------------------

@tool
def read_notebook(section: str, keys: str = "") -> str:
    """Read the current state from a notebook section.

    Available sections: ``scene_state``, ``party_state``, ``npc_registry``,
    ``combat_state``, ``memory_index``, ``campaign_summary``,
    ``rules_summary``.

    Args:
        section: Notebook section name.
        keys:    Comma-separated list of JSON keys to include. If empty,
                 the entire section is returned.

    Returns:
        Section content as JSON (for state sections) or plain text
        (for ``campaign_summary``), or an error message.
    """
    _ensure_dirs()
    try:
        path, fmt = _section_path(section)
    except KeyError as exc:
        return str(exc)

    if not path.exists():
        return f"Notebook section '{section}' has not been initialised yet."

    if fmt == "md":
        return path.read_text(encoding="utf-8")

    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"Error reading '{section}': {exc}"

    if keys.strip():
        key_list = [k.strip() for k in keys.split(",") if k.strip()]
        data = {k: data[k] for k in key_list if k in data}

    return json.dumps(data, ensure_ascii=False, indent=2)


@tool
def update_notebook(section: str, patch_json: str) -> str:
    """Update a notebook section by merging a JSON patch into the current state.

    For JSON sections (all except ``campaign_summary``), performs a shallow
    merge: existing keys are preserved, and keys in *patch_json* are added or
    overwritten.  For ``campaign_summary`` and ``rules_summary``, the value is
    appended as a new paragraph.

    Creates the section file if it does not exist yet.

    Args:
        section:    Notebook section name.
        patch_json: For JSON sections – a JSON object string, e.g.
                    ``'{"hp": 18, "status": "poisoned"}'``.
                    For ``campaign_summary`` – plain Markdown text to append.

    Returns:
        Confirmation or error message.
    """
    _ensure_dirs()
    try:
        path, fmt = _section_path(section)
    except KeyError as exc:
        return str(exc)

    if fmt == "md":
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(existing + "\n\n" + patch_json.strip(), encoding="utf-8")
        return "campaign_summary updated."

    # JSON section – shallow merge
    existing_data: dict[str, Any] = {}
    if path.exists():
        try:
            existing_data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_data = {}

    try:
        patch: dict[str, Any] = json.loads(patch_json)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON patch: {exc}"

    existing_data.update(patch)
    path.write_text(json.dumps(existing_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Notebook section '{section}' updated."


@tool
def append_log(event: str) -> str:
    """Append a timestamped event to the game session log.

    Call this after every significant event: combat actions, skill checks,
    NPC interactions, discovery of clues, story decisions, and chapter
    transitions.  The log is consumed by ``summarize_log`` and used for
    post-session review.

    Args:
        event: Plain-text description of the event.

    Returns:
        Confirmation with the UTC timestamp.
    """
    _ensure_dirs()
    log_path = LOG_DIR / "game.log"
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"[{ts}] {event}\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    return f"Logged at {ts}."


@tool
def summarize_log(window: int = 20) -> str:
    """Return the last *window* entries from the session log.

    Use this to recall recent events when the context window is limited, or
    as input to a summarization prompt to generate a narrative recap.

    Args:
        window: Number of most-recent log entries to return (default 20).

    Returns:
        The last *window* log lines as a single newline-separated string,
        or a message if the log is empty.
    """
    _ensure_dirs()
    log_path = LOG_DIR / "game.log"
    if not log_path.exists():
        return "No log entries yet."
    lines = log_path.read_text(encoding="utf-8").splitlines()
    recent = lines[-window:]
    return "\n".join(recent) if recent else "Log is empty."


# ---------------------------------------------------------------------------
# 5. Dialogue tools
# ---------------------------------------------------------------------------

@tool
def initialize_dialogue_state(default_order_csv: str = "", reset_history: bool = False) -> str:
    """Initialize dialogue state and create notebook placeholders.

    Args:
        default_order_csv: Optional comma-separated custom order. When empty,
            defaults to ``gm,human_player,llm_player_1,llm_player_2,llm_player_3``.
        reset_history: When true, also clear shared dialogue history and summary.

    Returns:
        A confirmation with the active speaker and created paths.
    """
    _ensure_dialogue_placeholders(reset_player_character_sheets=reset_history)
    if reset_history:
        _reset_dialogue_history_files()
    order = _split_csv_values(default_order_csv) or list(DEFAULT_DIALOGUE_ORDER)
    invalid = [actor_id for actor_id in order if actor_id not in ALL_ACTOR_IDS]
    if invalid:
        return f"Invalid actor ids in order: {invalid}. Allowed actors: {ALL_ACTOR_IDS}"
    if "gm" not in order:
        order.append("gm")

    state = _default_dialogue_state()
    state["default_order"] = order
    state["current_order"] = order
    state["active_speaker"] = order[0]
    _write_dialogue_state(state)
    history_message = " Shared dialogue history cleared." if reset_history else ""
    return (
        f"Dialogue state initialized. Active speaker: {state['active_speaker']}.\n"
        f"Order: {', '.join(state['current_order'])}.\n"
        f"Dialogue state path: {DIALOGUE_STATE_PATH}"
        f"{history_message}"
    )


@tool
def read_dialogue_state() -> str:
    """Read the current dialogue state with a computed speaker preview."""
    state = _ensure_dialogue_state_file()
    preview = _upcoming_speakers(state, lookahead=5)
    view = dict(state)
    view["upcoming_speakers"] = preview
    return json.dumps(view, ensure_ascii=False, indent=2)


@tool
def get_upcoming_speakers(lookahead: int = 5) -> str:
    """Return the upcoming dialogue order preview for the next turns."""
    state = _ensure_dialogue_state_file()
    preview = _upcoming_speakers(state, lookahead=max(1, lookahead))
    return " -> ".join(preview)


@tool
def set_temporary_speaking_order(actor_id: str, order_csv: str, reason: str = "") -> str:
    """Let the GM temporarily override speaking order.

    The temporary order is executed as-is. After the sequence finishes,
    control automatically returns to the GM.
    """
    if actor_id != "gm":
        return "Only the GM can set a temporary speaking order."

    state = _ensure_dialogue_state_file()
    order = _split_csv_values(order_csv)
    if not order:
        return "Temporary order must include at least one actor."

    invalid = [speaker_id for speaker_id in order if speaker_id not in ALL_ACTOR_IDS or speaker_id == "gm"]
    if invalid:
        return f"Temporary order can only contain players. Invalid entries: {invalid}"

    state["current_order"] = order
    state["temporary_order"] = order
    state["temporary_reason"] = reason.strip()
    state["turn_index"] = 0
    state["active_speaker"] = order[0]
    _write_dialogue_state(state)
    return (
        f"Temporary speaking order set: {', '.join(order)}. "
        "After this order finishes, control will return to gm."
    )


@tool
def request_interrupt(actor_id: str, reason: str = "") -> str:
    """Request an interruption for the requesting player."""
    if actor_id not in PLAYER_IDS:
        return f"Only players can request interruptions. Allowed players: {PLAYER_IDS}"
    state = _ensure_dialogue_state_file()
    queue = [item for item in state.get("pending_interrupts", []) if item.get("actor_id") != actor_id]
    queue.append({"actor_id": actor_id, "reason": reason.strip()})
    state["pending_interrupts"] = queue
    _write_dialogue_state(state)
    return f"Interrupt requested by {actor_id}. Pending interrupts: {len(queue)}"


@tool
def approve_interrupt(actor_id: str, speaker_id: str) -> str:
    """Approve one pending interrupt and make that player the next speaker."""
    if actor_id != "gm":
        return "Only the GM can approve interruptions."
    if speaker_id not in PLAYER_IDS:
        return f"Only players can be approved as interrupters. Allowed players: {PLAYER_IDS}"

    state = _ensure_dialogue_state_file()
    queue = state.get("pending_interrupts", [])
    if not any(item.get("actor_id") == speaker_id for item in queue):
        return f"No pending interrupt request found for {speaker_id}."

    state["pending_interrupts"] = [item for item in queue if item.get("actor_id") != speaker_id]
    state["pending_next_speaker"] = speaker_id
    _write_dialogue_state(state)
    return f"Interrupt approved. {speaker_id} will speak next."


@tool
def nominate_next_speaker(actor_id: str, next_speaker: str, reason: str = "") -> str:
    """Nominate the next speaker, typically when asking another player directly."""
    _validate_actor_id(actor_id)
    if next_speaker not in ALL_ACTOR_IDS:
        return f"Unknown next speaker {next_speaker!r}. Allowed actors: {ALL_ACTOR_IDS}"

    state = _ensure_dialogue_state_file()
    if state.get("active_speaker") != actor_id:
        return f"{actor_id} cannot nominate the next speaker because it is not their turn."

    state["pending_next_speaker"] = next_speaker
    if reason.strip():
        state["pending_next_speaker_reason"] = reason.strip()
    _write_dialogue_state(state)
    return f"Next speaker nominated: {next_speaker}."


@tool
def append_dialogue_history(speaker_id: str, message: str) -> str:
    """Append one shared dialogue turn to the shared history log."""
    _validate_actor_id(speaker_id)
    _ensure_dialogue_placeholders()
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"- [{timestamp}] **{speaker_id}**: {message.strip()}\n"
    with SHARED_HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    return f"Dialogue entry recorded for {speaker_id}."


@tool
def summarize_dialogue_history(window: int = 20) -> str:
    """Create a lightweight rolling summary from the last dialogue turns."""
    _ensure_dialogue_placeholders()
    if not SHARED_HISTORY_PATH.exists():
        return "No dialogue history yet."
    lines = [line for line in SHARED_HISTORY_PATH.read_text(encoding="utf-8").splitlines() if line.startswith("-")]
    recent = lines[-max(1, window):]
    if not recent:
        return "No dialogue history yet."
    summary = "# Shared Dialogue Summary\n\n" + "\n".join(recent) + "\n"
    SHARED_SUMMARY_PATH.write_text(summary, encoding="utf-8")
    return summary


@tool
def read_player_notebook(actor_id: str, owner_id: str, notebook_name: str) -> str:
    """Read one player's notebook with GM-or-owner access control."""
    try:
        _enforce_notebook_access(actor_id, owner_id)
        path = _player_notebook_path(owner_id, notebook_name)
    except (ValueError, PermissionError) as exc:
        return str(exc)
    _ensure_dialogue_placeholders()
    return path.read_text(encoding="utf-8")


@tool
def search_player_notebook(actor_id: str, owner_id: str, notebook_name: str, query: str) -> str:
    """Search a player's notebook using case-insensitive exact matching."""
    try:
        _enforce_notebook_access(actor_id, owner_id)
        path = _player_notebook_path(owner_id, notebook_name)
    except (ValueError, PermissionError) as exc:
        return str(exc)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text:
        return f"Notebook '{notebook_name}' for '{owner_id}' is empty."
    needle = query.lower().strip()
    matches = []
    for line in text.splitlines():
        if needle and needle in line.lower():
            matches.append(line)
    if not matches:
        return f"No matches for '{query}' in {owner_id}/{notebook_name}."
    return "\n".join(matches[:20])


@tool
def jump_player_notebook(actor_id: str, owner_id: str, notebook_name: str, heading: str) -> str:
    """Read one heading section from a player's notebook."""
    try:
        _enforce_notebook_access(actor_id, owner_id)
        path = _player_notebook_path(owner_id, notebook_name)
    except (ValueError, PermissionError) as exc:
        return str(exc)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    section = _read_markdown_heading_section(text, heading)
    if not section:
        return f"Heading '{heading}' not found in {owner_id}/{notebook_name}."
    return section


@tool
def update_player_notebook(
    actor_id: str,
    owner_id: str,
    notebook_name: str,
    content: str,
    mode: str = "append",
    heading: str = "",
) -> str:
    """Update a player's notebook with owner-or-GM permissions.

    Modes:
    - append: append content to the end of the notebook
    - replace: replace the entire notebook
    - replace_heading: replace one heading section body
    """
    try:
        _enforce_notebook_access(actor_id, owner_id)
        path = _player_notebook_path(owner_id, notebook_name)
    except (ValueError, PermissionError) as exc:
        return str(exc)

    _ensure_dialogue_placeholders()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    normalized_mode = mode.strip().lower() or "append"

    if normalized_mode == "replace":
        path.write_text(content.strip() + "\n", encoding="utf-8")
        return f"Notebook {owner_id}/{notebook_name} replaced."

    if normalized_mode == "replace_heading":
        if not heading.strip():
            return "heading is required when mode='replace_heading'."
        section = _read_markdown_heading_section(existing, heading)
        if not section:
            return f"Heading '{heading}' not found in {owner_id}/{notebook_name}."
        lines = existing.splitlines()
        old_lines = section.splitlines()
        start = next((i for i in range(len(lines)) if lines[i : i + len(old_lines)] == old_lines), None)
        if start is None:
            return f"Could not locate heading '{heading}' for replacement."
        end = start + len(old_lines)
        first_line = old_lines[0]
        replacement = [first_line, "", *content.strip().splitlines()]
        new_text = "\n".join(lines[:start] + replacement + lines[end:]).strip() + "\n"
        path.write_text(new_text, encoding="utf-8")
        return f"Heading '{heading}' updated in {owner_id}/{notebook_name}."

    path.write_text((existing.rstrip() + "\n\n" + content.strip()).strip() + "\n", encoding="utf-8")
    return f"Content appended to {owner_id}/{notebook_name}."


# ---------------------------------------------------------------------------
# 6. Turn management
# ---------------------------------------------------------------------------

@tool
def advance_turn() -> str:
    """Advance the dialogue turn to the next speaker.

    Priority:
    1. pending_next_speaker override
    2. current order progression
    3. when a temporary order ends, control returns to GM
    4. when default order wraps, the dialogue round increments
    """
    state = _ensure_dialogue_state_file()
    order = state.get("current_order") or state.get("default_order") or list(DEFAULT_DIALOGUE_ORDER)
    if not order:
        return "Dialogue order is empty. Initialize dialogue state first."

    current = state.get("active_speaker")
    state["last_completed_speaker"] = current
    pending_next = state.pop("pending_next_speaker", None)
    state.pop("pending_next_speaker_reason", None)

    if pending_next:
        try:
            _rotate_to_speaker(state, pending_next)
        except ValueError as exc:
            return str(exc)
    else:
        current_index = int(state.get("turn_index", 0))
        next_index = (current_index + 1) % len(order)
        if state.get("temporary_order"):
            if next_index == 0:
                _restore_default_order(state)
            else:
                state["turn_index"] = next_index
                state["active_speaker"] = order[next_index]
        else:
            if next_index == 0:
                state["round"] = int(state.get("round", 1)) + 1
            state["turn_index"] = next_index
            state["active_speaker"] = order[next_index]

    _write_dialogue_state(state)
    preview = _upcoming_speakers(state, lookahead=5)
    return (
        f"Turn advanced -> {state['active_speaker']} "
        f"(dialogue round {state.get('round', 1)}).\n"
        f"Upcoming: {' -> '.join(preview)}"
    )


# ---------------------------------------------------------------------------
# Exported list for easy agent wiring
# ---------------------------------------------------------------------------
ALL_TOOLS = [
    roll_dice,
    read_document_page,
    read_document_section,
    search_document,
    lookup_index,
    query_rules_tool,
    query_lore_tool,
    compile_rules_summary,
    answer_rule_query,
    read_notebook,
    update_notebook,
    append_log,
    summarize_log,
    initialize_dialogue_state,
    read_dialogue_state,
    get_upcoming_speakers,
    set_temporary_speaking_order,
    request_interrupt,
    approve_interrupt,
    nominate_next_speaker,
    append_dialogue_history,
    summarize_dialogue_history,
    read_player_notebook,
    search_player_notebook,
    jump_player_notebook,
    update_player_notebook,
    advance_turn,
]
