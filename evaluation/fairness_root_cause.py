"""Root-causes a fairness_audit.py spread: is it explained by which intents a
group happens to ask about (a sampling confound), or is there a residual gap
beyond that? This is the method that found the region gap was explainable
and fixable (System_Architecture.md, Stage 5 revision log), and the same
method applied to the tier gap that replaced it -- reusable rather than
re-derived ad hoc each time.

For each group in --dimension: computes observed accuracy, and an "expected"
accuracy as if that group's intent mix were classified at the *global*
per-intent accuracy rate. The difference is the residual -- the part not
explained by intent mix alone.

For the worst-residual group, also reports each expected-intent involved in
its errors alongside that intent's confusion rate *dataset-wide* (not just
within this group) -- the group's own error count is usually too small to
judge a pattern from directly (a 2-of-18 tally proves nothing), but if the
intents driving a group's errors are also globally confusable, that is the
same signal the original 4-pair fix was found from, just applied here rather
than re-derived by eye. A group whose errors land on intents with no strong
global confusion partner is more likely small-sample noise than a fixable
pattern -- this script says which case it's in, but does not pick a fix.

    python -m evaluation.fairness_root_cause \\
        --results evaluation/results/full_dev_run_v3/results.jsonl \\
        --tickets data/development_tickets.json \\
        --dimension customer_tier \\
        --output evaluation/results/full_dev_run_v3/root_cause_customer_tier.json
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

DOMINANT_THRESHOLD = 0.4  # matches the 4 pairs the original disambiguation fix targeted (52-65%)
MIN_GLOBAL_SUPPORT = 5  # a "100% confusion rate" from 1 dataset-wide error is a fluke, not a pattern


def _load_results(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            if "ticket_id" in row and row.get("expected_intent"):
                rows.append(row)
    return rows


def run(results_path: Path, tickets_path: Path, dimension: str, top_intents: int = 6) -> dict:
    results = _load_results(results_path)
    tickets_by_id = {t["ticket_id"]: t for t in json.loads(tickets_path.read_text())}
    for row in results:
        row[dimension] = tickets_by_id.get(row["ticket_id"], {}).get(dimension)

    # global (dataset-wide, every group) per-intent accuracy and top confusion partner
    intent_correct, intent_total = Counter(), Counter()
    intent_confusions = defaultdict(Counter)  # expected_intent -> Counter(predicted_intent)
    for r in results:
        exp, pred = r["expected_intent"], r["classification"]["intent"]
        intent_total[exp] += 1
        if pred == exp:
            intent_correct[exp] += 1
        else:
            intent_confusions[exp][pred] += 1
    global_acc = {i: intent_correct[i] / intent_total[i] for i in intent_total}

    global_top_confusion = {}
    for intent, confusions in intent_confusions.items():
        total_errors = sum(confusions.values())
        top_pred, top_count = confusions.most_common(1)[0]
        global_top_confusion[intent] = {
            "predicted_as": top_pred, "share_of_this_intents_errors": round(top_count / total_errors, 3),
            "total_errors_dataset_wide": total_errors,
        }

    by_group = defaultdict(list)
    for r in results:
        by_group[r.get(dimension) or "(missing)"].append(r)

    groups = {}
    for group, rows in by_group.items():
        n = len(rows)
        observed = sum(1 for r in rows if r["classification"]["intent"] == r["expected_intent"]) / n
        expected = sum(global_acc[r["expected_intent"]] for r in rows) / n
        groups[group] = {"n": n, "observed_accuracy": round(observed, 4), "expected_from_intent_mix": round(expected, 4),
                          "residual": round(observed - expected, 4)}

    worst_group = min(groups, key=lambda g: groups[g]["residual"])
    worst_rows = by_group[worst_group]

    # which expected-intents drive this group's errors, and are those intents globally confusable?
    group_error_intents = Counter(
        r["expected_intent"] for r in worst_rows if r["classification"]["intent"] != r["expected_intent"]
    )
    intent_breakdown = []
    for intent, group_error_count in group_error_intents.most_common(top_intents):
        g = global_top_confusion.get(intent)
        intent_breakdown.append({
            "expected_intent": intent,
            "errors_in_this_group": group_error_count,
            "global_top_confusion_partner": g["predicted_as"] if g else None,
            "global_confusion_rate_for_this_intent": g["share_of_this_intents_errors"] if g else None,
            "global_support": g["total_errors_dataset_wide"] if g else 0,
        })

    any_dominant = any(
        (b["global_confusion_rate_for_this_intent"] or 0) >= DOMINANT_THRESHOLD
        and b["global_support"] >= MIN_GLOBAL_SUPPORT
        for b in intent_breakdown
    )

    return {
        "dimension": dimension,
        "groups": groups,
        "worst_group": worst_group,
        "worst_group_error_count": sum(group_error_intents.values()),
        "worst_group_intent_breakdown": intent_breakdown,
        "likely_fixable_pattern_found": any_dominant,
        "note": (
            "at least one expected-intent driving this group's errors also has a strong, "
            f"well-supported global confusion partner (>= {DOMINANT_THRESHOLD:.0%} of that intent's "
            f"errors dataset-wide, from >= {MIN_GLOBAL_SUPPORT} dataset-wide errors, not a fluke from "
            "1-2 cases) -- worth a targeted disambiguation rule the same way the original 4-pair fix "
            "was found"
            if any_dominant else
            f"no intent driving this group's errors has a confusion partner that is both >= "
            f"{DOMINANT_THRESHOLD:.0%} dataset-wide and backed by >= {MIN_GLOBAL_SUPPORT} dataset-wide "
            f"errors -- this group's own error count is small ({sum(group_error_intents.values())}), "
            "so a targeted rule here risks fitting noise rather than a real mechanism; more data "
            "before concluding this is fixable"
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--tickets", required=True, type=Path)
    parser.add_argument("--dimension", required=True, choices=["customer_tier", "customer_region", "language_fluency"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = run(args.results, args.tickets, args.dimension)

    print(f"{args.dimension}:\n")
    for group, stats in report["groups"].items():
        print(f"  {group:>15}  n={stats['n']:<4} observed={stats['observed_accuracy']:.3f}  "
              f"expected_from_mix={stats['expected_from_intent_mix']:.3f}  residual={stats['residual']:+.3f}")
    print(f"\nworst group: {report['worst_group']} ({report['worst_group_error_count']} errors)")
    print(f"{'expected intent':>25} {'errors here':>12} {'global top confusion':>22} {'global rate':>12} {'global n':>9}")
    for b in report["worst_group_intent_breakdown"]:
        rate = f"{b['global_confusion_rate_for_this_intent']:.0%}" if b['global_confusion_rate_for_this_intent'] is not None else "n/a"
        print(f"{b['expected_intent']:>25} {b['errors_in_this_group']:>12} {str(b['global_top_confusion_partner']):>22} {rate:>12} {b['global_support']:>9}")
    print(f"\nlikely fixable pattern found: {report['likely_fixable_pattern_found']}")
    print(f"note: {report['note']}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(f"\nfull report written to {args.output}")


if __name__ == "__main__":
    main()
