from src import config, decision_log, llm_client
from src.graph import run_pipeline


def _stub_chat_json(system_prompt, user_content):
    if "classifier" in system_prompt.lower():
        return {"intent": "billing_query", "urgency": "medium", "confidence": 0.95, "alternatives": []}
    return {"draft": "Here is the answer, grounded in the source provided.", "citations": [{"claim": "source", "source_index": 1}], "refused": False}


def test_pipeline_runs_end_to_end_for_every_channel(monkeypatch):
    monkeypatch.setattr(llm_client, "chat_json", _stub_chat_json)
    for channel in ["email", "chat", "docs_comment", "forum"]:
        raw = {"ticket_id": f"E2E-{channel}", "channel": channel, "body": "How is my invoice calculated this month?"}
        result = run_pipeline(raw)
        assert result["final_action"] in {"sent_to_customer", "escalated"}
        rows = decision_log.rows_for_ticket(f"E2E-{channel}")
        assert {r.stage for r in rows} == {"classify", "retrieve", "route", "generate", "validate", "finalize"}


def test_engineered_guardrail_ticket_gets_blocked_and_escalated(monkeypatch):
    def _leaky_generate(system_prompt, user_content):
        if "classifier" in system_prompt.lower():
            return {"intent": "billing_query", "urgency": "medium", "confidence": 0.95, "alternatives": []}
        return {"draft": "Sure, here's an API key: sk-abcdefghijklmnopqrstuvwx1234", "citations": [{"claim": "x", "source_index": 1}], "refused": False}

    monkeypatch.setattr(llm_client, "chat_json", _leaky_generate)
    raw = {"ticket_id": "E2E-GUARDRAIL", "channel": "chat", "body": "How is my invoice calculated?"}
    result = run_pipeline(raw)

    assert result["validation"]["passed"] is False
    assert result["final_action"] == "escalated"
    rows = decision_log.rows_for_ticket("E2E-GUARDRAIL")
    validate_row = next(r for r in rows if r.stage == "validate")
    assert validate_row.guardrail_blocked == 1


def test_kill_switch_escalates_everything_instead_of_sending(monkeypatch):
    monkeypatch.setattr(llm_client, "chat_json", _stub_chat_json)
    monkeypatch.setattr(config, "AUTO_RESPONSE_ENABLED", False)
    raw = {"ticket_id": "E2E-KILLSWITCH", "channel": "chat", "body": "How is my invoice calculated this month?"}
    result = run_pipeline(raw)

    assert result["final_action"] == "escalated"
    rows = decision_log.rows_for_ticket("E2E-KILLSWITCH")
    finalize_row = next(r for r in rows if r.stage == "finalize")
    assert "kill switch" in finalize_row.reason


def test_malformed_ticket_does_not_crash_the_pipeline(monkeypatch):
    monkeypatch.setattr(llm_client, "chat_json", _stub_chat_json)
    raw = {"ticket_id": "E2E-MALFORMED", "channel": "unknown_channel", "body": None}
    result = run_pipeline(raw)
    assert result["final_action"] in {"sent_to_customer", "escalated"}
