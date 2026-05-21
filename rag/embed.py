"""Embed chunks and build BM25 index. Ported from reiselivet.

Run (requires CUDA for bge-m3):
    cd surimi-mcp
    .venv/bin/python -m rag.embed

Outputs in rag_cache/:
- embeddings.npy   float32 [n_chunks, 1024]
- chunk_meta.json
- chunks_text.json
- bm25.pkl
"""
from __future__ import annotations

import json
import pickle
import re
import sys
import time
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

CACHE_DIR = Path(__file__).resolve().parent.parent / "rag_cache"
MODEL_NAME = "BAAI/bge-m3"
BATCH_SIZE = 32

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+", re.UNICODE)


def _tokenise(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def main() -> int:
    chunks_path = CACHE_DIR / "chunks.json"
    if not chunks_path.exists():
        print(f"[embed] missing {chunks_path}; run rag.extract first")
        return 1

    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    print(f"[embed] {len(chunks)} chunks loaded")

    texts = [c["text"] for c in chunks]
    meta = [{k: c[k] for k in ("doc_id", "doc_title", "page", "end_page", "chunk_idx")} for c in chunks]

    print(f"[embed] loading {MODEL_NAME}...")
    t0 = time.time()
    device = "cuda"
    try:
        import torch
        if not torch.cuda.is_available():
            device = "cpu"
            print("[embed] CUDA not available, using CPU (slower)")
    except ImportError:
        device = "cpu"
    model = SentenceTransformer(MODEL_NAME, device=device)
    print(f"[embed] model loaded in {time.time()-t0:.1f}s ({device})")

    t0 = time.time()
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    print(f"[embed] encoded {len(texts)} chunks in {time.time()-t0:.1f}s -> {embeddings.shape}")

    np.save(CACHE_DIR / "embeddings.npy", embeddings.astype(np.float32))
    (CACHE_DIR / "chunk_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (CACHE_DIR / "chunks_text.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")

    print("[embed] building BM25 index...")
    tokenised = [_tokenise(t) for t in texts]
    bm25 = BM25Okapi(tokenised)
    with open(CACHE_DIR / "bm25.pkl", "wb") as f:
        pickle.dump({"bm25": bm25}, f)

    print(f"[embed] done: embeddings.npy ({embeddings.nbytes/1e6:.1f} MB), bm25.pkl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
