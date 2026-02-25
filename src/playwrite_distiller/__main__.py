"""
Command-line entrypoint for the playwrite_distiller package.

Usage (from the project root, with the venv active):

    python -m playwrite_distiller --url https://demoqa.com/ --timeout-ms 30000

For now this just runs the stub distiller and prints the DistilledResult
as JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .distiller import run_accessibility_distillation_sync


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Playwright accessibility distiller."
    )
    parser.add_argument(
        "--url",
        type=str,
        help="Target URL to analyze (default: https://demoqa.com/).",
        default=None,
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        help="Navigation timeout in milliseconds.",
        default=30_000,
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = run_accessibility_distillation_sync(
        url=args.url,
        timeout_ms=args.timeout_ms,
    )
    # DistilledResult is a dataclass containing other dataclasses,
    # so asdict() gives us a JSON-serializable structure.
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()

