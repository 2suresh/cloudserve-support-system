from src import config
from src.schemas import ClassificationResult, RetrievedPassage, RoutingDecision


def route(
    classification: ClassificationResult,
    retrieved: list[RetrievedPassage],
    threshold: float = config.CONFIDENCE_THRESHOLD,
) -> RoutingDecision:
    """Deterministic: same (classification, retrieved, threshold) always yields
    the same decision (A5). Checked in this order — no confidence score
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
