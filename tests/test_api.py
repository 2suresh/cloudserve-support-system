from fastapi.testclient import TestClient

from src import llm_client
from src.api import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["checks"]["vector_store"] is True


def test_submit_ticket_returns_a_routed_result(monkeypatch):
    monkeypatch.setattr(
        llm_client, "chat_json",
        lambda system, user: (
            {"intent": "billing_query", "urgency": "medium", "confidence": 0.95, "alternatives": []}
            if "classifier" in system.lower()
            else {"draft": "Here is your answer.", "citations": [{"claim": "x", "source_index": 1}], "refused": False}
        ),
    )
    response = client.post("/tickets", json={"ticket_id": "API-1", "channel": "chat", "body": "billing question"})
    assert response.status_code == 200
    body = response.json()
    assert body["final_action"] in {"sent_to_customer", "escalated"}


def test_submit_empty_ticket_returns_422():
    response = client.post("/tickets", json={})
    assert response.status_code == 422


def test_metrics_endpoint_returns_prometheus_text():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"tickets_processed_total" in response.content
