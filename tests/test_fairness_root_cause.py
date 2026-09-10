import json

from evaluation.fairness_root_cause import run


def _row(ticket_id, expected, predicted):
    return {
        "ticket_id": ticket_id,
        "expected_intent": expected,
        "classification": {"intent": predicted},
    }


def test_flags_a_well_supported_dominant_confusion(tmp_path):
    # group "a" gets all its errors from intent X, which is globally confused
    # with intent Y at a high, well-supported rate -- should flag as fixable
    rows = []
    for i in range(10):
        rows.append(_row(f"T{i}", "X", "Y" if i < 7 else "X"))  # X->Y globally 70%, n=7
    for i in range(10, 13):
        rows.append(_row(f"T{i}", "Z", "Z"))  # unrelated, all correct
    results_path = tmp_path / "results.jsonl"
    results_path.write_text("\n".join(json.dumps(r) for r in rows))

    tickets = [{"ticket_id": f"T{i}", "customer_tier": "enterprise" if i < 5 else "standard"} for i in range(13)]
    tickets_path = tmp_path / "tickets.json"
    tickets_path.write_text(json.dumps(tickets))

    report = run(results_path, tickets_path, "customer_tier")
    assert report["likely_fixable_pattern_found"] is True


def test_does_not_flag_a_low_support_fluke(tmp_path):
    # one single error (X -> Y) is "100% confusion" but from n=1 globally --
    # must not be flagged as a reliable pattern
    rows = [_row("T0", "X", "Y")]
    for i in range(1, 10):
        rows.append(_row(f"T{i}", "Z", "Z"))
    results_path = tmp_path / "results.jsonl"
    results_path.write_text("\n".join(json.dumps(r) for r in rows))

    tickets = [{"ticket_id": f"T{i}", "customer_tier": "enterprise" if i == 0 else "standard"} for i in range(10)]
    tickets_path = tmp_path / "tickets.json"
    tickets_path.write_text(json.dumps(tickets))

    report = run(results_path, tickets_path, "customer_tier")
    assert report["likely_fixable_pattern_found"] is False
