#!/usr/bin/env python3
"""Convert the offline DMG website into markdown, build its RAG index, and query it.

Examples
--------
python -m src.rag.test --skip-build --skip-query
python -m src.rag.test
python -m src.rag.test --skip-convert --skip-build --query "如何制作魔法物品"
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup, NavigableString, Tag

from src.rag.rag import build_index, query


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS_DIR = PROJECT_ROOT / "documents"
WEBSITE_ROOT = DOCUMENTS_DIR / "城主指南2024"
OUTPUT_MARKDOWN = DOCUMENTS_DIR / "城主指南2024.md"

DEFAULT_INDEX_NAME = "dmg_2024"
DEFAULT_QUERY = "如何制作魔法物品"
DEFAULT_TOP_K = 5
PAGE_MARKER_BAR = "-" * 48
BR_TOKEN = "__TRPG_BR__"

BLOCK_TAGS = {
	"article",
	"blockquote",
	"center",
	"div",
	"h1",
	"h2",
	"h3",
	"h4",
	"h5",
	"h6",
	"hr",
	"li",
	"ol",
	"p",
	"section",
	"table",
	"td",
	"th",
	"tr",
	"ul",
}
SKIP_TAGS = {"head", "meta", "link", "script", "style"}


def _natural_key(text: str) -> tuple[Any, ...]:
	parts = re.split(r"(\d+)", text.casefold())
	key: list[Any] = []
	for part in parts:
		if not part:
			continue
		if part.isdigit():
			key.append((0, int(part)))
		else:
			key.append((1, part))
	return tuple(key)


def _html_sort_key(path: Path) -> tuple[Any, ...]:
	rel_path = path.relative_to(WEBSITE_ROOT)
	if rel_path == Path("城主指南2024.htm"):
		prefix = 0
	elif rel_path == Path("Credits.htm"):
		prefix = 1
	elif rel_path.parts[:1] == ("附录A：设定汇编.htm",):
		prefix = 99
	else:
		prefix = 10
	return (prefix,) + tuple(_natural_key(part) for part in rel_path.parts)


def _normalize_text(text: str) -> str:
	text = text.replace("\xa0", " ")
	text = re.sub(r"[ \t\r\f\v]+", " ", text)
	text = re.sub(r" *\n *", "\n", text)
	text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
	text = text.replace(BR_TOKEN, "\n")
	text = re.sub(r" *\n *", "\n", text)
	text = re.sub(r"\n{3,}", "\n\n", text)
	return text.strip()


def _collapse_blank_lines(lines: Iterable[str]) -> list[str]:
	cleaned: list[str] = []
	blank_pending = False
	for line in lines:
		stripped = line.rstrip()
		if not stripped:
			blank_pending = True
			continue
		if blank_pending and cleaned:
			cleaned.append("")
		blank_pending = False
		cleaned.append(stripped)
	return cleaned


def _escape_md_cell(text: str) -> str:
	return text.replace("|", "\\|")


def _extract_inline(node: Any) -> str:
	if isinstance(node, NavigableString):
		return str(node)
	if not isinstance(node, Tag):
		return ""

	name = node.name.lower()
	if name in SKIP_TAGS:
		return ""
	if name == "br":
		return BR_TOKEN
	if name == "img":
		alt = _normalize_text(node.get("alt", ""))
		return alt

	text = "".join(_extract_inline(child) for child in node.children)
	text = _normalize_text(text)
	if not text:
		return ""

	if name in {"strong", "b"}:
		return f"**{text}**"
	if name in {"em", "i"}:
		return f"*{text}*"
	if name == "a":
		href = node.get("href", "").strip()
		if href and not href.startswith("#"):
			return f"{text} ({href})"
		return text
	return text


def _has_block_children(tag: Tag) -> bool:
	for child in tag.children:
		if isinstance(child, Tag) and child.name.lower() in BLOCK_TAGS:
			return True
	return False


def _render_list_item(tag: Tag, *, depth: int) -> list[str]:
	inline_parts: list[str] = []
	nested_lines: list[str] = []
	for child in tag.children:
		if isinstance(child, Tag) and child.name.lower() in {"ul", "ol"}:
			nested_lines.extend(_render_list(child, depth=depth + 1, ordered=child.name.lower() == "ol"))
			continue
		inline = _extract_inline(child)
		if inline:
			inline_parts.append(inline)

	text = _normalize_text(" ".join(part for part in inline_parts if part.strip()))
	lines: list[str] = [text] if text else []
	if nested_lines:
		if lines and nested_lines[0]:
			lines.append("")
		lines.extend(nested_lines)
	return lines


def _render_list(tag: Tag, *, depth: int, ordered: bool) -> list[str]:
	lines: list[str] = []
	for index, item in enumerate(tag.find_all("li", recursive=False), start=1):
		item_lines = _render_list_item(item, depth=depth)
		if not item_lines:
			continue
		prefix = f"{index}. " if ordered else "- "
		indent = "  " * depth
		first_line = item_lines[0] if item_lines else ""
		if first_line:
			lines.append(f"{indent}{prefix}{first_line}")
		for extra_line in item_lines[1:]:
			if extra_line:
				lines.append(f"{indent}  {extra_line}")
			else:
				lines.append("")
	return _collapse_blank_lines(lines + [""])


def _render_table(tag: Tag) -> list[str]:
	rows: list[list[str]] = []
	for row in tag.find_all("tr"):
		cells = row.find_all(["th", "td"])
		if not cells:
			continue
		rows.append([_escape_md_cell(_normalize_text(_extract_inline(cell))) for cell in cells])

	if not rows:
		return []

	max_columns = max(len(row) for row in rows)
	rows = [row + [""] * (max_columns - len(row)) for row in rows]
	if max_columns == 1:
		return _collapse_blank_lines([row[0] for row in rows if row[0]] + [""])

	header = rows[0]
	separator = ["---"] * max_columns
	lines = [
		"| " + " | ".join(header) + " |",
		"| " + " | ".join(separator) + " |",
	]
	for row in rows[1:]:
		lines.append("| " + " | ".join(row) + " |")
	lines.append("")
	return lines


def _render_children(node: Tag, *, heading_base: int) -> list[str]:
	lines: list[str] = []
	for child in node.children:
		if isinstance(child, NavigableString):
			text = _normalize_text(str(child))
			if text:
				lines.extend([text, ""])
			continue
		if not isinstance(child, Tag):
			continue
		lines.extend(_render_block(child, heading_base=heading_base))
	return _collapse_blank_lines(lines)


def _render_block(tag: Tag, *, heading_base: int) -> list[str]:
	name = tag.name.lower()
	if name in SKIP_TAGS:
		return []
	if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
		text = _normalize_text(_extract_inline(tag))
		if not text:
			return []
		level = min(heading_base + int(name[1]) - 1, 6)
		return [f"{'#' * level} {text}", ""]
	if name in {"ul", "ol"}:
		return _render_list(tag, depth=0, ordered=name == "ol")
	if name == "table":
		return _render_table(tag)
	if name == "blockquote":
		inner_lines = _render_children(tag, heading_base=heading_base)
		quoted = [f"> {line}" if line else ">" for line in inner_lines]
		return _collapse_blank_lines(quoted + [""])
	if name == "hr":
		return ["---", ""]
	if name in {"div", "section", "article", "center"} and _has_block_children(tag):
		return _render_children(tag, heading_base=heading_base)
	if name in {"p", "div", "section", "article", "center", "td", "th"}:
		text = _normalize_text(_extract_inline(tag))
		return [text, ""] if text else []
	return _render_children(tag, heading_base=heading_base)


def _find_first_heading(soup: BeautifulSoup) -> str:
	body = soup.body or soup
	for heading in body.find_all(re.compile(r"^h[1-6]$")):
		text = _normalize_text(_extract_inline(heading))
		if text:
			return text
	return ""


def _clean_heading_piece(text: str) -> str:
	return _normalize_text(Path(text).stem)


def _build_outline(rel_path: Path, *, first_heading: str) -> list[str]:
	parts = [_clean_heading_piece(part) for part in rel_path.with_suffix("").parts]
	outline: list[str] = []
	for part in parts:
		if not part:
			continue
		if outline and outline[-1] == part:
			continue
		outline.append(part)
	if first_heading and (not outline or outline[-1] != first_heading):
		outline.append(first_heading)
	return outline


def _strip_duplicate_leading_heading(lines: list[str], *, last_outline_heading: str) -> list[str]:
	trimmed = list(lines)
	while trimmed and not trimmed[0].strip():
		trimmed.pop(0)
	if not trimmed:
		return trimmed
	match = re.match(r"^#{1,6}\s+(.*)$", trimmed[0])
	if match and _normalize_text(match.group(1)) == _normalize_text(last_outline_heading):
		trimmed.pop(0)
		while trimmed and not trimmed[0].strip():
			trimmed.pop(0)
	return trimmed


def _read_html(path: Path) -> str:
	return path.read_text(encoding="gb18030")


def convert_dmg_website_to_markdown(website_root: Path = WEBSITE_ROOT, output_markdown: Path = OUTPUT_MARKDOWN) -> dict[str, Any]:
	if not website_root.exists():
		raise FileNotFoundError(f"Website root not found: {website_root}")

	html_paths = sorted(website_root.rglob("*.htm"), key=_html_sort_key)
	if not html_paths:
		raise FileNotFoundError(f"No .htm files found under {website_root}")

	sections: list[str] = []
	for page_number, html_path in enumerate(html_paths, start=1):
		rel_path = html_path.relative_to(website_root)
		soup = BeautifulSoup(_read_html(html_path), "html.parser")
		first_heading = _find_first_heading(soup)
		outline = _build_outline(rel_path, first_heading=first_heading)
		body = soup.body or soup
		body_lines = _render_children(body, heading_base=min(len(outline) + 1, 6))
		if outline:
			body_lines = _strip_duplicate_leading_heading(body_lines, last_outline_heading=outline[-1])

		page_lines = [f"{{{page_number}}}{PAGE_MARKER_BAR}", ""]
		for level, heading in enumerate(outline, start=1):
			page_lines.extend([f"{'#' * min(level, 6)} {heading}", ""])
		page_lines.extend(body_lines)
		page_lines = _collapse_blank_lines(page_lines)
		if page_lines:
			sections.append("\n".join(page_lines))
		logger.info("Converted %s", rel_path)

	output_markdown.write_text("\n\n".join(sections).strip() + "\n", encoding="utf-8")
	return {
		"html_count": len(html_paths),
		"markdown_path": output_markdown,
		"doc_id": output_markdown.stem,
	}


def _format_sections(sections: list[str]) -> str:
	return " > ".join(sections[:4]) if sections else "(no headings)"


def _print_results(results: list[dict[str, Any]]) -> None:
	print(f"result_count={len(results)}")
	for index, result in enumerate(results, 1):
		print(
			f"\n[{index}] doc={result['doc_id']} "
			f"page={result['page_num']} "
			f"score={result['score']:.4f} "
			f"section={_format_sections(result.get('sections', []))}"
		)
		print(result["text"])


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Convert the offline DMG website into markdown and build/query a RAG index."
	)
	parser.add_argument("--index-name", default=DEFAULT_INDEX_NAME)
	parser.add_argument("--query", default=DEFAULT_QUERY)
	parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
	parser.add_argument(
		"--skip-convert",
		action="store_true",
		help="Reuse the existing documents/城主指南2024.md instead of regenerating it.",
	)
	parser.add_argument(
		"--skip-build",
		action="store_true",
		help="Reuse an existing index instead of rebuilding it.",
	)
	parser.add_argument(
		"--skip-query",
		action="store_true",
		help="Stop after markdown conversion and optional index build.",
	)
	parser.add_argument(
		"--embed-backend",
		default="qwen",
		choices=["qwen", "openai", "huggingface", "auto"],
		help="Embedding backend passed through to src.rag.rag.",
	)
	parser.add_argument(
		"--embed-model",
		default="text-embedding-v4",
		help="Embedding model name. For qwen this defaults to text-embedding-v4.",
	)
	args = parser.parse_args()

	logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

	os.environ["TRPG_EMBED_BACKEND"] = args.embed_backend
	if args.embed_backend == "qwen":
		os.environ["TRPG_QWEN_EMBED_MODEL"] = args.embed_model
	elif args.embed_backend == "openai":
		os.environ["TRPG_OPENAI_EMBED_MODEL"] = args.embed_model
	elif args.embed_backend == "huggingface":
		os.environ["TRPG_HF_EMBED_MODEL"] = args.embed_model

	doc_id = OUTPUT_MARKDOWN.stem
	if not args.skip_convert:
		stats = convert_dmg_website_to_markdown()
		print(
			f"Converted {stats['html_count']} HTML files into {stats['markdown_path'].name} "
			f"(doc_id={stats['doc_id']})."
		)

	if not args.skip_build:
		print(f"Building index '{args.index_name}' from '{doc_id}'...")
		build_index(args.index_name, [doc_id])

	if args.skip_query:
		return 0

	print(
		f"Querying index '{args.index_name}' with query={args.query!r}, top_k={args.top_k}..."
	)
	results = query(args.index_name, args.query, top_k=args.top_k)
	_print_results(results)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
