"""Extract and chunk reference documents for embedding.

Run:
    cd surimi-mcp
    .venv/bin/python -m rag.extract

Outputs rag_cache/chunks.json — input for rag.embed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rag.docs import DOCUMENTS

CACHE_DIR = Path(__file__).resolve().parent.parent / "rag_cache"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 200


def _read_text(path: Path) -> str:
    if path.suffix == ".pdf":
        try:
            return subprocess.check_output(
                ["pdftotext", "-layout", str(path), "-"],
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text.strip()] if text.strip() else []

    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk.strip())
        i += chunk_size - overlap
    return chunks


def main() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    all_chunks = []
    for doc in DOCUMENTS:
        if not doc.source_path.exists():
            print(f"  SKIP {doc.doc_id} (file not found)")
            continue

        text = _read_text(doc.source_path)
        if not text.strip():
            continue

        chunks = _chunk_text(text)
        for idx, chunk in enumerate(chunks):
            all_chunks.append({
                "doc_id": doc.doc_id,
                "doc_title": doc.title,
                "kind": doc.kind,
                "page": idx,
                "end_page": idx,
                "chunk_idx": idx,
                "text": chunk,
            })

    out = CACHE_DIR / "chunks.json"
    out.write_text(json.dumps(all_chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[extract] {len(all_chunks)} chunks from {len(DOCUMENTS)} documents -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
