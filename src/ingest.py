import logging
import unicodedata

from src.schemas import Ticket

logger = logging.getLogger("cloudserve.ingest")

VALID_CHANNELS = {"email", "chat", "docs_comment", "forum"}


def _clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text.strip()


def normalize_ticket(raw: dict) -> Ticket:
    """One shared representation regardless of source channel (Brief §04, A2).
    Never raises: missing fields, empty bodies and unusual characters are
    normalised into a valid record rather than rejected (A11)."""
    channel = str(raw.get("channel") or "").strip().lower()
    if channel not in VALID_CHANNELS:
        logger.warning("unrecognised channel %r on ticket %r; defaulting to 'email'", channel, raw.get("ticket_id"))
        channel = "email"

    ticket_id = str(raw.get("ticket_id") or raw.get("id") or "UNKNOWN").strip()
    subject = _clean_text(raw.get("subject")) or None
    body = _clean_text(raw.get("body"))

    return Ticket(
        ticket_id=ticket_id,
        channel=channel,
        subject=subject,
        body=body,
        received_at=raw.get("received_at"),
        customer_id=raw.get("customer_id"),
        customer_tier=raw.get("customer_tier"),
        customer_region=raw.get("customer_region"),
        language_fluency=raw.get("language_fluency"),
        raw_payload=raw,
    )
