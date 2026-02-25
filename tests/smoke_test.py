"""
Very small smoke test exercising the Node → JSON → Python accessibility flow.

This script assumes that:
- Node.js is installed,
 - The js-runner subproject has had its dependencies installed:
   (cd js-runner && npm install)
 - The Node runner can reach https://example.com.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from playwrite_distiller.distiller import run_accessibility_distillation_sync


def main() -> None:
  project_root = Path(__file__).resolve().parents[1]
  js_runner_dir = project_root / "js-runner"
  runner_script = js_runner_dir / "aria-snapshot-runner.mjs"

  artifacts_dir = project_root / "artifacts" / "aria-snapshots"
  artifacts_dir.mkdir(parents=True, exist_ok=True)
  snapshot_path = artifacts_dir / "smoke-test-example-com.json"

  env = os.environ.copy()
  env["TARGET_URL"] = "https://example.com"
  env["SNAPSHOT_PATH"] = str(snapshot_path)

  completed = subprocess.run(
      ["node", str(runner_script)],
      cwd=str(js_runner_dir),
      env=env,
      check=False,
      capture_output=True,
      text=True,
  )

  if completed.returncode != 0:
      message = completed.stderr.strip() or completed.stdout.strip()
      raise SystemExit(f"Node runner failed: {message}")

  print(f"Snapshot written to: {snapshot_path}")

  result = run_accessibility_distillation_sync(snapshot_path=str(snapshot_path))
  print("Distiller result JSON:")
  print(
      json.dumps(
          {
              "url": result.url,
              "stats": {
                  "total_nodes": result.stats.total_nodes,
                  "interactive_nodes": result.stats.interactive_nodes,
                  "unnamed_interactive_nodes": result.stats.unnamed_interactive_nodes,
                  "unnamed_interactive_ratio": result.stats.unnamed_interactive_ratio,
              },
              "suggestion_report": {
                  "summary": result.suggestion_report.summary,
                  "severity": result.suggestion_report.severity.value,
              },
          },
          indent=2,
      )
  )


if __name__ == "__main__":
  main()
