"""
Unit and Integration Tests for EQATS Autonomous Repository Integrator & Self-Healing Pipeline
"""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import pytest

root_dir = Path(__file__).resolve().parent.parent
scripts_dir = root_dir / ".github" / "scripts"
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(scripts_dir))

from autonomous_repo_integrator import AutonomousRepoIntegrator, IST_SESSION_HELPER
from trigger_loop import dispatch_next_cycle


@pytest.fixture
def temp_integrator_env():
    """Creates an isolated temporary environment with mock repositories.txt and ledger."""
    temp_dir = Path(tempfile.mkdtemp())
    repos_file = temp_dir / "repositories.txt"

    repos_file.write_text("owner1/repo1\nowner2/repo2\nowner3/repo3\n", encoding="utf-8")

    orig_cwd = Path.cwd()
    os.chdir(temp_dir)

    integrator = AutonomousRepoIntegrator(
        repositories_file="repositories.txt",
        ledger_path="ingestion_blueprint.json",
        tasks_path="todo_tasks.md",
    )

    yield integrator, temp_dir

    os.chdir(orig_cwd)
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_load_repository_list(temp_integrator_env):
    integrator, _ = temp_integrator_env
    repos = integrator.load_repository_list()
    assert len(repos) == 3
    assert repos[0]["name"] == "repo1"
    assert repos[0]["target"] == "owner1/repo1"
    assert repos[0]["url"] == "https://github.com/owner1/repo1"


def test_ledger_persistence_and_recovery(temp_integrator_env):
    integrator, temp_dir = temp_integrator_env
    assert integrator.ledger["current_index"] == 0
    assert len(integrator.ledger["repositories"]) == 3

    ledger_file = temp_dir / "ingestion_blueprint.json"
    ledger_file.write_text("{ corrupted_json: true ", encoding="utf-8")

    reloaded_integrator = AutonomousRepoIntegrator(
        repositories_file="repositories.txt",
        ledger_path="ingestion_blueprint.json",
    )
    assert reloaded_integrator.ledger["current_index"] == 0
    assert len(reloaded_integrator.ledger["repositories"]) == 3


def test_sanitize_and_adapt_code_future_import(temp_integrator_env):
    integrator, temp_dir = temp_integrator_env
    sample_code = """from __future__ import annotations

def sample_func(price: float) -> float:
    # TODO: implement later
    return price * 1.05
"""
    test_file = temp_dir / "future_strategy.py"
    test_file.write_text(sample_code, encoding="utf-8")

    adapted = integrator.sanitize_and_adapt_code(test_file, temp_dir, "mock_repo")
    assert adapted is not None
    assert adapted.exists()

    content = adapted.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    # Ensure from __future__ import is the first code statement
    assert lines[0] == "from __future__ import annotations"
    assert "is_ist_market_session_active" in content


def test_auto_fix_syntax(temp_integrator_env):
    integrator, temp_dir = temp_integrator_env
    invalid_code_path = temp_dir / "invalid_syntax.py"
    invalid_code_path.write_text("def broken_func()\n    return 42\n", encoding="utf-8")

    try:
        import ast
        ast.parse(invalid_code_path.read_text(encoding="utf-8"))
    except SyntaxError as syn_err:
        integrator._auto_fix_syntax(invalid_code_path, syn_err)

    fixed_content = invalid_code_path.read_text(encoding="utf-8")
    assert "def broken_func():" in fixed_content


def test_auto_fix_mypy(temp_integrator_env):
    integrator, temp_dir = temp_integrator_env
    mypy_test_file = temp_dir / "mypy_test.py"
    mypy_test_file.write_text("x: Any = 10\n", encoding="utf-8")

    integrator._auto_fix_mypy(mypy_test_file, "Name 'Any' is not defined")
    fixed_content = mypy_test_file.read_text(encoding="utf-8")
    assert "from typing import Any" in fixed_content


def test_auto_fix_test_failures(temp_integrator_env):
    integrator, temp_dir = temp_integrator_env
    failing_test_file = temp_dir / "fail_test.py"
    failing_test_file.write_text("res = unassigned_var\n", encoding="utf-8")

    integrator._auto_fix_test_failures(failing_test_file, "NameError: name 'unassigned_var' is not defined")
    fixed_content = failing_test_file.read_text(encoding="utf-8")
    assert "unassigned_var = None" in fixed_content


def test_self_healing_handles_no_tests_collected(temp_integrator_env):
    integrator, temp_dir = temp_integrator_env
    valid_module = temp_dir / "valid_module.py"
    valid_module.write_text("def valid_calculation(x: int) -> int:\n    return x + 1\n", encoding="utf-8")

    # Pytest will return exit code 5 (NO_TESTS_COLLECTED), which should pass self-healing
    success = integrator.self_healing_loop(valid_module, max_retries=1)
    assert success is True


def test_trigger_loop_execution(temp_integrator_env):
    _integrator, _temp_dir = temp_integrator_env
    dispatch_next_cycle()
