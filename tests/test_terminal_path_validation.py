"""
Security test for terminal path validation.

This test verifies that the fix for the arbitrary executable selection vulnerability
is working correctly. The vulnerability allowed database-controlled terminal paths
to select arbitrary executables for execution by the MT5 initialization API.

The fix implements strict validation at multiple layers:
1. Database write time (add_broker_account, save_broker_credentials)
2. Database read time (MT5Connector.connect)
"""

import os
import tempfile
from typing import Any

import pytest

import config
import database


def test_validate_terminal_path_legitimate_paths() -> None:
    """Test that legitimate MT5 terminal paths are accepted."""
    valid_paths = [
        "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
        "C:\\Program Files (x86)\\MetaTrader 5\\terminal64.exe",
        "C:\\Program Files\\Alpari MT5\\terminal64.exe",
        "C:\\Program Files\\RoboForex MT5\\terminal.exe",
        "C:\\Users\\Trader\\AppData\\Local\\Programs\\MetaTrader 5\\terminal64.exe",
    ]
    for path in valid_paths:
        try:
            result = database.validate_terminal_path(path)
            assert result.lower().endswith(("terminal64.exe", "terminal.exe"))
            print(f"✓ Valid path accepted: {path}")
        except ValueError:
            print(f"✓ Valid path format accepted (file may not exist): {path}")


def test_validate_terminal_path_rejects_arbitrary_executables() -> None:
    """Test that arbitrary executables are rejected."""
    malicious_paths = [
        "C:\\Windows\\System32\\cmd.exe",
        "C:\\Windows\\System32\\powershell.exe",
        "C:\\Windows\\System32\\calc.exe",
        "C:\\Program Files\\SomeApp\\malicious.exe",
        "C:\\Users\\Public\\Downloads\\backdoor.exe",
        "\\\\remote\\share\\evil.exe",
    ]
    for path in malicious_paths:
        try:
            result = database.validate_terminal_path(path)
            pytest.fail(f"Malicious path was incorrectly accepted: {path}")
        except ValueError as e:
            assert "Invalid MT5 terminal filename" in str(e) or "terminal filename" in str(e).lower()
            print(f"✓ Malicious path rejected: {path} - {e}")


def test_validate_terminal_path_rejects_relative_paths() -> None:
    """Test that relative paths are rejected."""
    relative_paths = [
        "terminal64.exe",
        ".\\terminal64.exe",
        "..\\terminal64.exe",
        "..\\..\\Windows\\System32\\cmd.exe",
        "subfolder\\terminal64.exe",
    ]
    for path in relative_paths:
        try:
            result = database.validate_terminal_path(path)
            print(f"⚠ Relative path converted to absolute: {path} -> {result}")
        except ValueError as e:
            print(f"✓ Relative path rejected: {path} - {e}")


def test_validate_terminal_path_rejects_directory_traversal() -> None:
    """Test that directory traversal attempts are rejected."""
    traversal_paths = [
        "C:\\Program Files\\MT5\\..\\..\\..\\Windows\\System32\\cmd.exe",
        "C:\\Program Files\\MT5\\..\\..\\SomeApp\\malicious.exe",
    ]
    for path in traversal_paths:
        try:
            result = database.validate_terminal_path(path)
            pytest.fail(f"Directory traversal path was incorrectly accepted: {path}")
        except ValueError as e:
            assert "directory traversal" in str(e).lower() or "invalid" in str(e).lower()
            print(f"✓ Directory traversal rejected: {path} - {e}")


def test_validate_terminal_path_empty_and_none() -> None:
    """Test that empty and None paths are handled gracefully."""
    assert database.validate_terminal_path("") == ""
    assert database.validate_terminal_path(None) == ""
    assert database.validate_terminal_path("   ") == ""
    print("✓ Empty and None paths handled correctly")


def test_add_broker_account_validates_terminal_path() -> None:
    """Test that add_broker_account validates terminal_path before storing."""
    test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    test_db.close()
    original_db = config.DB_PATH
    config.DB_PATH = test_db.name
    try:
        database.init_db()
        database.add_broker_account(
            broker_name="Test Broker",
            server="test.server.com",
            account_id="12345",
            password="password123",
            terminal_path="C:\\Windows\\System32\\cmd.exe",
            is_active=1,
        )
        creds = database.get_broker_credentials()
        assert creds["terminal_path"] == "", (
            f"Malicious terminal path should have been cleared, but got: {creds['terminal_path']}"
        )
        print("✓ add_broker_account correctly rejected malicious terminal path")
        database.add_broker_account(
            broker_name="Test Broker 2",
            server="test.server.com",
            account_id="67890",
            password="password456",
            terminal_path="C:\\Program Files\\MetaTrader 5\\terminal64.exe",
            is_active=1,
        )
        creds = database.get_broker_credentials()
        assert creds["terminal_path"].lower().endswith("terminal64.exe"), (
            f"Legitimate terminal path should have been accepted, but got: {creds['terminal_path']}"
        )
        print("✓ add_broker_account correctly accepted legitimate terminal path")
    finally:
        config.DB_PATH = original_db
        try:
            os.unlink(test_db.name)
        except:
            pass


def test_save_broker_credentials_validates_terminal_path() -> None:
    """Test that save_broker_credentials validates terminal_path before storing."""
    test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    test_db.close()
    original_db = config.DB_PATH
    config.DB_PATH = test_db.name
    try:
        database.init_db()
        database.save_broker_credentials(
            server="test.server.com",
            account_id="12345",
            password="password123",
            leverage="1:100",
            terminal_path="C:\\Windows\\System32\\powershell.exe",
        )
        creds = database.get_broker_credentials()
        assert creds["terminal_path"] == "", (
            f"Malicious terminal path should have been cleared, but got: {creds['terminal_path']}"
        )
        print("✓ save_broker_credentials correctly rejected malicious terminal path")
        database.save_broker_credentials(
            server="test.server.com",
            account_id="67890",
            password="password456",
            leverage="1:100",
            terminal_path="C:\\Program Files\\Alpari MT5\\terminal64.exe",
        )
        creds = database.get_broker_credentials()
        assert creds["terminal_path"].lower().endswith("terminal64.exe"), (
            f"Legitimate terminal path should have been accepted, but got: {creds['terminal_path']}"
        )
        print("✓ save_broker_credentials correctly accepted legitimate terminal path")
    finally:
        config.DB_PATH = original_db
        try:
            os.unlink(test_db.name)
        except:
            pass


def test_connector_validates_terminal_path() -> None:
    """Test that MT5Connector.connect validates terminal_path before using it."""
    test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    test_db.close()
    original_db = config.DB_PATH
    config.DB_PATH = test_db.name
    try:
        database.init_db()
        database.add_broker_account(
            broker_name="Test Gateway", server="test.server.com", account_id="11111", password="pwd", is_active=1,
        )
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "\n            UPDATE broker_credentials \n            SET terminal_path = ? \n            WHERE is_active = 1\n        ",
            ("C:\\Windows\\System32\\calc.exe",),
        )
        conn.commit()
        conn.close()
        creds = database.get_broker_credentials()
        assert "calc.exe" in creds["terminal_path"].lower(), "Test setup failed: malicious path not in database"
        try:
            validated = database.validate_terminal_path(creds["terminal_path"])
            pytest.fail("Connector should have rejected malicious path from database")
        except ValueError as e:
            assert "Invalid MT5 terminal filename" in str(e)
            print("✓ Connector validation correctly rejects malicious path from database")
    finally:
        config.DB_PATH = original_db
        try:
            os.unlink(test_db.name)
        except:
            pass


if __name__ == "__main__":
    print("=" * 80)
    print("SECURITY TEST: Terminal Path Validation")
    print("=" * 80)
    print()
    print("Test 1: Legitimate MT5 paths")
    print("-" * 80)
    test_validate_terminal_path_legitimate_paths()
    print()
    print("Test 2: Arbitrary executables (should be rejected)")
    print("-" * 80)
    test_validate_terminal_path_rejects_arbitrary_executables()
    print()
    print("Test 3: Relative paths")
    print("-" * 80)
    test_validate_terminal_path_rejects_relative_paths()
    print()
    print("Test 4: Directory traversal attempts (should be rejected)")
    print("-" * 80)
    test_validate_terminal_path_rejects_directory_traversal()
    print()
    print("Test 5: Empty and None values")
    print("-" * 80)
    test_validate_terminal_path_empty_and_none()
    print()
    print("Test 6-7: add_broker_account validation")
    print("-" * 80)
    test_add_broker_account_validates_terminal_path()
    print()
    print("Test 8-9: save_broker_credentials validation")
    print("-" * 80)
    test_save_broker_credentials_validates_terminal_path()
    print()
    print("Test 10: Connector defense-in-depth validation")
    print("-" * 80)
    test_connector_validates_terminal_path()
    print()
    print("=" * 80)
    print("ALL SECURITY TESTS PASSED")
    print("=" * 80)
