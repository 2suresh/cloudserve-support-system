from src.guardrails import validate
from src.schemas import GenerationResult, Ticket

TICKET = Ticket(ticket_id="T-1", channel="email", body="hi", customer_id="CUST-1000")


def test_private_data_guardrail_blocks_an_engineered_leak():
    generation = GenerationResult(draft_text="Sure, your API key is sk-abcdefghijklmnopqrstuvwx, use it there.", mode="answer", refused=False)
    result = validate(generation, TICKET)
    assert result.passed is False
    assert "private_data" in result.blocked_reason


def test_other_customer_id_in_draft_blocks():
    generation = GenerationResult(draft_text="That issue also affected CUST-9999 last week.", mode="answer", refused=False)
    result = validate(generation, TICKET)
    assert result.passed is False


def test_own_customer_id_in_draft_does_not_block():
    generation = GenerationResult(
        draft_text="Your account CUST-1000 export completed.", citations=[], mode="answer", refused=False
    )
    result = validate(generation, TICKET)
    private_data_check = next(c for c in result.checks_run if c.name == "private_data")
    assert private_data_check.passed is True


def test_substantive_answer_with_no_citations_fails_grounding():
    generation = GenerationResult(draft_text="This is a fairly long and detailed answer with no sources cited at all.", mode="answer", refused=False)
    result = validate(generation, TICKET)
    assert result.passed is False
    assert "grounding" in result.blocked_reason


def test_empty_draft_fails_tone_check():
    generation = GenerationResult(draft_text="   ", mode="answer", refused=True)
    result = validate(generation, TICKET)
    assert result.passed is False


def test_clean_grounded_answer_passes():
    from src.schemas import Citation

    generation = GenerationResult(
        draft_text="You can export data via the export API as described in our docs.",
        citations=[Citation(claim_span="export API", doc_id="DOC-1", chunk_id="DOC-1::a")],
        mode="answer",
        refused=False,
    )
    result = validate(generation, TICKET)
    assert result.passed is True
    assert result.blocked_reason is None
