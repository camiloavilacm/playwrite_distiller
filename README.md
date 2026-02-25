## playwrite-distiller

Deterministic accessibility "distiller" that analyzes Playwright accessibility
snapshots and produces a small, JSON-friendly report suitable for CI gating and
downstream AI analysis.

### High-level flow

- **Node / Playwright (collection)**:
  - `js-runner/aria-snapshot-runner.mjs` launches Chromium with Playwright.
  - It navigates to a target URL, captures the accessibility tree via
    `page.accessibility.snapshot()`, and writes a normalized JSON file:
    - `root`: accessibility tree (role / name / children)
    - `url`, `pageTitle`, `capturedAt`
    - `metadata`: runner + timeout information

- **Python distiller (analysis)**:
  - `src/playwrite_distiller/distiller.py` loads the JSON snapshot and computes:
    - Aggregate stats: total nodes, interactive nodes, unnamed interactive nodes.
    - Simple health checks with a structured `SuggestionReport`.
  - The main entrypoints are:
    - `run_accessibility_distillation(...)`
    - `run_accessibility_distillation_sync(...)`

### Running the Node snapshot runner

From the project root:

```bash
cd js-runner
npm install

# Capture an accessibility snapshot for a URL
TARGET_URL="https://example.com" npm run aria-snapshot
```

By default, snapshots are written under:

- `artifacts/aria-snapshots/snapshot-<timestamp>.json` (relative to the project root)

You can override the output path with:

```bash
TARGET_URL="https://example.com" SNAPSHOT_PATH="/tmp/example-aria.json" npm run aria-snapshot
```

### Running the Python distiller against a snapshot

Once you have a snapshot JSON file:

```bash
python -m playwrite_distiller --snapshot-path artifacts/aria-snapshots/snapshot-xxxx.json
```

This prints a JSON payload like:

```json
{
  "status": "ok",
  "result": {
    "url": "https://example.com",
    "stats": {
      "total_nodes": 42,
      "interactive_nodes": 10,
      "unnamed_interactive_nodes": 1,
      "unnamed_interactive_ratio": 0.1
    },
    "suggestion_report": {
      "summary": "...",
      "severity": "low",
      "issues": []
    },
    "metadata": {
      "implementation": "aria_snapshot_json",
      "runner": "node-playwright",
      "timeout_ms": 30000
    }
  }
}
```

### Orchestrating Node + Python from the CLI

You can also let the Python CLI invoke the Node runner for you:

```bash
python -m playwrite_distiller \
  --url https://example.com \
  --use-node-runner
```

This will:

- Run the Node runner under `js-runner/` to generate a snapshot JSON file.
- Feed that snapshot into the Python distiller.
- Emit the usual structured JSON report (and non-zero exit code on failure).

### Legacy direct Playwright mode

If you call the distiller without `--snapshot-path` and without
`--use-node-runner`, it will attempt to use the Python Playwright bindings to
call `page.accessibility.snapshot()` directly. This mode is considered
**best-effort only**, is kept for developer convenience, and may not work in
all CI environments.

