"""
Unit tests for the accessibility distiller functions.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from playwrite_distiller.distiller import (
    _compute_accessibility_stats,
    _load_aria_snapshot_from_file,
    _run_health_checks,
)
from playwrite_distiller.exceptions import InaccessibleWebpageError
from playwrite_distiller.types import AccessibilityStats, SeverityLevel


class TestLoadAriaSnapshotFromFile:
    """Tests for _load_aria_snapshot_from_file()."""

    def test_load_with_root_key(self, tmp_path: Path) -> None:
        """Test loading a snapshot with 'root' key."""
        data = {
            "root": {"role": "WebArea", "name": "Test"},
            "url": "https://example.com",
            "capturedAt": "2024-01-01T00:00:00Z",
        }
        snapshot_file = tmp_path / "snapshot.json"
        snapshot_file.write_text(json.dumps(data))

        tree, metadata = _load_aria_snapshot_from_file(str(snapshot_file))

        assert tree == {"role": "WebArea", "name": "Test"}
        assert metadata["url"] == "https://example.com"
        assert metadata["capturedAt"] == "2024-01-01T00:00:00Z"

    def test_load_without_root_key(self, tmp_path: Path) -> None:
        """Test loading a snapshot without 'root' key."""
        data = {"role": "WebArea", "name": "Test"}
        snapshot_file = tmp_path / "snapshot.json"
        snapshot_file.write_text(json.dumps(data))

        tree, metadata = _load_aria_snapshot_from_file(str(snapshot_file))

        assert tree == {"role": "WebArea", "name": "Test"}
        assert metadata == {}

    def test_load_invalid_file(self, tmp_path: Path) -> None:
        """Test loading a non-existent file."""
        with pytest.raises(FileNotFoundError):
            _load_aria_snapshot_from_file(str(tmp_path / "nonexistent.json"))


class TestComputeAccessibilityStats:
    """Tests for _compute_accessibility_stats()."""

    def test_none_tree(self) -> None:
        """Test with None tree."""
        stats, issues = _compute_accessibility_stats(None)

        assert stats.total_nodes == 0
        assert stats.interactive_nodes == 0
        assert stats.unnamed_interactive_nodes == 0
        assert stats.unnamed_interactive_ratio == 0.0
        assert issues == []

    def test_empty_dict(self) -> None:
        """Test with empty dict."""
        stats, issues = _compute_accessibility_stats({})

        assert stats.total_nodes == 0
        assert stats.interactive_nodes == 0
        assert issues == []

    def test_simple_button_with_name(self) -> None:
        """Test button with accessible name."""
        tree = {'button "Submit"': []}
        stats, issues = _compute_accessibility_stats(tree)

        assert stats.total_nodes == 1
        assert stats.interactive_nodes == 1
        assert stats.unnamed_interactive_nodes == 0
        assert stats.unnamed_interactive_ratio == 0.0
        assert issues == []

    def test_button_without_name(self) -> None:
        """Test button without accessible name."""
        tree = {"button": []}
        stats, issues = _compute_accessibility_stats(tree)

        assert stats.total_nodes == 1
        assert stats.interactive_nodes == 1
        assert stats.unnamed_interactive_nodes == 1
        assert stats.unnamed_interactive_ratio == 1.0
        assert len(issues) == 1
        assert issues[0].role == "button"
        assert issues[0].name is None

    def test_link_without_name(self) -> None:
        """Test link without accessible name."""
        tree = {"link": []}
        stats, issues = _compute_accessibility_stats(tree)

        assert stats.interactive_nodes == 1
        assert stats.unnamed_interactive_nodes == 1
        assert len(issues) == 1
        assert issues[0].role == "link"

    def test_textbox_with_name(self) -> None:
        """Test textbox with accessible name."""
        tree = {'textbox "Search"': []}
        stats, issues = _compute_accessibility_stats(tree)

        assert stats.interactive_nodes == 1
        assert stats.unnamed_interactive_nodes == 0
        assert issues == []

    def test_nested_structure(self) -> None:
        """Test nested accessibility tree."""
        tree = {
            "root": [
                {'button "Submit"': []},
                {"link": []},
                {"navigation": [{"link": []}]},
            ]
        }
        stats, issues = _compute_accessibility_stats(tree)

        assert stats.total_nodes >= 4
        assert stats.interactive_nodes >= 3
        assert stats.unnamed_interactive_nodes >= 2

    def test_list_of_nodes(self) -> None:
        """Test list of nodes."""
        tree = [
            {'button "OK"': []},
            {'button "Cancel"': []},
            {"link": []},
        ]
        stats, issues = _compute_accessibility_stats(tree)

        assert stats.interactive_nodes == 3
        assert stats.unnamed_interactive_nodes == 1
        assert len(issues) == 1

    def test_string_leaf_node(self) -> None:
        """Test string as leaf node."""
        tree = ["Some text content"]
        stats, issues = _compute_accessibility_stats(tree)

        assert stats.total_nodes == 1
        assert issues == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
