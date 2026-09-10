from src.ingest import normalize_ticket


def test_all_four_channels_normalise_without_error():
    for channel in ["email", "chat", "docs_comment", "forum"]:
        raw = {"ticket_id": f"T-{channel}", "channel": channel, "subject": "help", "body": "something is broken"}
        ticket = normalize_ticket(raw)
        assert ticket.channel == channel
        assert ticket.body == "something is broken"


def test_missing_subject_and_empty_body_do_not_raise():
    ticket = normalize_ticket({"ticket_id": "T-1", "channel": "chat", "body": ""})
    assert ticket.subject is None
    assert ticket.body == ""


def test_unknown_channel_falls_back_rather_than_raising():
    ticket = normalize_ticket({"ticket_id": "T-2", "channel": "carrier_pigeon", "body": "hi"})
    assert ticket.channel == "email"


def test_original_text_and_channel_preserved_in_raw_payload():
    raw = {"ticket_id": "T-3", "channel": "forum", "body": "hello", "extra_field": "kept"}
    ticket = normalize_ticket(raw)
    assert ticket.raw_payload["extra_field"] == "kept"


def test_unusual_characters_do_not_raise():
    raw = {"ticket_id": "T-4", "channel": "email", "body": "control\x00chars\x07 and emoji 🎉 stay"}
    ticket = normalize_ticket(raw)
    assert "emoji" in ticket.body
    assert "\x00" not in ticket.body
