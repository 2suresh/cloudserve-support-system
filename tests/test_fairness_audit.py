import json

from evaluation.fairness_audit import run


def _row(ticket_id, final_action, passed, confidence, intent="billing_query", expected_intent="billing_query"):
    return {
        "ticket_id": ticket_id,
        "final_action": final_action,
        "validation": {"passed": passed},
        "classification": {"intent": intent, "confidence": confidence},
        "expected_intent": expected_intent,
    }


def test_fairness_audit_flags_a_large_spread(tmp_path):
    results = [
        _row("T1", "sent_to_customer", True, 0.9),
        _row("T2", "sent_to_customer", True, 0.9),
        _row("T3", "escalated", True, 0.5),
        _row("T4", "escalated", True, 0.5),
    ]
    results_path = tmp_path / "results.jsonl"
    results_path.write_text("\n".join(json.dumps(r) for r in results))

    tickets = [
        {"ticket_id": "T1", "customer_tier": "enterprise"},
        {"ticket_id": "T2", "customer_tier": "enterprise"},
        {"ticket_id": "T3", "customer_tier": "standard"},
        {"ticket_id": "T4", "customer_tier": "standard"},
    ]
    tickets_path = tmp_path / "tickets.json"
    tickets_path.write_text(json.dumps(tickets))

    report = run(results_path, tickets_path)
    tier = report["dimensions"]["customer_tier"]
    assert tier["groups"]["enterprise"]["resolution_rate"] == 1.0
    assert tier["groups"]["standard"]["resolution_rate"] == 0.0
    assert any("resolution_rate" in flag for flag in tier["flags"])


def test_fairness_audit_no_flag_when_groups_are_close(tmp_path):
    # 4 tickets per tier, each tier exactly 2 sent + 2 escalated -> identical
    # resolution rate, confidence and accuracy across groups, zero spread.
    actions = ["sent_to_customer", "sent_to_customer", "escalated", "escalated"]
    results = [_row(f"T{i}", actions[i % 4], True, 0.85) for i in range(8)]
    results_path = tmp_path / "results.jsonl"
    results_path.write_text("\n".join(json.dumps(r) for r in results))

    tickets = [{"ticket_id": f"T{i}", "customer_tier": "standard" if i < 4 else "enterprise"} for i in range(8)]
    tickets_path = tmp_path / "tickets.json"
    tickets_path.write_text(json.dumps(tickets))

    report = run(results_path, tickets_path)
    assert report["dimensions"]["customer_tier"]["flags"] == []
