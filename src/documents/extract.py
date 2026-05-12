#!/usr/bin/env python3
"""PDF → Markdown + page JSONL converter using Chandra OCR (HuggingFace).

For each input PDF this script writes three artefacts under data/:

  data/clean_markdown/<doc_id>.md
      Full paginated markdown.  Page separators are kept so the file can
      be split back into pages by downstream tools.

  data/page_jsonl/<doc_id>.jsonl
      One JSON object per line, one line per page.  Each record has:
        doc_id   – safe ASCII identifier derived from the filename
        source   – relative path to the original PDF
        page_num – 0-indexed page number
        markdown – cleaned markdown text for that page
        sections – list of heading strings found on the page

  data/chunk_index/<doc_id>_meta.json
      Page-level statistics extracted from Chandra's OCR results.
      Useful for the lookup_index tool and for building RAG chunk sets
      with accurate source anchors.

Usage:
  # Convert every PDF found in documents/
  python -m src.documents.extract

  # Convert specific files
  python -m src.documents.extract documents/my_file.pdf

    # Run local HuggingFace OCR on all pages with the default checkpoint
    python -m src.documents.extract

    # Override model checkpoint and batch size
    python -m src.documents.extract --model-checkpoint datalab-to/chandra-ocr-2 --batch-size 1

Requires:
    pip install chandra-ocr[hf]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-relative output directories
# ---------------------------------------------------------------------------
PROJECT_ROOT    = Path(__file__).resolve().parents[2]
DOCUMENTS_DIR   = PROJECT_ROOT / "documents"
CLEAN_MD_DIR    = PROJECT_ROOT / "data" / "clean_markdown"
PAGE_JSONL_DIR  = PROJECT_ROOT / "data" / "page_jsonl"
CHUNK_INDEX_DIR = PROJECT_ROOT / "data" / "chunk_index"

# Page separators recognized by downstream tooling. We normalize Chandra's
# merged markdown to the existing ``{n}------------------------------------------------`` form.
_PAGE_SEP_RE = re.compile(r"\n\n\{?(\d+)\}?\n?-{48}\n\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Convert an arbitrary filename stem to a safe ASCII doc_id.

    Example: "5eDnD_玩家手册PHB_中译v1.72版" → "5ednd___phb__v1_72_"
    (non-ASCII chars become underscores, then runs are collapsed)
    """
    ascii_safe = name.encode("ascii", errors="ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_safe.lower()).strip("_") or "doc"


def _extract_headings(md: str) -> list[str]:
    """Return the text of every ATX-style heading found in *md*."""
    headings: list[str] = []
    for line in md.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            headings.append(m.group(1).strip())
    return headings


def _normalize_paginated_markdown(text: str) -> str:
    """Normalize page separators to ``{n}------------------------------------------------``."""

    def repl(match: re.Match[str]) -> str:
        return f"\n\n{{{match.group(1)}}}{'-' * 48}\n\n"

    return _PAGE_SEP_RE.sub(repl, text)


def _merge_chandra_markdown(results: list[Any]) -> str:
    """Merge page-level Chandra markdown into one paginated markdown string."""
    blocks: list[str] = []
    for page_num, result in enumerate(results):
        if page_num > 0:
            blocks.append(f"\n\n{{{page_num}}}{'-' * 48}\n\n")
        blocks.append((result.markdown or "").strip())
    return "".join(blocks).strip()


def parse_paginated_markdown(text: str) -> list[dict[str, Any]]:
    """Split a paginated markdown string into per-page records.

    If no page separators are present (single-page document or unexpected
    format) the whole text is returned as a single page-0 record.

    Returns a list of dicts::

        [
          {"page_num": 0, "markdown": "...", "sections": [...]},
          {"page_num": 1, "markdown": "...", "sections": [...]},
          ...
        ]
    """
    parts = _PAGE_SEP_RE.split(text)

    # No separators found – treat entire document as page 0.
    if len(parts) == 1:
        return [
            {
                "page_num": 0,
                "markdown": text.strip(),
                "sections": _extract_headings(text),
            }
        ]

    # _PAGE_SEP_RE.split() produces:
    #   [pre_text, page_num_str, page_text, page_num_str, page_text, …]
    pages: list[dict[str, Any]] = []

    pre = parts[0].strip()
    if pre:
        pages.append(
            {"page_num": 0, "markdown": pre, "sections": _extract_headings(pre)}
        )

    i = 1
    while i + 1 <= len(parts) - 1:
        page_num = int(parts[i])
        md_block = parts[i + 1].strip()
        pages.append(
            {
                "page_num": page_num,
                "markdown": md_block,
                "sections": _extract_headings(md_block),
            }
        )
        i += 2

    return pages


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

def convert_pdf(
    pdf_path: Path,
    model: Any,
    *,
    batch_size: int = 1,
    max_output_tokens: int | None = None,
    include_images: bool = False,
    include_headers_footers: bool = False,
) -> None:
    """Convert *pdf_path* and write the three output artefacts.

    Args:
        pdf_path:                 Absolute path to the source PDF.
        model:                    Pre-loaded Chandra InferenceManager(method="hf").
        batch_size:               Number of pages to process per generation batch.
        max_output_tokens:        Optional max output tokens per page.
        include_images:           Whether to keep extracted images in the output.
        include_headers_footers:  Whether to include page headers/footers.
    """
    from chandra.input import load_file  # type: ignore[import]
    from chandra.model.schema import BatchInputItem  # type: ignore[import]

    doc_id = slugify(pdf_path.stem)
    print(f"\n[extract] {pdf_path.name}  →  doc_id={doc_id!r}")

    pages = load_file(str(pdf_path), {})
    if not pages:
        raise ValueError("No pages were loaded from the PDF.")

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    results: list[Any] = []
    for batch_start in range(0, len(pages), batch_size):
        batch_end = min(batch_start + batch_size, len(pages))
        batch = [
            BatchInputItem(image=image, prompt_type="ocr_layout")
            for image in pages[batch_start:batch_end]
        ]
        generate_kwargs: dict[str, Any] = {
            "include_images": include_images,
            "include_headers_footers": include_headers_footers,
        }
        if max_output_tokens is not None:
            generate_kwargs["max_output_tokens"] = max_output_tokens
        print(f"  ·  processing pages {batch_start + 1}-{batch_end} of {len(pages)}")
        results.extend(model.generate(batch, **generate_kwargs))

    full_md = _normalize_paginated_markdown(_merge_chandra_markdown(results))

    metadata: dict[str, Any] = {
        "backend": "chandra-hf",
        "num_pages": len(results),
        "total_token_count": sum(result.token_count for result in results),
        "total_chunks": sum(len(result.chunks) for result in results),
        "total_images": sum(len(result.images) for result in results),
        "pages": [
            {
                "page_num": page_num,
                "page_box": result.page_box,
                "token_count": result.token_count,
                "num_chunks": len(result.chunks),
                "num_images": len(result.images),
            }
            for page_num, result in enumerate(results)
        ],
    }

    # ------------------------------------------------------------------
    # 1. Clean Markdown
    # ------------------------------------------------------------------
    CLEAN_MD_DIR.mkdir(parents=True, exist_ok=True)
    md_out = CLEAN_MD_DIR / f"{doc_id}.md"
    md_out.write_text(full_md, encoding="utf-8")
    print(f"  ✓  clean_markdown  →  {md_out.relative_to(PROJECT_ROOT)}")

    # ------------------------------------------------------------------
    # 2. Page JSONL
    # ------------------------------------------------------------------
    pages = parse_paginated_markdown(full_md)
    PAGE_JSONL_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_out = PAGE_JSONL_DIR / f"{doc_id}.jsonl"
    with jsonl_out.open("w", encoding="utf-8") as fh:
        for page in pages:
            record: dict[str, Any] = {
                "doc_id": doc_id,
                "source": str(pdf_path.relative_to(PROJECT_ROOT)),
                **page,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(
        f"  ✓  page_jsonl      →  {jsonl_out.relative_to(PROJECT_ROOT)}"
        f"  ({len(pages)} pages)"
    )

    # ------------------------------------------------------------------
    # 3. Chunk index / metadata
    # ------------------------------------------------------------------
    CHUNK_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    meta_out = CHUNK_INDEX_DIR / f"{doc_id}_meta.json"
    meta: dict[str, Any] = {
        "doc_id": doc_id,
        "source": str(pdf_path.relative_to(PROJECT_ROOT)),
        "backend": metadata.get("backend", "chandra-hf"),
        "table_of_contents": [],
        "page_count": len(pages),
        "page_stats": metadata.get("pages", []),
        "total_token_count": metadata.get("total_token_count", 0),
        "total_chunks": metadata.get("total_chunks", 0),
        "total_images": metadata.get("total_images", 0),
    }
    meta_out.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  ✓  chunk_index     →  {meta_out.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert PDF documents to Markdown + page JSONL using Chandra OCR (HF).\n"
            "Outputs are written under data/clean_markdown/, data/page_jsonl/, "
            "and data/chunk_index/."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help=(
            "PDF file(s) to convert. "
            "Omit to process every *.pdf in documents/."
        ),
    )
    parser.add_argument(
        "--device",
        default="cuda",
        metavar="DEVICE",
        help="Torch device to use: cuda (default), cpu, or mps.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        metavar="N",
        help="Pages per Chandra HF batch. Default: 1.",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        metavar="N",
        help="Optional max output tokens per page passed to Chandra.",
    )
    parser.add_argument(
        "--model-checkpoint",
        default="datalab-to/chandra-ocr-2",
        metavar="MODEL",
        help="HuggingFace checkpoint for Chandra. Default: datalab-to/chandra-ocr-2.",
    )
    parser.add_argument(
        "--include-images",
        action="store_true",
        help="Keep extracted images in Chandra outputs while processing.",
    )
    parser.add_argument(
        "--include-headers-footers",
        action="store_true",
        help="Include page headers and footers in OCR output.",
    )
    parser.add_argument(
        "--force_ocr",
        action="store_true",
        help="Deprecated no-op kept for compatibility. Chandra always runs OCR.",
    )
    args = parser.parse_args(argv)

    # Resolve input file list.
    if args.files:
        pdf_paths = [Path(f).resolve() for f in args.files]
    else:
        pdf_paths = sorted(DOCUMENTS_DIR.glob("*.pdf"))

    if not pdf_paths:
        print(
            "[extract] No PDF files found.  "
            f"Put PDFs in {DOCUMENTS_DIR} or pass paths explicitly.",
            file=sys.stderr,
        )
        return 1

    # Force the requested torch device and model checkpoint before Chandra import
    # so its settings load the right local HuggingFace configuration.
    os.environ["TORCH_DEVICE"] = args.device
    os.environ["MODEL_CHECKPOINT"] = args.model_checkpoint
    print(f"[extract] Using device: {args.device}")
    print(f"[extract] Using model checkpoint: {args.model_checkpoint}")
    if args.force_ocr:
        print("[extract] NOTE: --force_ocr is ignored because Chandra always performs OCR.")

    # Load the local HuggingFace model once and reuse it across files.
    print("[extract] Loading Chandra HF model (this may take a moment on first run)…")
    try:
        from chandra.model import InferenceManager  # type: ignore[import]
    except ImportError:
        print(
            "[extract] chandra-ocr[hf] is not installed.\n"
            "  Install it with:  pip install chandra-ocr[hf]",
            file=sys.stderr,
        )
        return 1

    model = InferenceManager(method="hf")

    errors: list[str] = []
    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            msg = f"{pdf_path} – file not found"
            print(f"[extract] WARNING: {msg}", file=sys.stderr)
            errors.append(msg)
            continue
        try:
            convert_pdf(
                pdf_path,
                model,
                batch_size=args.batch_size,
                max_output_tokens=args.max_output_tokens,
                include_images=args.include_images,
                include_headers_footers=args.include_headers_footers,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"{pdf_path.name}: {exc}"
            print(f"[extract] ERROR – {msg}", file=sys.stderr)
            errors.append(msg)

    total = len(pdf_paths)
    ok    = total - len(errors)
    print(f"\n[extract] Done.  {ok}/{total} file(s) converted successfully.")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
