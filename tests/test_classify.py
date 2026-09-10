from src import classify, llm_client
from src.schemas import Ticket

TICKET = Ticket(ticket_id="T-1", channel="email", body="I can't log in, invalid credentials")


def test_classify_parses_a_well_formed_model_response(monkeypatch):
    monkeypatch.setattr(
        llm_client, "chat_json",
        lambda system, user: {"intent": "authentication_failure", "urgency": "high", "confidence": 0.91, "alternatives": []},
    )
    result = classify.classify(TICKET)
    assert result.intent == "authentication_failure"
    assert result.urgency == "high"
    assert 0.0 <= result.confidence <= 1.0
    assert not result.fallback_used


def test_classify_falls_back_on_provider_error(monkeypatch):
    def _raise(system, user):
        raise llm_client.ProviderError("simulated outage")

    monkeypatch.setattr(llm_client, "chat_json", _raise)
    result = classify.classify(TICKET)
    assert result.fallback_used
    assert result.intent == "unclear_request"


def test_classify_falls_back_on_invalid_intent_category(monkeypatch):
    monkeypatch.setattr(
        llm_client, "chat_json",
        lambda system, user: {"intent": "not_a_real_category", "urgency": "medium", "confidence": 0.5},
    )
    result = classify.classify(TICKET)
    assert result.intent == "unclear_request"
