from src.retrieve import Retriever


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
