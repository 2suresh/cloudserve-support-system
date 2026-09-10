from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

TICKETS_PROCESSED = Counter("tickets_processed_total", "Tickets processed", ["channel"])
ROUTING_DECISIONS = Counter("routing_decisions_total", "Routing decisions", ["action"])
GUARDRAIL_BLOCKS = Counter("guardrail_blocks_total", "Guardrail activations that blocked a response", ["check"])
CLASSIFICATION_CONFIDENCE = Histogram(
    "classification_confidence", "Distribution of classification confidence scores",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
STAGE_LATENCY = Histogram("stage_latency_seconds", "Per-component latency", ["stage"])
PIPELINE_LATENCY = Histogram("pipeline_latency_seconds", "End-to-end pipeline latency")


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
