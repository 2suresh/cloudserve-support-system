import re

from src.schemas import GenerationResult, GuardrailCheck, Ticket, ValidationResult

_PRIVATE_DATA_PATTERNS = [
    ("api_key", re.compile(r"\b(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("other_customer_id", re.compile(r"\bCUST-\d{3,}\b")),
]


def check_private_data(draft_text: str, ticket: Ticket) -> GuardrailCheck:
    """Zero tolerance (Brief §07 governance condition). Any secret-shaped token,
    card/SSN-shaped number, or a reference to a customer ID other than the
    ticket's own blocks the response."""
    for name, pattern in _PRIVATE_DATA_PATTERNS:
        for match in pattern.finditer(draft_text):
            if name == "other_customer_id" and match.group(0) == (ticket.customer_id or ""):
                continue
            return GuardrailCheck(name="private_data", passed=False, detail=f"matched {name} pattern: {match.group(0)[:4]}***")
    return GuardrailCheck(name="private_data", passed=True)


def check_grounding(generation: GenerationResult) -> GuardrailCheck:
    """Every claim in an auto-respond answer must map to a retrieved source
    (A6). A substantive answer with zero citations is treated as unsupported —
    this is what stops fluent-but-ungrounded text from shipping (Build Spec §08)."""
    if generation.mode != "answer" or generation.refused:
        return GuardrailCheck(name="grounding", passed=True)
    if len(generation.draft_text.strip()) > 40 and not generation.citations:
        return GuardrailCheck(name="grounding", passed=False, detail="substantive answer carries no citations")
    return GuardrailCheck(name="grounding", passed=True)


_BANNED_PHRASES = ("as an ai language model", "i am not able to help you with anything")


def check_tone(generation: GenerationResult) -> GuardrailCheck:
    text = generation.draft_text.strip().lower()
    if not text:
        return GuardrailCheck(name="tone", passed=False, detail="empty response")
    for phrase in _BANNED_PHRASES:
        if phrase in text:
            return GuardrailCheck(name="tone", passed=False, detail=f"contains disallowed phrase: '{phrase}'")
    return GuardrailCheck(name="tone", passed=True)


def validate(generation: GenerationResult, ticket: Ticket) -> ValidationResult:
    checks = [
        check_private_data(generation.draft_text, ticket),
        check_grounding(generation),
        check_tone(generation),
    ]
    failed = next((c for c in checks if not c.passed), None)
    return ValidationResult(
        passed=failed is None,
        checks_run=checks,
        blocked_reason=f"{failed.name}: {failed.detail}" if failed else None,
    )
