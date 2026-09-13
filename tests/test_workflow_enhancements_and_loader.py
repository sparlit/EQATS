"""
Unit Tests for Dynamic Plugin Loader, Dashboard Generator, and Webhook Alert Dispatcher
"""

import os
import sys
from pathlib import Path
import pytest

root_dir = Path(__file__).resolve().parent.parent
scripts_dir = root_dir / ".github" / "scripts"
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(scripts_dir))

from institutional_integrations.dynamic_plugin_loader import DynamicPluginLoader, initialize_dynamic_plugins
from generate_dashboard import generate_dashboard
from alert_dispatcher import send_webhook_alert


def test_dynamic_plugin_loader():
    loader = DynamicPluginLoader()
    res = loader.discover_and_load_plugins()

    assert "loaded_modules_count" in res
    assert "registered_plugins_count" in res
    assert isinstance(res["registered_plugins"], list)


def test_dashboard_generator():
    generate_dashboard()
    dashboard_file = Path("dashboard.html")
    assert dashboard_file.exists()
    content = dashboard_file.read_text(encoding="utf-8")
    assert "EQATS Institutional Integration Dashboard" in content


def test_alert_dispatcher():
    res = send_webhook_alert("TEST", "Test Title", "Test Message Payload")
    assert res["event_type"] == "TEST"
    assert res["title"] == "Test Title"
    assert isinstance(res["dispatched_channels"], list)
