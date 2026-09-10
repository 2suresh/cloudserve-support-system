from src.retrieve import Retriever, get_chroma_client, get_embedder, COLLECTION_NAME


def test_retrieval_resolves_to_real_corpus_passage():
    retriever = Retriever()
    results = retriever.retrieve("the console says invalid credentials when I log in", top_k=3)
    assert results, "expected at least one passage above the relevance threshold"
    assert results[0].doc_id.startswith("DOC-")
    assert results[0].score >= 0.0


def test_retrieval_returns_nothing_for_irrelevant_query():
    retriever = Retriever()
    results = retriever.retrieve("what is the capital of france", top_k=3, threshold=0.85)
    assert results == []


def test_same_query_returns_same_top_result():
    retriever = Retriever()
    first = retriever.retrieve("billing invoice question", top_k=1)
    second = retriever.retrieve("billing invoice question", top_k=1)
    assert [p.chunk_id for p in first] == [p.chunk_id for p in second]


def test_stale_article_is_excluded_from_retrieval(monkeypatch):
    """FR-11: the supplied corpus has no stale articles (every doc is 0 days
    old), so this can only be exercised with a synthetic one -- injected
    directly into the same collection the Retriever queries."""
    query = "a very specific synthetic phrase about zorbex flux capacitor recalibration"
    embedding = get_embedder().encode([query]).tolist()
    get_chroma_client().get_collection(COLLECTION_NAME).add(
        ids=["DOC-STALE-TEST::synthetic"],
        documents=[query],
        metadatas=[{"doc_id": "DOC-STALE-TEST", "title": "Stale test doc", "category": "", "last_reviewed_days_ago": 9999}],
        embeddings=embedding,
    )
    retriever = Retriever()
    results = retriever.retrieve(query, top_k=1, threshold=0.0)
    assert not any(p.doc_id == "DOC-STALE-TEST" for p in results)
