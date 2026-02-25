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
import sys
from dataclasses import asdict

from .distiller import run_accessibility_distillation_sync
from .exceptions import InaccessibleWebpageError


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
    try:
        result = run_accessibility_distillation_sync(
            url=args.url,
            timeout_ms=args.timeout_ms,
        )
    except InaccessibleWebpageError as exc:
        # Structured JSON error output for CI and tooling.
        payload = {
            "status": "error",
            "error_type": "InaccessibleWebpageError",
            "message": exc.message,
            "stats": asdict(exc.stats) if exc.stats is not None else None,
            "suggestion_report": (
                asdict(exc.suggestion_report)
                if exc.suggestion_report is not None
                else None
            ),
        }
        print(json.dumps(payload, indent=2))
        sys.exit(1)

    # DistilledResult is a dataclass containing other dataclasses,
    # so asdict() gives us a JSON-serializable structure.
    payload = {
        "status": "ok",
        "result": asdict(result),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

