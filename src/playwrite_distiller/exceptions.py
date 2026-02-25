"""
Custom exceptions for the Playwright-based accessibility distiller.
"""

from __future__ import annotations

from typing import Optional

from .types import AccessibilityStats, SuggestionReport


class InaccessibleWebpageError(Exception):
    """
    Raised when the accessibility health checks determine that a page
    does not meet the minimum deterministic accessibility bar.

    This error is designed to be machine- as well as human-friendly:
    - ``message`` gives a concise human summary.
    - ``stats`` exposes the computed AccessibilityStats (when available).
    - ``suggestion_report`` carries structured guidance for remediation.
    """

    def __init__(
        self,
        message: str,
        stats: Optional[AccessibilityStats] = None,
        suggestion_report: Optional[SuggestionReport] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stats = stats
        self.suggestion_report = suggestion_report


