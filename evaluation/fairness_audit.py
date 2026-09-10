"""Fairness audit (Brief §08): compares response quality across customer
groups — tier, region, and language fluency — computed from a completed
run's results.jsonl joined back to the input tickets file by ticket_id.

Governance condition (Brief §07): quality must not differ by more than five
percentage points between groups on any metric. This script states its
method and sample size per group, and flags any spread that exceeds that
floor — it does not decide what to do about a flagged gap, that judgement
belongs in the report.

    python -m evaluation.fairness_audit \\
        --results evaluation/results/full_dev_run_v1/results.jsonl \\
        --tickets data/development_tickets.json \\
        --output evaluation/results/full_dev_run_v1/fairness_report.json
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

DIMENSIONS = ["customer_tier", "customer_region", "language_fluency"]
SPREAD_THRESHOLD = 0.05  # five percentage points, Brief §07


def _load_results(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            if "ticket_id" in row and "final_action" in row:  # skip error rows
                rows.append(row)
    return rows


def _group_metrics(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    resolved = sum(1 for r in rows if r["final_action"] == "sent_to_customer")
    guardrail_pass = sum(1 for r in rows if r["validation"]["passed"])
    confidences = [r["classification"]["confidence"] for r in rows]
    accuracy_rows = [r for r in rows if r.get("expected_intent")]
    accuracy = (
        sum(1 for r in accuracy_rows if r["classification"]["intent"] == r["expected_intent"]) / len(accuracy_rows)
        if accuracy_rows else None
    )
    return {
        "n": n,
        "resolution_rate": round(resolved / n, 4),
        "guardrail_pass_rate": round(guardrail_pass / n, 4),
        "mean_confidence": round(statistics.mean(confidences), 4),
        "classification_accuracy": round(accuracy, 4) if accuracy is not None else None,
    }


def run(results_path: Path, tickets_path: Path) -> dict:
    results = _load_results(results_path)
    tickets_by_id = {t["ticket_id"]: t for t in json.loads(tickets_path.read_text())}

    for row in results:
        source = tickets_by_id.get(row["ticket_id"], {})
        for dim in DIMENSIONS:
            row[dim] = source.get(dim)

    report = {"method": "resolution rate, guardrail-pass rate, mean confidence, and classification "
                          "accuracy (where a label exists) computed per group; groups compared by "
                          "max-min spread, flagged when it exceeds the 5-point governance floor",
              "sample_size_total": len(results), "dimensions": {}}

    for dim in DIMENSIONS:
        groups = defaultdict(list)
        for row in results:
            groups[row.get(dim) or "(missing)"].append(row)

        per_group = {name: _group_metrics(rows) for name, rows in groups.items()}
        flags = []
        for metric in ["resolution_rate", "guardrail_pass_rate", "mean_confidence", "classification_accuracy"]:
            values = {name: g[metric] for name, g in per_group.items() if g.get(metric) is not None}
            if len(values) < 2:
                continue
            spread = max(values.values()) - min(values.values())
            if spread > SPREAD_THRESHOLD:
                worst = min(values, key=values.get)
                best = max(values, key=values.get)
                flags.append(
                    f"{metric}: {spread:.3f} spread exceeds 0.05 floor ({worst}={values[worst]:.3f} vs {best}={values[best]:.3f})"
                )

        report["dimensions"][dim] = {"groups": per_group, "flags": flags}

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--tickets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    report = run(args.results, args.tickets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))

    print(f"sample size: {report['sample_size_total']}\n")
    for dim, data in report["dimensions"].items():
        print(f"== {dim} ==")
        for name, g in data["groups"].items():
            print(f"  {name:>12}  n={g['n']:<4} resolution={g.get('resolution_rate')}  "
                  f"guardrail_pass={g.get('guardrail_pass_rate')}  accuracy={g.get('classification_accuracy')}")
        for flag in data["flags"]:
            print(f"  FLAG: {flag}")
        if not data["flags"]:
            print("  no flags (all metrics within 5-point floor)")
        print()

    print(f"full report written to {args.output}")


if __name__ == "__main__":
    main()
