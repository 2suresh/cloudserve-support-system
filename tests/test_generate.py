from src import generate, llm_client
from src.schemas import ClassificationResult, RetrievedPassage, RoutingDecision, Ticket

TICKET = Ticket(ticket_id="T-1", channel="email", body="How do I export my data?")
CLASSIFICATION = ClassificationResult(intent="data_export", urgency="low", confidence=0.9)
PASSAGE = RetrievedPassage(doc_id="DOC-DATA-001", chunk_id="DOC-DATA-001::resolution", title="Exporting data", text="Use the export API.", score=0.8)


def test_answer_mode_maps_citations_to_retrieved_passages(monkeypatch):
    monkeypatch.setattr(
        llm_client, "chat_json",
        lambda system, user: {
            "draft": "You can export your data using the export API.",
            "citations": [{"claim": "export API", "source_index": 1}],
            "refused": False,
        },
    )
    routing = RoutingDecision(action="auto_respond", reason="ok", threshold_used=0.8)
    result = generate.generate(TICKET, CLASSIFICATION, [PASSAGE], routing)
    assert result.mode == "answer"
    assert result.citations[0].doc_id == "DOC-DATA-001"


def test_summary_mode_for_escalated_ticket(monkeypatch):
    monkeypatch.setattr(
        llm_client, "chat_json",
        lambda system, user: {"draft": "Customer wants to export data; no matching doc found.", "citations": [], "refused": False},
    )
    routing = RoutingDecision(action="escalate", reason="low confidence", threshold_used=0.8)
    result = generate.generate(TICKET, CLASSIFICATION, [], routing)
    assert result.mode == "summary"


def test_generate_falls_back_on_provider_error(monkeypatch):
    def _raise(system, user):
        raise llm_client.ProviderError("simulated outage")

    monkeypatch.setattr(llm_client, "chat_json", _raise)
    routing = RoutingDecision(action="auto_respond", reason="ok", threshold_used=0.8)
    result = generate.generate(TICKET, CLASSIFICATION, [PASSAGE], routing)
    assert result.refused is True
