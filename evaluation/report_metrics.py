"""Computes the metrics report defined in Build Specification §04, purely from
this run's own results and decision log — nothing here is calculated by hand."""

import statistics
from collections import Counter, defaultdict


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))
    return ordered[idx]


def compute_report(results: list[dict], errors: list[dict], decisions_logged: int) -> dict:
    total = len(results) + len(errors)
    latencies = [r["latency_ms"] for r in results]
    confidences = [r["classification"]["confidence"] for r in results]

    sent = sum(1 for r in results if r["final_action"] == "sent_to_customer")
    escalated = sum(1 for r in results if r["final_action"] == "escalated")
    blocked = sum(1 for r in results if not r["validation"]["passed"])

    retrieval_hits = sum(1 for r in results if r["retrieved"])

    guardrail_counts = Counter()
    private_data_hits = 0
    for r in results:
        for check in r["validation"]["checks_run"]:
            if not check["passed"]:
                guardrail_counts[check["name"]] += 1
                if check["name"] == "private_data":
                    private_data_hits += 1

    class_correct, class_seen = defaultdict(int), defaultdict(int)
    class_predicted = defaultdict(int)
    has_labels = any(r.get("expected_intent") for r in results)
    if has_labels:
        for r in results:
            expected = r.get("expected_intent")
            predicted = r["classification"]["intent"]
            if expected:
                class_seen[expected] += 1
                class_predicted[predicted] += 1
                if predicted == expected:
                    class_correct[expected] += 1

    precision_recall = {}
    if has_labels:
        for cls in set(list(class_seen) + list(class_predicted)):
            tp = class_correct[cls]
            precision = tp / class_predicted[cls] if class_predicted[cls] else 0.0
            recall = tp / class_seen[cls] if class_seen[cls] else 0.0
            precision_recall[cls] = {"precision": round(precision, 3), "recall": round(recall, 3), "support": class_seen[cls]}

    return {
        "volume": {
            "tickets_processed": total,
            "answered_automatically": sent,
            "escalated": escalated,
            "blocked_by_guardrails": blocked,
            "processing_errors": len(errors),
        },
        "business": {
            "first_contact_resolution": round(sent / total, 4) if total else 0.0,
            "escalation_rate": round(escalated / total, 4) if total else 0.0,
            "mean_response_time_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "median_response_time_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        },
        "technical": {
            "classification_precision_recall_by_class": precision_recall,
            "retrieval_hit_rate": round(retrieval_hits / total, 4) if total else 0.0,
            "latency_ms_median": round(_percentile(latencies, 50), 2),
            "latency_ms_p95": round(_percentile(latencies, 95), 2),
            "mean_classification_confidence": round(statistics.mean(confidences), 4) if confidences else 0.0,
        },
        "governance": {
            "decisions_logged": decisions_logged,
            "guardrail_activations_by_type": dict(guardrail_counts),
            "private_data_detections": private_data_hits,
        },
    }
