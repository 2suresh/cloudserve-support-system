"""Build-time calibration (System_Architecture.md §3.2, §12): calls the real
model over development_tickets.json, bins raw confidence into deciles, and
writes storage/calibration.json mapping each decile to its *observed*
accuracy. classify.py applies this mapping so stated confidence tracks real
accuracy (Brief §07 governance condition) instead of being a raw model score
presented as a probability.

Run once you have a working API key. Costs ~500 model calls — never run this
against validation_tickets.json (Brief §06).

    python -m scripts.calibrate
"""

import json
from collections import defaultdict

from src import config, ingest
from src.classify import classify as run_classify

# A bucket with only one or two tickets in it produces a calibrated value of
# 0.0 or 1.0 purely by chance — that's noise, not a measurement, and it would
# make classify.py *more* wrong than the identity mapping it replaces. Below
# this count, the bucket is left out of the mapping so classify.py's
# `mapping.get(bucket, raw_confidence)` falls back to the raw score instead.
MIN_BUCKET_SAMPLES = 10


def main():
    data_path = config.BASE_DIR / "data" / "development_tickets.json"
    tickets = json.loads(data_path.read_text())

    buckets_correct = defaultdict(int)
    buckets_total = defaultdict(int)

    for i, raw in enumerate(tickets, 1):
        ticket = ingest.normalize_ticket(raw)
        expected_intent = (raw.get("labels") or {}).get("intent")
        if not expected_intent:
            continue
        result = run_classify(ticket)
        bucket = str(min(9, int(result.confidence * 10)))
        buckets_total[bucket] += 1
        if result.intent == expected_intent:
            buckets_correct[bucket] += 1
        if i % 50 == 0:
            print(f"processed {i}/{len(tickets)}")

    print("\nbucket  n  observed_accuracy")
    for b in sorted(buckets_total, key=int):
        n = buckets_total[b]
        acc = buckets_correct[b] / n if n else 0.0
        flag = "" if n >= MIN_BUCKET_SAMPLES else "  <- too few samples, excluded"
        print(f"{b:>6} {n:>3}  {acc:.3f}{flag}")

    mapping = {
        b: round(buckets_correct[b] / buckets_total[b], 3)
        for b in buckets_total
        if buckets_total[b] >= MIN_BUCKET_SAMPLES
    }
    out_path = config.BASE_DIR / "storage" / "calibration.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(mapping, indent=2))
    print(f"\nwrote calibration mapping to {out_path}: {mapping}")
    if not mapping:
        print("no bucket had enough samples — classify.py will use raw (uncalibrated) confidence")


if __name__ == "__main__":
    main()
