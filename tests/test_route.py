from src.route import route
from src.schemas import ClassificationResult, RetrievedPassage

PASSAGE = RetrievedPassage(doc_id="DOC-1", chunk_id="DOC-1::a", title="t", text="x", score=0.9)


def _classification(intent="billing_query", confidence=0.9):
    return ClassificationResult(intent=intent, urgency="medium", confidence=confidence)


def test_no_retrieval_hit_escalates():
    decision = route(_classification(), [], threshold=0.8)
    assert decision.action == "escalate"
    assert "relevance threshold" in decision.reason


def test_policy_excluded_intent_escalates_even_with_high_confidence():
    decision = route(_classification(intent="security_incident", confidence=0.99), [PASSAGE], threshold=0.8)
    assert decision.action == "escalate"
    assert "policy-excluded" in decision.reason


def test_low_confidence_escalates():
    decision = route(_classification(confidence=0.5), [PASSAGE], threshold=0.8)
    assert decision.action == "escalate"


def test_confident_grounded_non_excluded_auto_responds():
    decision = route(_classification(confidence=0.95), [PASSAGE], threshold=0.8)
    assert decision.action == "auto_respond"


def test_routing_is_deterministic():
    classification = _classification(confidence=0.95)
    first = route(classification, [PASSAGE], threshold=0.8)
    second = route(classification, [PASSAGE], threshold=0.8)
    assert first.action == second.action
    assert first.reason == second.reason
