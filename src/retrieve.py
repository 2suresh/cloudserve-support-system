import json
import logging
import re
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from src import config
from src.schemas import RetrievedPassage

logger = logging.getLogger("cloudserve.retrieve")

COLLECTION_NAME = "documentation"
_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)

_embedder: SentenceTransformer | None = None
_chroma_client = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(config.EMBEDDING_MODEL)
    return _embedder


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        Path(config.CHROMA_PATH).mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=config.CHROMA_PATH, settings=Settings(anonymized_telemetry=False)
        )
    return _chroma_client


def chunk_document(doc: dict) -> list[dict]:
    """Chunk by the corpus's own heading structure (Symptoms / Common causes /
    Resolution / Notes) rather than a fixed token window, so every chunk is a
    citable, addressable unit (System_Architecture.md §3.3)."""
    content = doc.get("content", "")
    title = doc.get("title", doc.get("doc_id", ""))
    matches = list(_HEADING_RE.finditer(content))

    chunks = []
    if not matches:
        chunks.append({"section": "full", "text": content.strip() or title})
    else:
        first_start = matches[0].start()
        intro = content[:first_start].strip()
        if intro:
            chunks.append({"section": "intro", "text": intro})
        for i, m in enumerate(matches):
            section_name = m.group(1).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body = content[start:end].strip()
            chunks.append({"section": section_name, "text": f"{section_name}\n{body}" if body else section_name})

    out = []
    for c in chunks:
        if not c["text"].strip():
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", c["section"].lower()).strip("-") or "section"
        out.append(
            {
                "chunk_id": f"{doc['doc_id']}::{slug}",
                "doc_id": doc["doc_id"],
                "title": title,
                "category": doc.get("category"),
                "last_reviewed_days_ago": doc.get("last_reviewed_days_ago", 0),
                "text": c["text"],
            }
        )
    return out


def build_index(documentation_path: str | Path, force: bool = False) -> int:
    client = get_chroma_client()
    try:
        existing = client.get_collection(COLLECTION_NAME)
        if not force and existing.count() > 0:
            logger.info("index already built (%s chunks); skipping", existing.count())
            return existing.count()
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    docs = json.loads(Path(documentation_path).read_text())
    all_chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    if not all_chunks:
        return 0

    embedder = get_embedder()
    embeddings = embedder.encode([c["text"] for c in all_chunks]).tolist()
    collection.add(
        ids=[c["chunk_id"] for c in all_chunks],
        documents=[c["text"] for c in all_chunks],
        metadatas=[
            {
                "doc_id": c["doc_id"],
                "title": c["title"],
                "category": c["category"] or "",
                "last_reviewed_days_ago": c["last_reviewed_days_ago"],
            }
            for c in all_chunks
        ],
        embeddings=embeddings,
    )
    logger.info("indexed %s chunks from %s documents", len(all_chunks), len(docs))
    return len(all_chunks)


class Retriever:
    def __init__(self, documentation_path: str | Path | None = None):
        self.documentation_path = documentation_path or (config.BASE_DIR / "data" / "documentation.json")
        self._ensure_index()

    def _ensure_index(self):
        client = get_chroma_client()
        try:
            collection = client.get_collection(COLLECTION_NAME)
            if collection.count() == 0:
                raise ValueError("empty")
        except Exception:
            if Path(self.documentation_path).exists():
                build_index(self.documentation_path)
            else:
                logger.warning("no documentation corpus found at %s; retrieval will return nothing", self.documentation_path)

    def retrieve(
        self, query_text: str, top_k: int = config.RETRIEVAL_TOP_K, threshold: float = config.RETRIEVAL_RELEVANCE_THRESHOLD
    ) -> list[RetrievedPassage]:
        client = get_chroma_client()
        try:
            collection = client.get_collection(COLLECTION_NAME)
        except Exception:
            return []
        if collection.count() == 0 or not query_text.strip():
            return []

        embedder = get_embedder()
        query_embedding = embedder.encode([query_text]).tolist()
        result = collection.query(query_embeddings=query_embedding, n_results=min(top_k, collection.count()))

        passages = []
        ids = result["ids"][0]
        docs = result["documents"][0]
        metas = result["metadatas"][0]
        distances = result["distances"][0]
        for chunk_id, text, meta, distance in zip(ids, docs, metas, distances):
            score = 1.0 - distance  # cosine distance -> similarity
            if score < threshold:
                continue
            if meta.get("last_reviewed_days_ago", 0) > config.RETRIEVAL_RECENCY_LIMIT_DAYS:
                continue  # FR-11: an article reviewed too long ago can't ground an auto-answer
            passages.append(
                RetrievedPassage(
                    doc_id=meta["doc_id"],
                    chunk_id=chunk_id,
                    title=meta["title"],
                    category=meta.get("category") or None,
                    text=text,
                    score=round(score, 4),
                )
            )
        return passages
