"""
Accessibility distiller entrypoints.

Current implementation:
- Navigates to the target URL using Playwright.
- Tries to capture the accessibility snapshot.
- Derives basic AccessibilityStats from the snapshot (step 6a).
- Applies simple health checks and raises InaccessibleWebpageError
  for clearly invalid pages (step 6b).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import asyncio
import logging

from playwright.async_api import async_playwright

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


def _compute_accessibility_stats(tree: Any | None) -> AccessibilityStats:
    """
    Traverse the Playwright accessibility snapshot and derive basic stats.

    The snapshot is a nested dict structure with keys like ``role``,
    ``name`` and ``children``. We treat anything with a role in
    INTERACTIVE_ROLES as an interactive node.
    """

    if not tree:
        return AccessibilityStats(
            total_nodes=0,
            interactive_nodes=0,
            unnamed_interactive_nodes=0,
            unnamed_interactive_ratio=0.0,
        )

    def _walk(node: Dict[str, Any]) -> Tuple[int, int, int]:
        total = 1
        interactive = 0
        unnamed_interactive = 0

        role = node.get("role")
        name = node.get("name")

        if isinstance(role, str) and role in INTERACTIVE_ROLES:
            interactive = 1
            if not name:
                unnamed_interactive = 1

        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                c_total, c_interactive, c_unnamed = _walk(child)
                total += c_total
                interactive += c_interactive
                unnamed_interactive += c_unnamed

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
    timeout_ms: int = 30_000,
) -> DistilledResult:
    """
    Core async API for running the accessibility distiller.

    For now this is a minimal stub that returns a deterministic, hard-coded
    result shape. In future steps this will:
    - Launch Playwright.
    - Capture the accessibility snapshot.
    - Compute AccessibilityStats and SuggestionReport.
    - Raise InaccessibleWebpageError when checks fail.
    """

    effective_url = url or "https://demoqa.com/"

    # Step 4+5: integrate Playwright navigation and (where supported)
    # capture the accessibility snapshot. Health checks will be added
    # in a later step.
    accessibility_tree: Any | None = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(effective_url, timeout=timeout_ms)
        # Warm-up: wait for common interactive elements so we know the
        # UI has rendered, then give the accessibility tree a brief
        # moment to initialize before we snapshot.
        try:
            await page.wait_for_selector("button, a, input", timeout=5_000)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.info(
                "No common interactive elements found within warm-up timeout: %s", exc
            )
        await asyncio.sleep(0.5)

        # Minimal snapshot capture; later we can tweak options such as
        # interesting_only or root if needed. Some environments or
        # older Playwright versions may not expose page.accessibility,
        # so we guard this call to keep the distiller robust.
        if hasattr(page, "accessibility"):
            try:
                accessibility_tree = await page.accessibility.snapshot()
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Failed to capture accessibility snapshot: %s", exc)
        else:
            LOGGER.info(
                "Playwright Page has no 'accessibility' attribute; "
                "skipping accessibility tree snapshot."
            )
        await browser.close()

    # Step 6a: derive basic statistics from the accessibility tree.
    stats: AccessibilityStats = _compute_accessibility_stats(accessibility_tree)

    # Step 6b: apply minimal health checks. This may still raise
    # InaccessibleWebpageError for clearly invalid pages (e.g. many
    # unnamed interactive elements), but trivial trees are treated as a
    # partial analysis instead of a hard failure.
    passed_checks = _run_health_checks(stats=stats, url=effective_url)

    if passed_checks:
        summary = (
            "Accessibility analysis completed and basic health checks passed. "
            "Detailed suggestion reports will be added in later iterations."
        )
        severity = SeverityLevel.LOW
    else:
        summary = (
            "Accessibility analysis completed, but the accessibility tree "
            "appears minimal or incomplete. Treat these results as partial."
        )
        severity = SeverityLevel.MEDIUM

    suggestion_report: SuggestionReport = SuggestionReport(
        summary=summary,
        severity=severity,
        issues=[],
    )

    distilled = DistilledResult(
        url=effective_url,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        timeout_ms=timeout_ms,
        stats=stats,
        suggestion_report=suggestion_report,
        accessibility_tree=accessibility_tree,
        metadata={
            "implementation": "stub",
            "version": "0.1.0",
        },
    )

    # Note: we intentionally do NOT raise InaccessibleWebpageError here yet,
    # because no real checks are implemented. That behavior will be added in
    # later steps once Playwright integration and health checks exist.

    return distilled


def run_accessibility_distillation_sync(
    url: Optional[str] = None,
    timeout_ms: int = 30_000,
) -> DistilledResult:
    """
    Synchronous wrapper around the async distiller.

    This is convenient for simple CLI or CI entrypoints that do not want
    to manage an event loop directly.
    """

    import asyncio

    try:
        return asyncio.run(
            run_accessibility_distillation(url=url, timeout_ms=timeout_ms)
        )
    except InaccessibleWebpageError:
        # Re-raise unchanged for callers that specifically want to catch it.
        raise

