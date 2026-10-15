"""
Unit tests for the CredentialManager standalone module.
"""

import contextlib
import os
import tempfile
from collections.abc import Generator
from unittest.mock import patch

import pytest

from unittest.mock import patch

from src.credential_manager import CredentialManager


@pytest.fixture
def temp_db() -> Generator[str]:
    """Creates a temporary database file for test isolation."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        with contextlib.suppress(Exception):
            os.remove(path)
    salt_file = path + ".salt"
    if os.path.exists(salt_file):
        with contextlib.suppress(Exception):
            os.remove(salt_file)


def test_credential_manager_init(temp_db: str) -> None:
    """Tests initialization of CredentialManager with custom DB path."""
    cm = CredentialManager(db_path=temp_db)
    assert cm is not None


def test_add_user_error_paths(temp_db: str) -> None:
    cm = CredentialManager(db_path=temp_db)

    # 1. Test empty / missing inputs
    assert cm.add_user("", "Password123!", "123456") is False
    assert cm.add_user("trader_bob", "", "123456") is False
    assert cm.add_user("trader_bob", "Password123!", "") is False

    # 2. Test database exception handling (line 78 error path)
    from unittest.mock import patch
    with patch("database.add_user", side_effect=Exception("Database error simulation")):
        assert cm.add_user("trader_bob", "Password123!", "123456") is False


def test_user_crud_operations(temp_db: str) -> None:
    """Tests user CRUD operations."""
    cm = CredentialManager(db_path=temp_db)

    # 1. Add user
    assert cm.add_user("trader_bob", "Password123!", "123456", role="QUANT_TRADER") is True

    # 2. Get all users
    users = cm.get_all_users()
    assert len(users) >= 2  # QUANT_OPERATOR (default) + trader_bob
    bob = cm.get_user("trader_bob")
    assert bob is not None
    assert bob["username"] == "trader_bob"
    assert bob["role"] == "QUANT_TRADER"

    # Non-existent user
    assert cm.get_user("non_existent_user") is None

    # 3. Verify user credentials
    assert cm.verify_user_credentials("trader_bob", "Password123!", "123456") is True
    assert cm.verify_user_credentials("trader_bob", "WrongPassword", "123456") is False

    # 4. Update user
    assert (
        cm.update_user(
            "trader_bob",
            new_password="NewPassword456!",
            new_role="SOVEREIGN_ADMIN",
        )
        is True
    )
    assert cm.verify_user_credentials("trader_bob", "NewPassword456!", "123456") is True

    # 5. Reset admin credentials
    assert (
        cm.reset_admin_credentials(
            new_password="NewAdminPassword789!",
            new_pin="999888",
        )
        is True
    )
    assert cm.verify_user_credentials("QUANT_OPERATOR", "NewAdminPassword789!", "999888") is True

    # 6. Delete user
    assert cm.delete_user("trader_bob") is True
    assert cm.get_user("trader_bob") is None


def test_broker_crud_operations(temp_db: str) -> None:
    """Tests broker CRUD operations."""
    cm = CredentialManager(db_path=temp_db)

    # 1. Add broker
    assert (
        cm.add_broker_account(
            broker_name="Interactive Brokers",
            server="127.0.0.1:4002",
            account_id="U1234567",
            password="IBSecretPassword",
            leverage="1:50",
            protocol_type="IBKR",
            is_active=1,
        )
        is True
    )

    # 2. Get brokers
    brokers = cm.get_all_brokers()
    assert len(brokers) == 1
    b = brokers[0]
    assert b["broker_name"] == "Interactive Brokers"
    assert b["password"] == "IBSecretPassword"

    # 3. Get active broker
    active_b = cm.get_active_broker_credentials()
    assert active_b is not None
    assert active_b["broker_name"] == "Interactive Brokers"

    # 4. Save primary broker credentials
    assert (
        cm.save_primary_broker_credentials(
            server="127.0.0.1:4002",
            account_id="U1234567",
            password="UpdatedIBSecretPassword",
            leverage="1:100",
            broker_name="Interactive Brokers Updated",
        )
        is True
    )

    active_b_updated = cm.get_active_broker_credentials()
    assert active_b_updated is not None
    assert active_b_updated["broker_name"] == "Interactive Brokers Updated"
    assert active_b_updated["password"] == "UpdatedIBSecretPassword"

    # 5. Broker profiles
    assert cm.add_broker_profile(broker_key="ibkr", display_name="IBKR Profile") is True
    profiles = cm.get_all_broker_profiles()
    assert len(profiles) >= 1

    # 6. Terminal path validation
    valid, res = cm.validate_terminal_path("C:/Program Files/MetaTrader 5/terminal64.exe")
    assert valid is True
    assert "terminal64.exe" in res.lower()

    invalid, _ = cm.validate_terminal_path("C:/Windows/notepad.exe")
    assert invalid is False

    # 7. Delete broker
    b_id = b["id"]
    assert cm.delete_broker_account(b_id) is True
    assert len(cm.get_all_brokers()) == 0


def test_user_error_paths(temp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cm = CredentialManager(db_path=temp_db)

    # 1. add_user validation errors (missing params)
    assert cm.add_user("", "Pass123!", "123456") is False
    assert cm.add_user("user1", "", "123456") is False
    assert cm.add_user("user1", "Pass123!", "") is False

    # 2. add_user database exception error path
    monkeypatch.setattr("database.add_user", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.add_user("err_user", "Pass123!", "123456") is False

    # 3. update_user database exception error path
    monkeypatch.setattr("database.update_user", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.update_user("trader_bob", new_password="NewPass!") is False

    # 4. delete_user database exception error path
    monkeypatch.setattr("database.delete_user", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.delete_user("trader_bob") is False

    # 5. reset_admin_credentials database exception error path
    monkeypatch.setattr("database.add_user", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    monkeypatch.setattr("database.update_user", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.reset_admin_credentials() is False


def test_broker_error_paths(temp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cm = CredentialManager(db_path=temp_db)

    # 1. add_broker_account exception error path
    monkeypatch.setattr("database.add_broker_account", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.add_broker_account("BrokerX", "127.0.0.1", "12345", "pass") is False

    # 2. save_primary_broker_credentials exception error path
    monkeypatch.setattr("database.save_broker_credentials", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.save_primary_broker_credentials("127.0.0.1", "12345", "pass") is False

    # 3. set_active_broker exception error path
    monkeypatch.setattr("database.set_active_broker", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.set_active_broker(1) is False

    # 4. delete_broker_account exception error path
    monkeypatch.setattr("database.delete_broker_account", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.delete_broker_account(1) is False

    # 5. add_broker_profile exception error path
    monkeypatch.setattr("database.add_broker_profile", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.add_broker_profile("KEY", "Display Name") is False

    # 6. reencrypt_all_broker_credentials exception error path
    monkeypatch.setattr(cm, "get_all_brokers", lambda: (_ for _ in ()).throw(RuntimeError("DB error")))
    assert cm.reencrypt_all_broker_credentials() is False


def test_security_health_and_circuit_breaker(temp_db: str) -> None:
    """Tests security health check and circuit breaker reset."""
    cm = CredentialManager(db_path=temp_db)

    # Security health
    health = cm.get_security_health_status()
    assert "overall_security_grade" in health
    assert "migration_status" in health

    # Re-encryption test
    cm.add_broker_account(
        broker_name="Test Broker Active",
        server="DemoServer",
        account_id="999888",
        password="TestPassword",
        is_active=1,
    )
    cm.add_broker_account(
        broker_name="Test Broker Inactive",
        server="DemoServer",
        account_id="999889",
        password="TestPassword",
        is_active=0,
    )
    assert cm.reencrypt_all_broker_credentials() is True

    # Circuit breaker state
    database.save_circuit_breaker_state(
        trading_date="2026-03-31",
        daily_start_balance=10000.0,
        is_halted=True,
        halt_reason="Max Drawdown Exceeded",
    )

    cb_state = cm.load_circuit_breaker_state()
    assert cb_state is not None
    assert cb_state["is_halted"] is True

    assert cm.reset_circuit_breaker_halt() is True
    cb_state_reset = cm.load_circuit_breaker_state()
    assert cb_state_reset is not None
    assert cb_state_reset["is_halted"] is False


def test_user_error_paths(temp_db: str) -> None:
    from unittest.mock import patch

    cm = CredentialManager(db_path=temp_db)

    # Missing parameters validation
    assert cm.add_user("", "Password123!", "123456") is False
    assert cm.add_user("user1", "", "123456") is False
    assert cm.add_user("user1", "Password123!", "") is False

    # Exception handling when calling database functions
    with patch("database.add_user", side_effect=RuntimeError("Database failure")):
        assert cm.add_user("fail_user", "Pass123!", "123456") is False

    with patch("database.update_user", side_effect=RuntimeError("Database failure")):
        assert cm.update_user("fail_user", new_password="NewPass123!") is False

    with patch("database.delete_user", side_effect=RuntimeError("Database failure")):
        assert cm.delete_user("fail_user") is False

    # Reset admin credentials error paths
    with patch("database.add_user", side_effect=RuntimeError("Admin reset failure")):
        assert cm.reset_admin_credentials(admin_username="NON_EXISTENT_ADMIN") is False

    with patch("database.update_user", side_effect=RuntimeError("Admin update failure")):
        assert cm.reset_admin_credentials(admin_username="QUANT_OPERATOR") is False


def test_broker_error_paths(temp_db: str) -> None:
    from unittest.mock import patch

    cm = CredentialManager(db_path=temp_db)

    # Test broker profile CRUD happy path and error handling
    assert cm.add_broker_profile(broker_key="NSE_TEST", display_name="NSE Test Broker") is True
    profiles = cm.get_all_broker_profiles()
    assert any(p.get("broker_key") == "nse_test" for p in profiles)

    with patch("database.add_broker_profile", side_effect=RuntimeError("Profile error")):
        assert cm.add_broker_profile(broker_key="FAIL_KEY", display_name="Fail Broker") is False

    # Broker account error paths
    with patch("database.add_broker_account", side_effect=RuntimeError("Add account error")):
        assert (
            cm.add_broker_account(
                broker_name="FailBroker",
                server="FailServer",
                account_id="000",
                password="Pass",
            )
            is False
        )

    with patch("database.save_broker_credentials", side_effect=RuntimeError("Save credentials error")):
        assert (
            cm.save_primary_broker_credentials(
                server="FailServer",
                account_id="000",
                password="Pass",
            )
            is False
        )

    with patch("database.set_active_broker", side_effect=RuntimeError("Set active error")):
        assert cm.set_active_broker(999) is False

    with patch("database.delete_broker_account", side_effect=RuntimeError("Delete broker error")):
        assert cm.delete_broker_account(999) is False

    # Re-encryption error handling
    with patch.object(cm, "get_all_brokers", side_effect=RuntimeError("Get brokers error")):
        assert cm.reencrypt_all_broker_credentials() is False
