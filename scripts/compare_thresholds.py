"""Sweeps candidate confidence thresholds against development_tickets.json to
choose CONFIDENCE_THRESHOLD from data rather than by feel (Brief §05,
System_Architecture.md §7). Never run this against validation_tickets.json —
that would tune against the set meant to check progress independently.

For each threshold, reports: automation rate, how many auto-answered tickets
would have been *wrong* per the labelled expected_route (the number the
governance floor cares about), and overall agreement with expected_route.

    python -m scripts.compare_thresholds
"""

import json

from src import config, ingest
from src.classify import classify
from src.graph import get_retriever
from src.route import route


def main():
    data_path = config.BASE_DIR / "data" / "development_tickets.json"
    tickets = json.loads(data_path.read_text())
    retriever = get_retriever()

    records = []
    for i, raw in enumerate(tickets, 1):
        ticket = ingest.normalize_ticket(raw)
        labels = raw.get("labels") or {}
        expected_route = labels.get("expected_route")
        if not expected_route:
            continue
        classification = classify(ticket)
        retrieved = retriever.retrieve(f"{ticket.subject or ''} {ticket.body}".strip())
        records.append((classification, retrieved, expected_route))
        if i % 50 == 0:
            print(f"classified {i}/{len(tickets)}")

    print(f"\n{'threshold':>9} {'auto_rate':>10} {'wrong_auto':>11} {'agreement':>10}")
    for threshold in [round(0.5 + 0.05 * i, 2) for i in range(11)]:
        auto_count = wrong_auto = agree = 0
        for classification, retrieved, expected in records:
            decision = route(classification, retrieved, threshold=threshold)
            if decision.action == "auto_respond":
                auto_count += 1
                if expected != "auto_respond":
                    wrong_auto += 1
            if decision.action == expected:
                agree += 1
        n = len(records)
        print(f"{threshold:>9} {auto_count / n:>10.2%} {wrong_auto:>11} {agree / n:>10.2%}")


if __name__ == "__main__":
    main()
