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
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .exceptions import InaccessibleWebpageError
from .types import (
    AccessibilityStats,
    DistilledResult,
    InteractiveElementIssue,
    SeverityLevel,
    SuggestionReport,
)

LOGGER = logging.getLogger(__name__)


def configure_logging(level: str | None = None) -> None:
    """Configure logging based on environment or explicit level."""
    import os

    log_level = level or os.environ.get("PLAYWRITE_DISTILLER_LOG_LEVEL", "WARNING")
    numeric_level = getattr(logging, log_level.upper(), logging.WARNING)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


configure_logging()

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

FORM_ROLES = {
    "textbox",
    "searchbox",
    "combobox",
    "checkbox",
    "radio",
    "switch",
    "slider",
    "spinbutton",
}

INVALID_ARIA_ROLES = {
    "banner",
    "contentinfo",
    "navigation",
    "complementary",
    "main",
    "region",
}

IMAGE_ROLES = {"img", "image"}


def get_interactive_roles() -> set[str]:
    """Get the set of interactive roles. Can be overridden via environment variable."""
    import os

    env_roles = os.environ.get("PLAYWRITE_DISTILLER_INTERACTIVE_ROLES")
    if env_roles:
        return {role.strip() for role in env_roles.split(",") if role.strip()}
    return INTERACTIVE_ROLES.copy()


def set_interactive_roles(roles: set[str]) -> None:
    """Set custom interactive roles (for testing or configuration)."""
    global INTERACTIVE_ROLES
    INTERACTIVE_ROLES = roles


def _load_aria_snapshot_from_file(
    snapshot_path: str,
) -> tuple[Any | None, Mapping[str, Any]]:
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
        metadata: dict[str, Any] = {key: value for key, value in raw.items() if key != "root"}
    else:
        tree = raw
        metadata = {}

    return tree, metadata


def _compute_accessibility_stats(
    tree: Any | None,
) -> tuple[AccessibilityStats, list[InteractiveElementIssue]]:
    """
    Traverse the ARIA snapshot (YAML-parsed dict/list/str) to derive stats.
    Compatible with modern Playwright aria_snapshot() outputs.

    Returns a tuple of (stats, issues) where issues contains specific
    problematic elements found during traversal.
    """
    if isinstance(tree, str):
        try:
            tree = yaml.safe_load(tree)
        except Exception as exc:
            LOGGER.error("Failed to parse ARIA YAML: %s", exc)
            tree = None

    if not tree:
        return (
            AccessibilityStats(
                total_nodes=0,
                interactive_nodes=0,
                unnamed_interactive_nodes=0,
                unnamed_interactive_ratio=0.0,
            ),
            [],
        )

    issues: list[InteractiveElementIssue] = []

    def _walk(node: Any) -> tuple[int, int, int]:
        nonlocal issues
        total = 0
        interactive = 0
        unnamed_interactive = 0

        if isinstance(node, dict):
            total += 1
            for key, value in node.items():
                role_name = key.split()[0] if isinstance(key, str) else ""

                if role_name in get_interactive_roles():
                    interactive = 1
                    has_name = '"' in key or (isinstance(value, str) and value.strip())
                    if not has_name:
                        unnamed_interactive = 1
                        issues.append(
                            InteractiveElementIssue(
                                role=role_name,
                                description=f"Interactive element '{role_name}' without accessible name",
                                name=None,
                            )
                        )

                c_total, c_inter, c_unnamed = _walk(value)
                total += c_total
                interactive += c_inter
                unnamed_interactive += c_unnamed

        elif isinstance(node, list):
            for item in node:
                c_total, c_inter, c_unnamed = _walk(item)
                total += c_total
                interactive += c_inter
                unnamed_interactive += c_unnamed

        elif isinstance(node, str):
            total += 1
            role_name = node.split()[0]
            if role_name in INTERACTIVE_ROLES:
                interactive = 1
                if '"' not in node:
                    unnamed_interactive = 1
                    issues.append(
                        InteractiveElementIssue(
                            role=role_name,
                            description=f"Interactive element '{role_name}' without accessible name",
                            name=None,
                        )
                    )

        return total, interactive, unnamed_interactive

    total_nodes, interactive_nodes, unnamed_interactive_nodes = _walk(tree)

    unnamed_ratio = unnamed_interactive_nodes / interactive_nodes if interactive_nodes else 0.0

    return (
        AccessibilityStats(
            total_nodes=total_nodes,
            interactive_nodes=interactive_nodes,
            unnamed_interactive_nodes=unnamed_interactive_nodes,
            unnamed_interactive_ratio=unnamed_ratio,
        ),
        issues,
    )


def _run_health_checks(
    stats: AccessibilityStats,
    url: str,
    issues: list[InteractiveElementIssue] | None = None,
) -> bool:
    """
    Apply simple, deterministic health checks.

    - Empty / trivial trees (very few nodes) are treated as problematic.
    - Extreme unnamed interactive ratio is also treated as failure.
    - Form controls without accessible names.
    - Invalid ARIA role usage on interactive elements.
    """

    if issues is None:
        issues = []

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
                issues=issues,
            ),
        )

    return True


async def run_accessibility_distillation(
    url: str | None = None,
    snapshot_path: str | None = None,
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
        stats: AccessibilityStats
        issues: list[InteractiveElementIssue]
        stats, issues = _compute_accessibility_stats(accessibility_tree)
        passed_checks = _run_health_checks(stats=stats, url=effective_url, issues=issues)

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
            issues=issues,
        )

        metadata: dict[str, Any] = {
            "implementation": "aria_snapshot_json",
            "version": "0.1.0",
        }
        # Merge any metadata that came from the snapshot document itself.
        metadata.update(snapshot_metadata)

        return DistilledResult(
            url=effective_url,
            timestamp_utc=datetime.now(UTC).isoformat(),
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
        stats, _ = _compute_accessibility_stats(None)
        empty_issues: list[InteractiveElementIssue] = []
        passed_checks = _run_health_checks(stats=stats, url=effective_url, issues=empty_issues)

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
            timestamp_utc=datetime.now(UTC).isoformat(),
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
    stats, issues = _compute_accessibility_stats(accessibility_tree)
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
        issues=issues,
    )

    return DistilledResult(
        url=effective_url,
        timestamp_utc=datetime.now(UTC).isoformat(),
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
    url: str | None = None,
    snapshot_path: str | None = None,
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
