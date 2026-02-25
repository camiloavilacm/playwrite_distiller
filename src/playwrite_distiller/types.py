"""
Core datatypes for the accessibility distiller.

These dataclasses are intentionally JSON-friendly and will be used both
for deterministic CI artifacts and for downstream AI analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class SeverityLevel(str, Enum):
    """Severity level for accessibility suggestions and reports."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True)
class AccessibilityStats:
    """
    Aggregate statistics derived from the accessibility tree.
    """

    total_nodes: int
    interactive_nodes: int
    unnamed_interactive_nodes: int
    unnamed_interactive_ratio: float


@dataclass(slots=True)
class InteractiveElementIssue:
    """
    Describes a single interactive element that has an accessibility issue,
    e.g. missing accessible name or ambiguous role.
    """

    role: str
    description: str
    name: Optional[str] = None
    xpath: Optional[str] = None
    css_selector: Optional[str] = None
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SuggestionReport:
    """
    Structured report with suggested remediations for a page.

    The severity level is an aggregate signal for the report as a whole;
    individual issues are listed in ``issues``.
    """

    summary: str
    severity: SeverityLevel
    issues: list[InteractiveElementIssue] = field(default_factory=list)


@dataclass(slots=True)
class DistilledResult:
    """
    High-level result of an accessibility distillation run.

    This object is designed to be easily serialized to JSON for CI
    artifacts and later AI analysis.
    """

    url: str
    timestamp_utc: str
    timeout_ms: int
    stats: AccessibilityStats
    suggestion_report: SuggestionReport
    accessibility_tree: Any | None
    metadata: Mapping[str, Any] = field(default_factory=dict)

