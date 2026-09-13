"""
Unit tests for EQATS Automated AI Workflow Reviewer
"""

import sys
from pathlib import Path
import pytest

root_dir = Path(__file__).resolve().parent.parent
scripts_dir = root_dir / ".github" / "scripts"
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(scripts_dir))

from ai_workflow_reviewer import AIWorkflowReviewer


def test_ai_workflow_reviewer_initialization():
    reviewer = AIWorkflowReviewer()
    assert reviewer.root_dir.exists()


def test_gather_pipeline_metrics():
    reviewer = AIWorkflowReviewer()
    metrics = reviewer.gather_pipeline_metrics()
    assert "total_repos" in metrics
    assert "current_index" in metrics
    assert "completed" in metrics
    assert "skipped" in metrics
    assert "pending" in metrics


def test_generate_ai_review_report_deterministic_fallback():
    reviewer = AIWorkflowReviewer()
    metrics = reviewer.gather_pipeline_metrics()
    report = reviewer.generate_ai_review_report(metrics)
    assert "# " in report
    assert "EQATS" in report
