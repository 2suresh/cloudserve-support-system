"""One-off (or re-run with --force) build of the Chroma index from the
documentation corpus. The Retriever also builds this automatically on first
use if it's missing, so this script is a convenience, not a required step."""

import argparse
from pathlib import Path

from src import config
from src.retrieve import build_index


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--documentation", type=Path, default=config.BASE_DIR / "data" / "documentation.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    count = build_index(args.documentation, force=args.force)
    print(f"indexed {count} chunks from {args.documentation}")


if __name__ == "__main__":
    main()
