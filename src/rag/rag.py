#!/usr/bin/env python3
"""RAG module – LlamaIndex-based vector index for TRPG documents.

Data flow
---------
    PDF → src/documents/extract.py → data/clean_markdown/<doc_id>.md
                                                                 → build_index() → data/indices/<name>/
                                                                 → query()       → list[dict]

Two logical index namespaces are kept separate so retrieval can be scoped:
  rules  – player handbook, monster manual, spells, combat rules
  lore   – campaign modules, world lore, NPC entries, locations

Prerequisites
-------------
  pip install llama-index-core llama-index-embeddings-openai
  # or a local embedding alternative, e.g.:
  #   pip install llama-index-embeddings-huggingface
  #   then set:  Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

Embedding model
---------------
By default LlamaIndex uses OpenAI text-embedding-3-small.
Set the OPENAI_API_KEY environment variable, or override Settings.embed_model
at the top of your entry-point script before calling build_index / query.

CLI usage
---------
  # Build the rules index from two doc_ids produced by extract.py
  python -m src.rag.rag build rules 5ednd__phb 5ednd__mm

  # Query
  python -m src.rag.rag query rules "fireball spell damage and area"
  python -m src.rag.rag query lore  "who is the antagonist in chapter 2"
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths  (anchored to project root = two levels above this file)
# ---------------------------------------------------------------------------
PROJECT_ROOT   = Path(__file__).resolve().parents[2]
CLEAN_MARKDOWN_DIR = PROJECT_ROOT / "data" / "clean_markdown"
DOCUMENTS_DIR = PROJECT_ROOT / "documents"
INDEX_DIR      = PROJECT_ROOT / "data" / "indices"

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
PAGE_MARKER_RE = re.compile(r"^\{(\d+)\}-+$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_llama() -> None:
    """Raise a clear ImportError if llama-index-core is not installed."""
    try:
        import llama_index.core  # noqa: F401
    except ImportError:
        raise ImportError(
            "llama-index-core is not installed.\n"
            "  pip install llama-index-core llama-index-embeddings-openai"
        ) from None


class DashScopeEmbedding:
    """OpenAI-compatible embedding wrapper for DashScope/Qwen models."""

    @classmethod
    def create(
        cls,
        *,
        model_name: str,
        api_key: str,
        api_base: str,
    ):
        from llama_index.core.base.embeddings.base import BaseEmbedding
        from llama_index.core.bridge.pydantic import Field, PrivateAttr
        from openai import AsyncOpenAI, OpenAI

        class _DashScopeEmbedding(BaseEmbedding):
            model_name: str = Field(description="Embedding model name.")
            api_key: str = Field(description="DashScope-compatible API key.")
            api_base: str = Field(description="DashScope-compatible OpenAI base URL.")
            _client: OpenAI = PrivateAttr()
            _aclient: AsyncOpenAI = PrivateAttr()

            def __init__(self, **data: Any) -> None:
                super().__init__(**data)
                self._client = OpenAI(api_key=self.api_key, base_url=self.api_base)
                self._aclient = AsyncOpenAI(api_key=self.api_key, base_url=self.api_base)

            @staticmethod
            def _normalize(text: str) -> str:
                return text.replace("\n", " ")

            def _get_query_embedding(self, query: str) -> list[float]:
                return self._get_text_embedding(query)

            async def _aget_query_embedding(self, query: str) -> list[float]:
                return await self._aget_text_embedding(query)

            def _get_text_embedding(self, text: str) -> list[float]:
                response = self._client.embeddings.create(
                    model=self.model_name,
                    input=self._normalize(text),
                )
                return response.data[0].embedding

            async def _aget_text_embedding(self, text: str) -> list[float]:
                response = await self._aclient.embeddings.create(
                    model=self.model_name,
                    input=self._normalize(text),
                )
                return response.data[0].embedding

            def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
                response = self._client.embeddings.create(
                    model=self.model_name,
                    input=[self._normalize(text) for text in texts],
                )
                return [item.embedding for item in response.data]

            async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
                response = await self._aclient.embeddings.create(
                    model=self.model_name,
                    input=[self._normalize(text) for text in texts],
                )
                return [item.embedding for item in response.data]

        return _DashScopeEmbedding(
            model_name=model_name,
            api_key=api_key,
            api_base=api_base,
        )


def _configure_embed_model() -> str:
    """Configure LlamaIndex embeddings.

    Preference order:
      1. ``TRPG_EMBED_BACKEND=huggingface`` → local HuggingFace model
      2. ``TRPG_EMBED_BACKEND=openai``      → OpenAI embeddings
      3. ``TRPG_EMBED_BACKEND=qwen``        → DashScope Qwen embeddings
      4. default ``auto``                  → HuggingFace if available, else OpenAI
    """
    from llama_index.core import Settings

    backend = os.getenv("TRPG_EMBED_BACKEND", "auto").strip().lower()
    hf_model = os.getenv("TRPG_HF_EMBED_MODEL", "BAAI/bge-m3")
    openai_model = os.getenv("TRPG_OPENAI_EMBED_MODEL", "text-embedding-3-small")
    qwen_model = os.getenv("TRPG_QWEN_EMBED_MODEL", "text-embedding-v4")
    dashscope_api_base = os.getenv(
        "TRPG_DASHSCOPE_API_BASE",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if backend in {"qwen", "dashscope"}:
        if not openai_api_key:
            raise ValueError(
                "Qwen embeddings requested but no API key was found. "
                "Set OPENAI_API_KEY."
            )
        try:
            Settings.embed_model = DashScopeEmbedding.create(
                model_name=qwen_model,
                api_key=openai_api_key,
                api_base=dashscope_api_base,
            )
            return f"qwen:{qwen_model}"
        except ImportError:
            raise ImportError(
                "Qwen embeddings require the OpenAI client package. Install:\n"
                "  pip install openai"
            ) from None

    if backend in {"huggingface", "hf", "auto"}:
        try:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding

            Settings.embed_model = HuggingFaceEmbedding(model_name=hf_model)
            return f"huggingface:{hf_model}"
        except ImportError:
            if backend in {"huggingface", "hf"}:
                raise ImportError(
                    "HuggingFace embeddings requested but not installed.\n"
                    "  pip install llama-index-embeddings-huggingface"
                ) from None

    if backend in {"openai", "auto"}:
        try:
            from llama_index.embeddings.openai import OpenAIEmbedding

            Settings.embed_model = OpenAIEmbedding(model=openai_model)
            return f"openai:{openai_model}"
        except ImportError:
            raise ImportError(
                "No usable embedding backend found. Install one of:\n"
                "  pip install llama-index-embeddings-huggingface\n"
                "  pip install llama-index-embeddings-openai"
            ) from None

    raise ValueError(
        "Unsupported TRPG_EMBED_BACKEND value. Use one of: auto, huggingface, openai, qwen."
    )


def _extract_chunk_sections(text: str, fallback_sections: list[str]) -> list[str]:
    headings = [
        match.group(1).strip()
        for match in re.finditer(r"^#{1,6}\s+(.*)", text, flags=re.MULTILINE)
    ]
    return headings or fallback_sections


def _slugify_doc_name(name: str) -> str:
    ascii_safe = name.encode("ascii", errors="ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_safe.lower()).strip("_") or "doc"


def _resolve_markdown_path(doc_id: str) -> Path | None:
    normalized_doc_id = doc_id[:-3] if doc_id.lower().endswith(".md") else doc_id

    exact_clean_path = CLEAN_MARKDOWN_DIR / doc_id
    if doc_id.lower().endswith(".md") and exact_clean_path.exists():
        return exact_clean_path

    direct_path = CLEAN_MARKDOWN_DIR / f"{normalized_doc_id}.md"
    if direct_path.exists():
        return direct_path

    if DOCUMENTS_DIR.exists():
        for markdown_path in sorted(DOCUMENTS_DIR.glob("*.md")):
            if markdown_path.name == doc_id:
                return markdown_path
            if markdown_path.stem == normalized_doc_id:
                return markdown_path
            if _slugify_doc_name(markdown_path.stem) == normalized_doc_id:
                return markdown_path

    return None


def _split_with_boundary(text: str, pattern: str) -> list[str]:
    parts = [part.strip() for part in re.split(pattern, text) if part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _window_split(text: str, *, chunk_size: int) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(stripped):
        end = min(start + chunk_size, len(stripped))
        chunks.append(stripped[start:end].strip())
        if end >= len(stripped):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return [chunk for chunk in chunks if chunk]


def _pack_units(
    units: list[str],
    *,
    joiner: str,
    chunk_size: int,
    split_oversized: callable,
) -> list[str]:
    chunks: list[str] = []
    current = ""

    for unit in units:
        stripped = unit.strip()
        if not stripped:
            continue
        if len(stripped) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(split_oversized(stripped, chunk_size=chunk_size))
            continue

        candidate = stripped if not current else f"{current}{joiner}{stripped}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = stripped

    if current:
        chunks.append(current)

    return chunks


def _split_by_clauses(text: str, *, chunk_size: int) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= chunk_size:
        return [stripped]

    clauses = _split_with_boundary(stripped, r"(?<=[，,])")
    if len(clauses) == 1:
        return _window_split(stripped, chunk_size=chunk_size)

    return _pack_units(
        clauses,
        joiner="",
        chunk_size=chunk_size,
        split_oversized=lambda value, *, chunk_size: _window_split(value, chunk_size=chunk_size),
    )


def _split_by_sentences(text: str, *, chunk_size: int) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= chunk_size:
        return [stripped]

    sentences = _split_with_boundary(stripped, r"(?<=[。！？.!?])")
    if len(sentences) == 1:
        return _split_by_clauses(stripped, chunk_size=chunk_size)

    return _pack_units(
        sentences,
        joiner="",
        chunk_size=chunk_size,
        split_oversized=_split_by_clauses,
    )


def _split_by_paragraphs(text: str, *, chunk_size: int) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= chunk_size:
        return [stripped]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", stripped) if part.strip()]
    if len(paragraphs) == 1:
        return _split_by_sentences(stripped, chunk_size=chunk_size)

    return _pack_units(
        paragraphs,
        joiner="\n\n",
        chunk_size=chunk_size,
        split_oversized=_split_by_sentences,
    )


def _build_heading_prefix(sections: list[str]) -> str:
    return "\n".join(
        f"{'#' * min(level, 6)} {title}"
        for level, title in enumerate(sections, 1)
    )


def _format_section_chunk(sections: list[str], body: str) -> str:
    prefix = _build_heading_prefix(sections)
    stripped_body = body.strip()
    if prefix and stripped_body:
        return f"{prefix}\n\n{stripped_body}"
    return prefix or stripped_body


def _split_structured_markdown_chunk(
    body: str,
    *,
    sections: list[str],
    chunk_size: int = CHUNK_SIZE,
) -> list[str]:
    prefix = _build_heading_prefix(sections)
    reserved = len(prefix) + 2 if prefix else 0
    content_limit = max(chunk_size - reserved, chunk_size // 2)
    body_chunks = _split_by_paragraphs(body, chunk_size=content_limit)
    return [
        _format_section_chunk(sections, chunk)
        for chunk in body_chunks
        if chunk.strip()
    ]


def _iter_markdown_blocks(doc_id: str, path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    page_num = 0
    heading_stack: list[str] = []
    buffer: list[str] = []
    block_page = page_num
    blocks: list[dict[str, Any]] = []

    def flush_block() -> None:
        nonlocal buffer, block_page
        body = "\n".join(buffer).strip()
        buffer = []
        if not body:
            return
        blocks.append(
            {
                "doc_id": doc_id,
                "source": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "page_num": block_page,
                "sections": heading_stack.copy(),
                "markdown": body,
            }
        )

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        page_match = PAGE_MARKER_RE.match(stripped)
        if page_match:
            flush_block()
            page_num = int(page_match.group(1))
            block_page = page_num
            continue

        heading_match = HEADING_RE.match(stripped)
        if heading_match:
            flush_block()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_stack = heading_stack[: level - 1] + [title]
            block_page = page_num
            continue

        if stripped.startswith("![]("):
            continue

        if not stripped and not buffer:
            continue

        buffer.append(line)

    flush_block()
    return blocks


def _load_markdown_nodes(doc_id: str, path: Path) -> list:
    from llama_index.core.schema import TextNode

    nodes: list[TextNode] = []
    for block_idx, block in enumerate(_iter_markdown_blocks(doc_id, path)):
        chunks = _split_structured_markdown_chunk(
            block["markdown"],
            sections=block.get("sections", []),
        )
        for chunk_idx, chunk_text in enumerate(chunks):
            metadata = {
                "doc_id": block["doc_id"],
                "source": block["source"],
                "page_num": block["page_num"],
                "sections": block.get("sections", []),
                "chunk_idx": chunk_idx,
            }
            nodes.append(
                TextNode(
                    text=chunk_text,
                    metadata=metadata,
                    excluded_embed_metadata_keys=list(metadata),
                    id_=f"{block['doc_id']}::p{block['page_num']}::b{block_idx}::c{chunk_idx}",
                )
            )
    return nodes


def _load_nodes(doc_ids: list[str]) -> list:
    """Read markdown files for *doc_ids* and return nodes.

    Markdown is preferred and is chunked by heading hierarchy, then by
    paragraph, sentence, and clause while preserving page markers like
    ``{242}------------------------------------------------`` as page metadata.
    """
    from llama_index.core.schema import TextNode

    nodes: list[TextNode] = []
    for doc_id in doc_ids:
        markdown_path = _resolve_markdown_path(doc_id)
        if markdown_path is not None:
            logger.info("Loading %r from markdown %s", doc_id, markdown_path)
            nodes.extend(_load_markdown_nodes(doc_id, markdown_path))
            continue

        logger.warning(
            "No markdown file found for doc_id=%r – expected data/clean_markdown/<doc_id>.md or a matching documents/*.md",
            doc_id,
        )
    return nodes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_index(index_name: str, doc_ids: list[str]) -> None:
    """Ingest *doc_ids* into a named vector index and persist it to disk.

    The index is saved under ``data/indices/<index_name>/`` and can be loaded
    later with :func:`load_index` without re-ingesting.

    Args:
        index_name: Logical name, e.g. ``"rules"`` or ``"lore"``.
        doc_ids:    Stems of markdown files under ``data/clean_markdown/``
                    or matching markdown files under ``documents/``.

    Raises:
        ValueError:  No markdown nodes found for any of the given doc_ids.
        ImportError: llama-index-core is not installed.
    """
    _require_llama()
    from llama_index.core import VectorStoreIndex

    embed_backend = _configure_embed_model()

    nodes = _load_nodes(doc_ids)
    if not nodes:
        raise ValueError(
            f"No pages loaded for {doc_ids!r}. "
            "Run `python -m src.documents.extract` first."
        )

    persist_dir = INDEX_DIR / index_name
    persist_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Building %r index with %d page-nodes…", index_name, len(nodes))
    logger.info("Embedding backend: %s", embed_backend)
    index = VectorStoreIndex(nodes, show_progress=True)
    index.storage_context.persist(persist_dir=str(persist_dir))
    logger.info("Index %r saved to %s", index_name, persist_dir)


def load_index(index_name: str):
    """Load a previously built index from disk.

    Args:
        index_name: Must match a name passed to :func:`build_index` earlier.

    Returns:
        A ``VectorStoreIndex`` instance ready for retrieval.

    Raises:
        FileNotFoundError: Index directory does not exist.
    """
    _require_llama()
    _configure_embed_model()
    from llama_index.core import StorageContext, load_index_from_storage

    persist_dir = INDEX_DIR / index_name
    if not persist_dir.exists():
        raise FileNotFoundError(
            f"Index {index_name!r} not found at {persist_dir}. "
            "Run build_index() first."
        )
    ctx = StorageContext.from_defaults(persist_dir=str(persist_dir))
    return load_index_from_storage(ctx)


def query(
    index_name: str,
    query_text: str,
    top_k: int = 5,
    filters: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Retrieve the *top_k* most relevant passages from a named index.

    Args:
        index_name: ``"rules"`` or ``"lore"`` (or any custom name).
        query_text: Natural-language question or keyword phrase.
        top_k:      Number of passages to retrieve.
        filters:    Optional dict of exact-match metadata filters, e.g.
                    ``{"doc_id": "5ednd__phb"}`` to restrict to one document.

    Returns:
        List of result dicts, each with keys:
            ``text``      – passage markdown text
            ``score``     – cosine similarity score (higher = more relevant)
            ``doc_id``    – source document identifier
            ``page_num``  – 0-indexed page number within the source PDF
            ``source``    – relative path to the original PDF
            ``sections``  – list of heading strings found on that page
            ``chunk_idx`` – chunk number within the page record
    """
    index = load_index(index_name)

    retriever_kwargs: dict[str, Any] = {"similarity_top_k": top_k}
    if filters:
        from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
        retriever_kwargs["filters"] = MetadataFilters(
            filters=[
                ExactMatchFilter(key=k, value=v) for k, v in filters.items()
            ]
        )

    retriever = index.as_retriever(**retriever_kwargs)
    hits = retriever.retrieve(query_text)
    return [
        {
            "text":     h.node.text,
            "score":    h.score,
            "doc_id":   h.node.metadata.get("doc_id", ""),
            "page_num": h.node.metadata.get("page_num", -1),
            "source":   h.node.metadata.get("source", ""),
            "sections": h.node.metadata.get("sections", []),
            "chunk_idx": h.node.metadata.get("chunk_idx", 0),
        }
        for h in hits
    ]


# Convenience wrappers kept thin so tools.py can import them by name.

def query_rules(
    query_text: str,
    top_k: int = 5,
    filters: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Query the ``rules`` index.  See :func:`query` for return format."""
    return query("rules", query_text, top_k=top_k, filters=filters)


def query_lore(
    query_text: str,
    top_k: int = 5,
    filters: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Query the ``lore`` index.  See :func:`query` for return format."""
    return query("lore", query_text, top_k=top_k, filters=filters)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    ap = argparse.ArgumentParser(
        description="Build or query a TRPG RAG index.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m src.rag.rag build rules 5ednd__phb 5ednd__mm\n"
            "  python -m src.rag.rag query rules 'fireball damage'\n"
            "  python -m src.rag.rag query lore  'main antagonist' --top_k 3\n"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    bp = sub.add_parser("build", help="Build a named index from page_jsonl files.")
    bp.description = "Build a named index from markdown files."
    bp.add_argument("index_name", help="Index name, e.g. rules or lore.")
    bp.add_argument("doc_ids", nargs="+", metavar="DOC_ID",
                    help="Document IDs (stems of data/clean_markdown/*.md or matching documents/*.md).")

    qp = sub.add_parser("query", help="Query an index.")
    qp.add_argument("index_name", help="Index name to search.")
    qp.add_argument("query_text", help="Natural-language query.")
    qp.add_argument("--top_k", type=int, default=5)

    args = ap.parse_args(argv)

    if args.cmd == "build":
        build_index(args.index_name, args.doc_ids)
        print(f"Index '{args.index_name}' built from {args.doc_ids}.")
    else:
        results = query(args.index_name, args.query_text, top_k=args.top_k)
        if not results:
            print("No results found.")
            return 0
        for i, r in enumerate(results, 1):
            secs = " > ".join(r["sections"][:3]) if r["sections"] else "(no headings)"
            print(f"\n[{i}] {r['doc_id']}  p{r['page_num']}  §{secs}  score={r['score']:.4f}")
            print(r["text"])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
