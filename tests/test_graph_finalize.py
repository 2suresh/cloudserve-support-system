from src.graph import node_finalize
from src.schemas import GenerationResult, RoutingDecision, Ticket, ValidationResult


def _state(refused: bool):
    ticket = Ticket(ticket_id="T-1", channel="email", subject="s", body="b")
    routing = RoutingDecision(
        action="auto_respond", reason="confidence 0.90 >= threshold 0.80, grounded, not policy-excluded", threshold_used=0.8)
    generation = GenerationResult(draft_text="We don't have a confident answer.", citations=[
    ], mode="answer", refused=refused)
    validation = ValidationResult(passed=True, checks_run=[])
    return {"ticket": ticket, "routing": routing, "generation": generation, "validation": validation, "log_entries": []}


def test_refused_generation_escalates_even_when_guardrails_pass():
    result = node_finalize(_state(refused=True))
    assert result["final_action"] == "escalated"
    assert "refused" in result["log_entries"][-1]["reason"]


def test_confident_generation_still_auto_sends():
    result = node_finalize(_state(refused=False))
    assert result["final_action"] == "sent_to_customer"
