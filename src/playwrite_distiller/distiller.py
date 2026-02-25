"""
Accessibility distiller entrypoints.

This module currently provides minimal, Playwright-free stubs for the
core distillation API. In later steps we will:
- Integrate Playwright's async API.
- Collect the accessibility snapshot.
- Run health checks and potentially raise InaccessibleWebpageError.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright

from .exceptions import InaccessibleWebpageError
from .types import (
    AccessibilityStats,
    DistilledResult,
    SeverityLevel,
    SuggestionReport,
)


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

    # Step 4: integrate Playwright navigation only (no snapshot yet).
    # This proves we can deterministically launch a browser and reach
    # the target URL using the async Playwright API.
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(effective_url, timeout=timeout_ms)
        # Keep this minimal for now; later steps will:
        # - wait for a stable state (e.g. networkidle)
        # - capture the accessibility snapshot
        await browser.close()

    stats: AccessibilityStats = AccessibilityStats(
        total_nodes=0,
        interactive_nodes=0,
        unnamed_interactive_nodes=0,
        unnamed_interactive_ratio=0.0,
    )

    suggestion_report: SuggestionReport = SuggestionReport(
        summary="No accessibility analysis has been performed yet (stub distiller).",
        severity=SeverityLevel.LOW,
        issues=[],
    )

    distilled = DistilledResult(
        url=effective_url,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        timeout_ms=timeout_ms,
        stats=stats,
        suggestion_report=suggestion_report,
        accessibility_tree=None,
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

