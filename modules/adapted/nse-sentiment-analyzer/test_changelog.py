"""Tests for changelog and feature request infrastructure."""


def test_changelog_file_exists():
    """CHANGELOG.md should exist at project root."""
    import os
    assert os.path.isfile("CHANGELOG.md"), "CHANGELOG.md not found at project root"


def test_changelog_has_entries():
    """CHANGELOG.md should contain at least one version entry."""
    with open("CHANGELOG.md", encoding="utf-8") as f:
        content = f.read()
    assert "## [" in content or "# " in content, "No version headers found in CHANGELOG.md"
