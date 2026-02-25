"""
Command-line entrypoint for the playwrite_distiller package.

Primary modes:

- Snapshot analysis (recommended for CI):
    python -m playwrite_distiller --snapshot-path path/to/snapshot.json

- One-shot collection + analysis (Node runner + Python analyzer):
    python -m playwrite_distiller --url https://demoqa.com/ --use-node-runner

- Legacy direct Playwright mode (best-effort only, may not work everywhere):
    python -m playwrite_distiller --url https://demoqa.com/ --timeout-ms 30000
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

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
        "--snapshot-path",
        type=str,
        help=(
            "Path to a pre-generated accessibility snapshot JSON file. "
            "When provided, the distiller will skip any browser launch and "
            "analyze this snapshot directly."
        ),
        default=None,
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        help="Navigation timeout in milliseconds.",
        default=30_000,
    )
    parser.add_argument(
        "--use-node-runner",
        action="store_true",
        help=(
            "When set (and no --snapshot-path is provided), call the Node-based "
            "Playwright runner to capture an accessibility snapshot before "
            "running analysis. This requires Node, npm, and the js-runner "
            "subproject to be installed (npm install)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    snapshot_path = args.snapshot_path

    # ------------------------------------------------------------------
    # Optionally orchestrate the Node-based snapshot collection.
    # ------------------------------------------------------------------
    if snapshot_path is None and args.use_node_runner and args.url:
        # Compute a deterministic snapshot path under the project root
        # so that subsequent tools (and users) can inspect artifacts.
        project_root = Path(__file__).resolve().parent.parent
        artifacts_dir = project_root / "artifacts" / "aria-snapshots"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        snapshot_path = str(
            artifacts_dir / f"snapshot-cli-{int(__import__('time').time())}.json"
        )

        js_runner_dir = project_root / "js-runner"
        runner_script = js_runner_dir / "aria-snapshot-runner.mjs"

        env = os.environ.copy()
        env["TARGET_URL"] = args.url
        env["SNAPSHOT_PATH"] = snapshot_path
        env["TIMEOUT_MS"] = str(args.timeout_ms)

        try:
            completed = subprocess.run(
                ["node", str(runner_script)],
                cwd=str(js_runner_dir),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            error_payload = {
                "status": "error",
                "error_type": "AriaSnapshotCollectionError",
                "message": (
                    "Failed to execute Node runner. Ensure that Node.js is installed "
                    "and accessible on PATH."
                ),
            }
            print(json.dumps(error_payload, indent=2))
            sys.exit(1)

        if completed.returncode != 0:
            # Try to surface structured JSON from the runner if present.
            message = completed.stderr.strip() or completed.stdout.strip()
            error_payload = {
                "status": "error",
                "error_type": "AriaSnapshotCollectionError",
                "message": message,
            }
            print(json.dumps(error_payload, indent=2))
            sys.exit(1)

    # ------------------------------------------------------------------
    # Run the Python distiller against either a snapshot file or (legacy)
    # via direct Playwright integration.
    # ------------------------------------------------------------------
    try:
        result = run_accessibility_distillation_sync(
            url=args.url,
            snapshot_path=snapshot_path,
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

