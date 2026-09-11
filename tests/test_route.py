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


def test_security_incident_safety_net_escalates_credential_breach_even_if_misclassified():
    # real confirmed bypass: classifier called this api_key_issue at 0.95 confidence
    body = (
        "One of our engineers believes their credentials may have been exposed "
        "in a breach at another service. What should we be doing right now?"
    )
    decision = route(_classification(intent="api_key_issue", confidence=0.95), [PASSAGE], ticket_body=body, threshold=0.8)
    assert decision.action == "escalate"
    assert "safety-net" in decision.reason


def test_security_incident_safety_net_escalates_former_employee_access_even_if_misclassified():
    # real confirmed bypass: classifier called this account_access at 0.95 confidence
    body = (
        "A former employee appears to still have access three weeks after leaving. "
        "We have found API calls made under their account. This is urgent."
    )
    decision = route(_classification(intent="account_access", confidence=0.95), [PASSAGE], ticket_body=body, threshold=0.8)
    assert decision.action == "escalate"
    assert "safety-net" in decision.reason


def test_security_incident_safety_net_does_not_fire_on_unrelated_ticket():
    body = "I can't figure out how to set up SSO for our workspace, can you help?"
    decision = route(_classification(intent="sso_configuration", confidence=0.95), [PASSAGE], ticket_body=body, threshold=0.8)
    assert decision.action == "auto_respond"
