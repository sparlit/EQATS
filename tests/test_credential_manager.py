"""
Unit tests for the CredentialManager standalone module.
"""

import os
import tempfile
from collections.abc import Generator

import pytest

from src.credential_manager import CredentialManager


@pytest.fixture
def temp_db() -> Generator[str]:
    """Creates a temporary database file for test isolation."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    salt_file = path + ".salt"
    if os.path.exists(salt_file):
        try:
            os.remove(salt_file)
        except Exception:
            pass


def test_credential_manager_init(temp_db: str) -> None:
    cm = CredentialManager(db_path=temp_db)
    assert cm is not None


def test_user_crud_operations(temp_db: str) -> None:
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

    # 3. Verify user credentials
    assert cm.verify_user_credentials("trader_bob", "Password123!", "123456") is True
    assert cm.verify_user_credentials("trader_bob", "WrongPassword", "123456") is False

    # 4. Update user
    assert cm.update_user("trader_bob", new_password="NewPassword456!", new_role="SOVEREIGN_ADMIN") is True
    assert cm.verify_user_credentials("trader_bob", "NewPassword456!", "123456") is True

    # 5. Reset admin credentials
    assert cm.reset_admin_credentials(new_password="NewAdminPassword789!", new_pin="999888") is True
    assert cm.verify_user_credentials("QUANT_OPERATOR", "NewAdminPassword789!", "999888") is True

    # 6. Delete user
    assert cm.delete_user("trader_bob") is True
    assert cm.get_user("trader_bob") is None


def test_broker_crud_operations(temp_db: str) -> None:
    cm = CredentialManager(db_path=temp_db)

    # 1. Add broker
    assert cm.add_broker_account(
        broker_name="Interactive Brokers",
        server="127.0.0.1:4002",
        account_id="U1234567",
        password="IBSecretPassword",
        leverage="1:50",
        protocol_type="IBKR",
        is_active=1,
    ) is True

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
    assert cm.save_primary_broker_credentials(
        server="127.0.0.1:4002",
        account_id="U1234567",
        password="UpdatedIBSecretPassword",
        leverage="1:100",
        broker_name="Interactive Brokers Updated",
    ) is True

    active_b_updated = cm.get_active_broker_credentials()
    assert active_b_updated is not None
    assert active_b_updated["broker_name"] == "Interactive Brokers Updated"
    assert active_b_updated["password"] == "UpdatedIBSecretPassword"

    # 5. Terminal path validation
    valid, res = cm.validate_terminal_path("C:/Program Files/MetaTrader 5/terminal64.exe")
    assert valid is True
    assert "terminal64.exe" in res.lower()

    invalid, _ = cm.validate_terminal_path("C:/Windows/notepad.exe")
    assert invalid is False

    # 6. Delete broker
    b_id = b["id"]
    assert cm.delete_broker_account(b_id) is True
    assert len(cm.get_all_brokers()) == 0


def test_security_health_and_circuit_breaker(temp_db: str) -> None:
    cm = CredentialManager(db_path=temp_db)

    # Security health
    health = cm.get_security_health_status()
    assert "overall_security_grade" in health
    assert "migration_status" in health

    # Re-encryption test
    cm.add_broker_account(
        broker_name="Test Broker",
        server="DemoServer",
        account_id="999888",
        password="TestPassword",
        is_active=1,
    )
    assert cm.reencrypt_all_broker_credentials() is True

    # Circuit breaker state
    import database
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
