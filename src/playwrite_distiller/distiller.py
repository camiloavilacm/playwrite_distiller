"""
Accessibility distiller entrypoints.

Primary usage:
- Consume an ARIA accessibility snapshot JSON file produced by an external
  runner (for example, Playwright Test using ARIA snapshot helpers).
- Derive basic AccessibilityStats from the snapshot (step 6a).
- Apply simple health checks and raise InaccessibleWebpageError for clearly
  invalid pages (step 6b).

Legacy / best-effort mode:
- When no snapshot file is provided, the distiller still attempts to launch
  Playwright directly and call page.accessibility.snapshot(). This path is
  kept for developer convenience only and may not work in all environments.
"""

from __future__ import annotations

import asyncio
import logging
import json
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .exceptions import InaccessibleWebpageError
from .types import (
    AccessibilityStats,
    DistilledResult,
    SeverityLevel,
    SuggestionReport,
)


LOGGER = logging.getLogger(__name__)

# Very small, explicit thresholds for early health checks.
MIN_TOTAL_NODES = 3
MAX_UNNAMED_INTERACTIVE_RATIO = 0.5

# A conservative first pass at "interactive" roles for basic stats.
INTERACTIVE_ROLES = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "combobox",
    "checkbox",
    "radio",
    "switch",
    "slider",
    "tab",
    "tablist",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "spinbutton",
    "treeitem",
}


def _load_aria_snapshot_from_file(
    snapshot_path: str,
) -> Tuple[Any | None, Mapping[str, Any]]:
    """
    Load an ARIA accessibility snapshot from a JSON file.

    The expected primary shape is a dict with a ``root`` key containing the
    accessibility tree and optional metadata fields such as ``url`` or
    ``capturedAt``. If no ``root`` key is present, the entire JSON document
    is treated as the accessibility tree.
    """

    path = Path(snapshot_path)
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict) and "root" in raw:
        tree = raw.get("root")
        metadata: Dict[str, Any] = {
            key: value for key, value in raw.items() if key != "root"
        }
    else:
        tree = raw
        metadata = {}

    return tree, metadata


def _compute_accessibility_stats(tree: Any | None) -> AccessibilityStats:
    """
    Traverse the ARIA snapshot (YAML-parsed dict/list/str) to derive stats.
    Compatible with modern Playwright aria_snapshot() outputs.
    """
    if isinstance(tree, str):
        try:
            # Converts the YAML string into a Python object structure
            tree = yaml.safe_load(tree)
        except Exception as exc:
            LOGGER.error("Failed to parse ARIA YAML: %s", exc)
            tree = None

    if not tree:
        return AccessibilityStats(
            total_nodes=0,
            interactive_nodes=0,
            unnamed_interactive_nodes=0,
            unnamed_interactive_ratio=0.0,
        )

    def _walk(node: Any) -> Tuple[int, int, int]:
        total = 0
        interactive = 0
        unnamed_interactive = 0

        # Case 1: Dictionary - Key is usually the 'Role "Name"'
        if isinstance(node, dict):
            total += 1
            for key, value in node.items():
                # Extract the role (e.g., 'button "Submit"' -> 'button')
                role_name = key.split()[0] if isinstance(key, str) else ""
                
                if role_name in INTERACTIVE_ROLES:
                    interactive = 1
                    # In YAML, if there's no name, the value is often an empty list or None
                    # If the key is just 'button' without a quoted name, check the value
                    has_name = '"' in key or (isinstance(value, str) and value.strip())
                    if not has_name:
                        unnamed_interactive = 1

                # Recursively walk children (the value of the dict)
                c_total, c_inter, c_unnamed = _walk(value)
                total += c_total
                interactive += c_inter
                unnamed_interactive += c_unnamed

        # Case 2: List - Represents a collection of sibling nodes
        elif isinstance(node, list):
            for item in node:
                c_total, c_inter, c_unnamed = _walk(item)
                total += c_total
                interactive += c_inter
                unnamed_interactive += c_unnamed

        # Case 3: String - Usually a text node or a simplified leaf node
        elif isinstance(node, str):
            total += 1
            # Check if the string itself represents a role (e.g., "- button")
            role_name = node.split()[0]
            if role_name in INTERACTIVE_ROLES:
                interactive = 1
                if '"' not in node: # No quoted name found in the string
                    unnamed_interactive = 1

        return total, interactive, unnamed_interactive

    total_nodes, interactive_nodes, unnamed_interactive_nodes = _walk(tree)

    unnamed_ratio = (
        unnamed_interactive_nodes / interactive_nodes if interactive_nodes else 0.0
    )

    return AccessibilityStats(
        total_nodes=total_nodes,
        interactive_nodes=interactive_nodes,
        unnamed_interactive_nodes=unnamed_interactive_nodes,
        unnamed_interactive_ratio=unnamed_ratio,
    )

def _run_health_checks(
    stats: AccessibilityStats,
    url: str,
) -> bool:
    """
    Apply simple, deterministic health checks.

    Step 6b keeps this intentionally small:
    - Empty / trivial trees (very few nodes) are treated as problematic.
    - Extreme unnamed interactive ratio is also treated as failure.
    For now, empty / trivial trees are logged as a warning (partial
    analysis) instead of a hard failure, to better support restricted
    environments where the accessibility API is unavailable.
    """

    # Trivial tree: effectively nothing in the accessibility snapshot.
    if stats.total_nodes < MIN_TOTAL_NODES:
        LOGGER.warning(
            "Minimal accessibility tree detected for %r "
            "(total_nodes=%d). Treating analysis as partial.",
            url,
            stats.total_nodes,
        )
        return False

    # Many unnamed interactive elements: fail fast for now.
    if (
        stats.interactive_nodes > 0
        and stats.unnamed_interactive_ratio > MAX_UNNAMED_INTERACTIVE_RATIO
    ):
        raise InaccessibleWebpageError(
            message=(
                f"Too many unnamed interactive elements on {url!r} "
                f"(ratio={stats.unnamed_interactive_ratio:.2f})."
            ),
            stats=stats,
            suggestion_report=SuggestionReport(
                summary=(
                    "A large proportion of interactive controls (links, buttons, "
                    "inputs) appear without accessible names. Add aria-label, "
                    "aria-labelledby, or visible text labels as appropriate."
                ),
                severity=SeverityLevel.HIGH,
                issues=[],
            ),
        )

    return True


async def run_accessibility_distillation(
    url: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    timeout_ms: int = 30_000,
) -> DistilledResult:
    """
    Core async API for running the accessibility distiller.

    Primary (recommended) mode:
    - Provide ``snapshot_path`` pointing at an ARIA snapshot JSON file.
      The file is loaded and used as the source of truth for the
      accessibility tree.

    Legacy / best-effort mode:
    - When ``snapshot_path`` is omitted, the distiller will try to launch
      Playwright and call ``page.accessibility.snapshot()``. This path is
      primarily for developer convenience and may not work in all CI
      environments.
    """

    # Preferred path: consume an ARIA snapshot JSON file.
    if snapshot_path is not None:
        accessibility_tree, snapshot_metadata = _load_aria_snapshot_from_file(
            snapshot_path=snapshot_path
        )

        # Prefer an explicit URL argument, then any URL found in the snapshot
        # metadata, and finally fall back to a generic placeholder.
        effective_url = url or str(snapshot_metadata.get("url") or "about:blank")

        # Derive statistics and health checks from the loaded tree.
        stats: AccessibilityStats = _compute_accessibility_stats(accessibility_tree)
        passed_checks = _run_health_checks(stats=stats, url=effective_url)

        if passed_checks:
            summary = (
                "Accessibility analysis completed from ARIA snapshot and "
                "basic health checks passed."
            )
            severity = SeverityLevel.LOW
        else:
            summary = (
                "Accessibility analysis completed from ARIA snapshot, but the "
                "accessibility tree appears minimal or incomplete. Treat these "
                "results as partial."
            )
            severity = SeverityLevel.MEDIUM

        suggestion_report: SuggestionReport = SuggestionReport(
            summary=summary,
            severity=severity,
            issues=[],
        )

        metadata: Dict[str, Any] = {
            "implementation": "aria_snapshot_json",
            "version": "0.1.0",
        }
        # Merge any metadata that came from the snapshot document itself.
        metadata.update(snapshot_metadata)

        return DistilledResult(
            url=effective_url,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            timeout_ms=timeout_ms,
            stats=stats,
            suggestion_report=suggestion_report,
            accessibility_tree=accessibility_tree,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Legacy path: fall back to calling page.accessibility.snapshot()
    # directly from Python Playwright, primarily for local development.
    # ------------------------------------------------------------------

    LOGGER.info(
        "No snapshot_path provided; falling back to direct Playwright "
        "navigation and page.accessibility.snapshot(). This mode is "
        "deprecated and may not be supported in all environments."
    )

    effective_url = url or "https://demoqa.com/"

    accessibility_tree: Any | None = None
    # Guard against environments where Playwright is not installed.
    try:
        from playwright.async_api import async_playwright  # type: ignore[import]
    except Exception:  # pragma: no cover - defensive
        LOGGER.warning(
            "playwright.async_api is not available; cannot capture "
            "accessibility snapshot directly. Returning a partial analysis "
            "with an empty accessibility tree."
        )
        stats = _compute_accessibility_stats(None)
        passed_checks = _run_health_checks(stats=stats, url=effective_url)

        if passed_checks:
            summary = (
                "Accessibility analysis completed without a direct snapshot; "
                "treat results as best-effort only."
            )
            severity = SeverityLevel.MEDIUM
        else:
            summary = (
                "Accessibility analysis completed without a direct snapshot, "
                "but the accessibility tree appears minimal or incomplete. "
                "Treat these results as partial."
            )
            severity = SeverityLevel.MEDIUM

        suggestion_report = SuggestionReport(
            summary=summary,
            severity=severity,
            issues=[],
        )

        return DistilledResult(
            url=effective_url,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            timeout_ms=timeout_ms,
            stats=stats,
            suggestion_report=suggestion_report,
            accessibility_tree=None,
            metadata={
                "implementation": "playwright_direct_snapshot_unavailable",
                "version": "0.1.0",
            },
        )

    async with async_playwright() as p:  # type: ignore[misc]
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(effective_url, timeout=timeout_ms)
        body = page.locator("body")
        if hasattr(body, "aria_snapshot"):
            try:
                # This returns a YAML string
                accessibility_tree = await body.aria_snapshot()
            except Exception as exc:
                LOGGER.warning("Failed to capture aria_snapshot: %s", exc)
        else:
            LOGGER.error("Environment version too old for aria_snapshot.")
            
        await browser.close()

    # Derive statistics and apply health checks using the captured tree.
    stats = _compute_accessibility_stats(accessibility_tree)
    passed_checks = _run_health_checks(stats=stats, url=effective_url)

    if passed_checks:
        summary = (
            "Accessibility analysis completed from direct Playwright snapshot "
            "and basic health checks passed."
        )
        severity = SeverityLevel.LOW
    else:
        summary = (
            "Accessibility analysis completed from direct Playwright snapshot, "
            "but the accessibility tree appears minimal or incomplete. Treat "
            "these results as partial."
        )
        severity = SeverityLevel.MEDIUM

    suggestion_report = SuggestionReport(
        summary=summary,
        severity=severity,
        issues=[],
    )

    return DistilledResult(
        url=effective_url,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        timeout_ms=timeout_ms,
        stats=stats,
        suggestion_report=suggestion_report,
        accessibility_tree=accessibility_tree,
        metadata={
            "implementation": "playwright_direct_snapshot",
            "version": "0.1.0",
        },
    )


def run_accessibility_distillation_sync(
    url: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    timeout_ms: int = 30_000,
) -> DistilledResult:
    """
    Synchronous wrapper around the async distiller.

    This is convenient for simple CLI or CI entrypoints that do not want
    to manage an event loop directly.
    """

    try:
        return asyncio.run(
            run_accessibility_distillation(
                url=url,
                snapshot_path=snapshot_path,
                timeout_ms=timeout_ms,
            )
        )
    except InaccessibleWebpageError:
        # Re-raise unchanged for callers that specifically want to catch it.
        raise

