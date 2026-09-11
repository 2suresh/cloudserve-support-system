import re

from src import config
from src.schemas import ClassificationResult, RetrievedPassage, RoutingDecision

# Defense in depth for the policy-excluded intents (Brief §07's zero-tolerance framing):
# a confirmed real bug (7/26 security_incident tickets auto-sent, all at 0.95 confidence,
# because the classifier called them api_key_issue/account_access instead) showed that
# relying on the classifier alone for a zero-tolerance policy is "a hope, not a control".
# Each entry is a set of words that must ALL appear (any order, case-insensitive) in the
# ticket body for the safety net to fire, independent of what the classifier said.
_SECURITY_INCIDENT_SAFETY_NET: list[set[str]] = [
    {"breach"}, {"compromised"}, {"unauthorized", "access"}, {"hacked"}, {"leaked"},
    {"former", "employee", "access"},
]


def _security_incident_safety_net_triggered(ticket_body: str) -> bool:
    words = set(re.findall(r"[a-z]+", ticket_body.lower()))
    return any(trigger.issubset(words) for trigger in _SECURITY_INCIDENT_SAFETY_NET)


def route(
    classification: ClassificationResult,
    retrieved: list[RetrievedPassage],
    ticket_body: str = "",
    threshold: float = config.CONFIDENCE_THRESHOLD,
) -> RoutingDecision:
    """Deterministic: same (classification, retrieved, ticket_body, threshold) always
    yields the same decision (A5). Checked in this order — no confidence score
    justifies auto-answering a policy-excluded ticket, and no grounding means
    there is nothing to answer from (System_Architecture.md §3.4, Figure 4)."""
    if not retrieved:
        return RoutingDecision(action="escalate", reason="no retrieval passage cleared the relevance threshold", threshold_used=threshold)

    if classification.intent in config.POLICY_EXCLUDED_INTENTS:
        return RoutingDecision(
            action="escalate",
            reason=f"intent '{classification.intent}' is policy-excluded from automation",
            threshold_used=threshold,
        )

    if _security_incident_safety_net_triggered(ticket_body):
        return RoutingDecision(
            action="escalate",
            reason=(
                f"classified as '{classification.intent}', but the ticket text matches a "
                "security-incident safety-net pattern -- escalating regardless of classification"
            ),
            threshold_used=threshold,
        )

    if classification.confidence < threshold:
        return RoutingDecision(
            action="escalate",
            reason=f"confidence {classification.confidence:.2f} below threshold {threshold:.2f}",
            threshold_used=threshold,
        )

    return RoutingDecision(
        action="auto_respond",
        reason=f"confidence {classification.confidence:.2f} >= threshold {threshold:.2f}, grounded, not policy-excluded",
        threshold_used=threshold,
    )
