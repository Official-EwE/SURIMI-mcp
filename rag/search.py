"""Hybrid search over SURIMI reference documents. Ported from reiselivet.

Three-stage: dense (bge-m3) + lexical (BM25) + rerank (bge-reranker-v2-m3).
Falls back to dense+BM25 only if reranker fails to load (CPU-only deployment).
"""
from __future__ import annotations

import json
import pickle
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterable, Optional, Sequence

import numpy as np

CACHE_DIR = Path(__file__).resolve().parent.parent / "rag_cache"
EMBEDDER_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
DENSE_TOPK = 40
BM25_TOPK = 40

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+", re.UNICODE)


def _tokenise(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class _State:
    embedder: object
    reranker: object  # None if unavailable
    embeddings: np.ndarray
    meta: list[dict]
    texts: list[str]
    bm25: object
    doc_ids: np.ndarray


_state: Optional[_State] = None
_lock = Lock()


def warmup() -> None:
    global _state
    with _lock:
        if _state is not None:
            return
        if not (CACHE_DIR / "embeddings.npy").exists():
            print("[rag] no rag_cache/embeddings.npy — RAG disabled", flush=True)
            return

        from sentence_transformers import SentenceTransformer

        t0 = time.time()
        embeddings = np.load(CACHE_DIR / "embeddings.npy")
        meta = json.loads((CACHE_DIR / "chunk_meta.json").read_text(encoding="utf-8"))
        texts = json.loads((CACHE_DIR / "chunks_text.json").read_text(encoding="utf-8"))
        with open(CACHE_DIR / "bm25.pkl", "rb") as f:
            bm25 = pickle.load(f)["bm25"]
        doc_ids = np.array([m["doc_id"] for m in meta], dtype=object)
        print(f"[rag] cache loaded in {time.time()-t0:.2f}s ({len(meta)} chunks)", flush=True)

        device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
        except ImportError:
            pass

        t0 = time.time()
        embedder = SentenceTransformer(EMBEDDER_MODEL, device=device)
        print(f"[rag] embedder loaded ({device}) in {time.time()-t0:.1f}s", flush=True)

        reranker = None
        try:
            from sentence_transformers import CrossEncoder
            t0 = time.time()
            reranker = CrossEncoder(RERANKER_MODEL, device=device)
            print(f"[rag] reranker loaded ({device}) in {time.time()-t0:.1f}s", flush=True)
        except Exception as e:
            print(f"[rag] reranker skipped: {e}", flush=True)

        _state = _State(
            embedder=embedder,
            reranker=reranker,
            embeddings=embeddings,
            meta=meta,
            texts=texts,
            bm25=bm25,
            doc_ids=doc_ids,
        )


def is_available() -> bool:
    return _state is not None


def _ensure() -> Optional[_State]:
    if _state is None:
        warmup()
    return _state


def search(
    query: str,
    top_k: int = 5,
    doc_filter: Optional[Iterable[str]] = None,
) -> list[dict]:
    state = _ensure()
    if state is None:
        return []

    doc_filter_list = list(doc_filter) if doc_filter else None
    mask = None
    if doc_filter_list:
        allowed = set(doc_filter_list)
        mask = np.array([d in allowed for d in state.doc_ids], dtype=bool)

    q_vec = state.embedder.encode(
        [query], normalize_embeddings=True, convert_to_numpy=True,
    )[0]
    dense_scores = state.embeddings @ q_vec
    dense_idx = _top_indices(dense_scores, DENSE_TOPK, mask)

    bm25_scores = np.asarray(state.bm25.get_scores(_tokenise(query)), dtype=np.float32)
    bm25_idx = _top_indices(bm25_scores, BM25_TOPK, mask)

    union = np.unique(np.concatenate([dense_idx, bm25_idx])) if dense_idx.size or bm25_idx.size else np.array([], dtype=np.int64)
    if union.size == 0:
        return []

    if state.reranker is not None:
        pairs = [(query, state.texts[i]) for i in union.tolist()]
        rerank_logits = state.reranker.predict(pairs, convert_to_numpy=True)
        rerank_scores = 1.0 / (1.0 + np.exp(-rerank_logits))
        order = np.argsort(-rerank_scores)[:top_k]
    else:
        combo = np.zeros(len(union), dtype=np.float32)
        for i, idx in enumerate(union):
            combo[i] = dense_scores[idx] * 0.6 + (bm25_scores[idx] / max(bm25_scores.max(), 1e-9)) * 0.4
        order = np.argsort(-combo)[:top_k]
        rerank_scores = combo

    results: list[dict] = []
    for o in order:
        chunk_idx = int(union[o])
        m = state.meta[chunk_idx]
        results.append({
            "doc_id": m["doc_id"],
            "doc_title": m["doc_title"],
            "snippet": state.texts[chunk_idx][:500],
            "score": float(rerank_scores[o]),
        })
    return results


def _top_indices(scores: np.ndarray, k: int, mask: Optional[np.ndarray]) -> np.ndarray:
    work = scores.copy()
    if mask is not None:
        work[~mask] = -np.inf
    k = min(k, int((np.isfinite(work)).sum()))
    if k <= 0:
        return np.array([], dtype=np.int64)
    idx = np.argpartition(-work, k - 1)[:k]
    return idx[np.argsort(-work[idx])]
