"""Document registry for SURIMI RAG layer.

Scans references/ for markdown, text, and PDF files. Each gets a stable
doc_id slug derived from its path relative to references/.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REFERENCES_ROOT = Path(__file__).resolve().parents[2] / "references"
CUSTOM_DOCS_PATH = Path(__file__).resolve().parent.parent / "rag_cache" / "custom_docs.json"


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    kind: str
    source_path: Path
    summary: str


def _slug(path: Path) -> str:
    rel = path.relative_to(REFERENCES_ROOT)
    return re.sub(r"[^a-z0-9]+", "-", str(rel).lower()).strip("-")


def _title_from_path(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").title()


def _classify(path: Path) -> str:
    s = str(path).lower()
    if "protocol" in s:
        return "protocol"
    if "wiki" in s:
        return "wiki"
    if "ecopath" in s:
        return "model"
    if "grant" in s:
        return "grant"
    if "data-lake" in s or "datagui" in s:
        return "data-infrastructure"
    return "reference"


def discover_documents() -> list[Document]:
    docs: list[Document] = []
    if not REFERENCES_ROOT.exists():
        return docs

    for ext in ("*.md", "*.txt", "*.pdf"):
        for path in sorted(REFERENCES_ROOT.rglob(ext)):
            if any(skip in str(path) for skip in [
                "node_modules", ".git", "__pycache__", ".venv",
                "package.json", "package-lock", "tsconfig",
            ]):
                continue
            docs.append(Document(
                doc_id=_slug(path),
                title=_title_from_path(path),
                kind=_classify(path),
                source_path=path,
                summary="",
            ))

    if CUSTOM_DOCS_PATH.exists():
        custom = json.loads(CUSTOM_DOCS_PATH.read_text(encoding="utf-8"))
        for c in custom:
            docs.append(Document(
                doc_id=c["doc_id"],
                title=c["title"],
                kind=c.get("kind", "custom"),
                source_path=Path(c["source_path"]),
                summary=c.get("summary", ""),
            ))

    return docs


DOCUMENTS = discover_documents()
DOC_BY_ID = {d.doc_id: d for d in DOCUMENTS}
