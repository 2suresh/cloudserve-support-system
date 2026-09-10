"""Unattended full-set evaluation run (Build Specification A9/A10).

    python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results/

Takes an input path and output path as arguments rather than a hardcoded
filename, because the final assessment points this at a hidden file this
harness has never seen (Build Spec §04).
"""

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path

from src.graph import run_pipeline

from evaluation.report_metrics import compute_report

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cloudserve.harness")


def run(input_path: Path, output_path: Path) -> dict:
    tickets = json.loads(input_path.read_text())
    if not isinstance(tickets, list):
        raise ValueError("input file must contain a JSON array of tickets")

    output_path.mkdir(parents=True, exist_ok=True)
    results_file = output_path / "results.jsonl"

    results, errors = [], []
    t_start = time.time()

    with results_file.open("w") as f:
        for i, raw_ticket in enumerate(tickets, start=1):
            ticket_id = raw_ticket.get("ticket_id", f"UNKNOWN-{i}")
            try:
                result = run_pipeline(raw_ticket)
                labels = raw_ticket.get("labels") or {}
                result["expected_intent"] = labels.get("intent")
                result["expected_route"] = labels.get("expected_route")
                results.append(result)
                f.write(json.dumps(result) + "\n")
            except Exception as exc:  # a ticket that misbehaves is recorded, never dropped (A9, Build Spec §08)
                logger.error("ticket %s failed: %s\n%s", ticket_id, exc, traceback.format_exc())
                error_row = {"ticket_id": ticket_id, "error": str(exc)}
                errors.append(error_row)
                f.write(json.dumps(error_row) + "\n")

            if i % 25 == 0 or i == len(tickets):
                logger.info("processed %s/%s tickets", i, len(tickets))

    elapsed_s = time.time() - t_start
    # Counted from this run's own results, not looked up by ticket_id in the decision
    # log — a DB lookup would double-count whenever a ticket_id repeats across separate
    # runs (which happens in normal use: reprocessing the same file twice, or another
    # test run touching the same IDs).
    decisions_logged = sum(r["log_entries_written"] for r in results)

    report = compute_report(results, errors, decisions_logged)
    report["run_metadata"] = {
        "input_file": str(input_path),
        "total_tickets_in_file": len(tickets),
        "elapsed_seconds": round(elapsed_s, 2),
    }

    (output_path / "metrics_report.json").write_text(json.dumps(report, indent=2))
    logger.info("run complete in %.1fs — report written to %s", elapsed_s, output_path / "metrics_report.json")
    return report


def main():
    parser = argparse.ArgumentParser(description="Run the full evaluation harness, unattended.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    report = run(args.input, args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
