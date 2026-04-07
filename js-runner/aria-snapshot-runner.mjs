import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium } from "playwright";

/**
 * Minimal Node runner to capture an accessibility snapshot for a given URL.
 *
 * Contract:
 * - Reads the target URL from process.env.TARGET_URL (required).
 * - Optional process.env.SNAPSHOT_PATH to control the output JSON path.
 * - Optional process.env.TIMEOUT_MS to control navigation timeout (ms).
 *
 * Output JSON structure (consumed by the Python distiller):
 * {
 *   "root": { ... Playwright accessibility.snapshot() tree ... },
 *   "url": "<page URL>",
 *   "pageTitle": "<document.title>",
 *   "capturedAt": "<ISO 8601 UTC timestamp>",
 *   "metadata": {
 *     "runner": "node-playwright",
 *     "timeout_ms": <number>
 *   }
 * }
 */

async function main() {
  const targetUrl = process.env.TARGET_URL;
  if (!targetUrl) {
    console.error(
      JSON.stringify(
        {
          status: "error",
          error_type: "AriaSnapshotCollectionError",
          message: "TARGET_URL environment variable is required.",
        },
        null,
        2,
      ),
    );
    process.exit(1);
  }

  const timeoutMs =
    Number.parseInt(process.env.TIMEOUT_MS ?? "", 10) || 30_000;

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);

  const defaultSnapshotDir = path.resolve(
    __dirname,
    "..",
    "artifacts",
    "aria-snapshots",
  );
  const explicitSnapshotPath = process.env.SNAPSHOT_PATH;

  const snapshotPath =
    explicitSnapshotPath ||
    path.join(
      defaultSnapshotDir,
      `snapshot-${Date.now().toString(36)}.json`,
    );

  const snapshotDir = path.dirname(snapshotPath);

  await mkdir(snapshotDir, { recursive: true });

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({
      ignoreHTTPSErrors: true,
    });

    await page.goto(targetUrl, {
      timeout: timeoutMs,
      waitUntil: "load",
    });

    // Best-effort warm-up for interactive elements.
    try {
      await page.waitForSelector("button, a, input", {
        timeout: 5_000,
      });
    } catch {
      // Non-fatal; continue.
    }

    let accessibilityTree = null;
    if (page.accessibility && page.accessibility.snapshot) {
      try {
        accessibilityTree = await page.accessibility.snapshot();
      } catch (error) {
        // Keep a null tree but report the error in metadata.
        console.warn(
          "Failed to capture accessibility snapshot:",
          String(error),
        );
      }
    }

    let pageTitle = "Unknown";
    try {
      pageTitle = await page.title();
    } catch (error) {
      console.warn("Failed to get page title:", String(error));
    }

    const payload = {
      root: accessibilityTree,
      url: targetUrl,
      pageTitle,
      capturedAt: new Date().toISOString(),
      metadata: {
        runner: "node-playwright",
        timeout_ms: timeoutMs,
      },
    };

    await writeFile(snapshotPath, JSON.stringify(payload, null, 2), "utf8");

    // Print the path for callers that want to discover it dynamically.
    console.log(
      JSON.stringify(
        {
          status: "ok",
          snapshot_path: snapshotPath,
        },
        null,
        2,
      ),
    );
  } catch (error) {
    console.error(
      JSON.stringify(
        {
          status: "error",
          error_type: "AriaSnapshotCollectionError",
          message: String(error),
        },
        null,
        2,
      ),
    );
    process.exit(1);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

main();


