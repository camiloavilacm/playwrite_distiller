"""
Core package for the Playwright-based accessibility distiller.

Public surface is intentionally small and explicit so that imports in
application code and tests remain stable as the project evolves.
"""

from __future__ import annotations

from .exceptions import InaccessibleWebpageError
from .types import (
    AccessibilityStats,
    InteractiveElementIssue,
    SeverityLevel,
    SuggestionReport,
)

__all__: list[str] = [
    "AccessibilityStats",
    "InteractiveElementIssue",
    "InaccessibleWebpageError",
    "SeverityLevel",
    "SuggestionReport",
]


