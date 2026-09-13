from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
Tests for automated DMG build workflow (#140).
Validates .github/workflows/build-mac.yml is well-formed.
"""


from pathlib import Path

import pytest

WORKFLOW_FILE = Path(__file__).parent.parent / ".github" / "workflows" / "build-mac.yml"


class TestBuildMacWorkflow:
    def test_workflow_file_exists(self):
        assert WORKFLOW_FILE.exists()

    def test_workflow_is_valid_yaml(self):
        import yaml

        content = WORKFLOW_FILE.read_text()
        parsed = yaml.safe_load(content)
        assert parsed is not None

    def test_workflow_has_name(self):
        import yaml

        parsed = yaml.safe_load(WORKFLOW_FILE.read_text())
        assert "name" in parsed

    def test_workflow_triggers_on_tag_push(self):
        # Check raw YAML text — YAML 'on:' parses as True in Python
        content = WORKFLOW_FILE.read_text()
        assert "tags:" in content or "tag" in content

    def test_workflow_has_manual_trigger(self):
        content = WORKFLOW_FILE.read_text()
        assert "workflow_dispatch" in content

    def test_workflow_runs_on_macos(self):
        import yaml

        parsed = yaml.safe_load(WORKFLOW_FILE.read_text())
        jobs = parsed.get("jobs", {})
        for job in jobs.values():
            runs_on = job.get("runs-on", "")
            if "macos" in str(runs_on).lower():
                return
        pytest.fail("No job runs on macos-latest")

    def test_workflow_has_npm_build_step(self):
        content = WORKFLOW_FILE.read_text()
        assert "npm run build" in content

    def test_workflow_has_python_install(self):
        content = WORKFLOW_FILE.read_text()
        assert "pip install" in content

    def test_workflow_skips_code_signing(self):
        content = WORKFLOW_FILE.read_text()
        assert "CSC_IDENTITY_AUTO_DISCOVERY" in content

    def test_workflow_uploads_artifact(self):
        content = WORKFLOW_FILE.read_text()
        assert "upload-artifact" in content

    def test_workflow_creates_release_on_tag(self):
        content = WORKFLOW_FILE.read_text()
        assert "action-gh-release" in content or "create-release" in content or "release" in content
