from src import decision_log
from src.schemas import DecisionLogEntry


def test_log_decision_round_trips():
    entry = DecisionLogEntry(
        ticket_id="T-LOG-1", channel="email", stage="route", prediction="auto_respond",
        confidence=0.9, action="auto_respond", reason="confidence above threshold", threshold_used=0.8,
    )
    decision_log.log_decision(entry)
    rows = decision_log.rows_for_ticket("T-LOG-1")
    assert len(rows) == 1
    assert rows[0].action == "auto_respond"
    assert rows[0].reason == "confidence above threshold"


def test_multiple_stages_reconcile_against_one_ticket():
    ticket_id = "T-LOG-2"
    for stage in ["classify", "route", "generate", "validate", "finalize"]:
        decision_log.log_decision(
            DecisionLogEntry(ticket_id=ticket_id, channel="chat", stage=stage, prediction="x", action="x", reason="x")
        )
    rows = decision_log.rows_for_ticket(ticket_id)
    assert len(rows) == 5
    assert {r.stage for r in rows} == {"classify", "route", "generate", "validate", "finalize"}
