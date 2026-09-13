"""
Unit Tests for EQATS Auto-PR & Failed Merge Healing Engine
"""

import sys
from pathlib import Path
import pytest

root_dir = Path(__file__).resolve().parent.parent
scripts_dir = root_dir / ".github" / "scripts"
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(scripts_dir))

from auto_pr_healer import AutoPRHealer


def test_auto_pr_healer_initialization():
    healer = AutoPRHealer()
    assert healer.root_dir.exists()


def test_fetch_open_pull_requests():
    healer = AutoPRHealer()
    prs = healer.fetch_open_pull_requests()
    assert isinstance(prs, list)


def test_heal_all_pending_prs():
    healer = AutoPRHealer()
    res = healer.heal_all_pending_prs()
    assert "total_open_prs" in res
    assert "healed_and_merged_count" in res
    assert isinstance(res["healed_branches"], list)
