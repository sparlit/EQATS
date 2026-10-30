"""
Unit tests for src/migrate_credentials.py script.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

import migrate_credentials


class TestMigrateCredentials:
    """Test suite for credential migration script."""

    def test_backup_database_missing_file(self, tmp_path: pytest.TempPathFactory) -> None:
        """Test backup_database when DB file does not exist."""
        non_existent_db = str(tmp_path / "non_existent.db")
        with patch("config.DB_PATH", non_existent_db):
            result = migrate_credentials.backup_database()
            assert result is False

    def test_backup_database_success(self, tmp_path: pytest.TempPathFactory) -> None:
        """Test backup_database when DB file exists and copy succeeds."""
        db_file = tmp_path / "test_scalper_brain.db"
        db_file.write_text("dummy db content")
        with patch("config.DB_PATH", str(db_file)):
            result = migrate_credentials.backup_database()
            assert result is True
            # Verify a backup file was created
            backup_files = list(tmp_path.glob("test_scalper_brain.db.backup_*"))
            assert len(backup_files) == 1
            assert backup_files[0].read_text() == "dummy db content"

    def test_backup_database_copy_exception(self, tmp_path: pytest.TempPathFactory) -> None:
        """Test backup_database when shutil.copy2 raises an exception."""
        db_file = tmp_path / "test_scalper_brain.db"
        db_file.write_text("dummy db content")
        with patch("config.DB_PATH", str(db_file)), patch(
            "shutil.copy2", side_effect=PermissionError("Permission denied")
        ):
            result = migrate_credentials.backup_database()
            assert result is False

    def test_check_cryptography_available(self) -> None:
        """Test check_cryptography when cryptography package is available."""
        with patch.dict("sys.modules", {"cryptography.fernet": MagicMock()}):
            result = migrate_credentials.check_cryptography()
            assert result is True

    def test_check_cryptography_missing(self) -> None:
        """Test check_cryptography when cryptography package is missing."""
        with patch.dict("sys.modules", {"cryptography.fernet": None}):
            result = migrate_credentials.check_cryptography()
            assert result is False

    def test_check_master_key_env_var_set(self) -> None:
        """Test check_master_key when EQATS_MASTER_KEY is in environment variables."""
        with patch.dict(os.environ, {"EQATS_MASTER_KEY": "secret_passphrase"}):
            result = migrate_credentials.check_master_key()
            assert result is True

    def test_check_master_key_env_var_not_set_user_accepts(self) -> None:
        """Test check_master_key when EQATS_MASTER_KEY is missing and user inputs 'y'."""
        with patch.dict(os.environ, {}, clear=True), patch("builtins.input", return_value="y"):
            if "EQATS_MASTER_KEY" in os.environ:
                del os.environ["EQATS_MASTER_KEY"]
            result = migrate_credentials.check_master_key()
            assert result is True

    def test_check_master_key_env_var_not_set_user_declines(self) -> None:
        """Test check_master_key when EQATS_MASTER_KEY is missing and user inputs 'n'."""
        with patch.dict(os.environ, {}, clear=True), patch("builtins.input", return_value="n"):
            if "EQATS_MASTER_KEY" in os.environ:
                del os.environ["EQATS_MASTER_KEY"]
            result = migrate_credentials.check_master_key()
            assert result is False

    def test_migrate_credentials_no_brokers(self) -> None:
        """Test migrate_credentials when database returns empty broker list."""
        with patch("database.get_all_brokers", return_value=[]):
            result = migrate_credentials.migrate_credentials()
            assert result is True

    def test_migrate_credentials_active_broker(self) -> None:
        """Test migrate_credentials with active broker credentials."""
        mock_broker = {
            "id": 1,
            "broker_name": "TestBroker",
            "account_id": "12345",
            "password": "pass",
            "server": "demo.server.com",
            "leverage": "1:100",
            "environment": "Demo",
            "protocol_type": "MT5",
            "api_key": "key123",
            "api_secret": "sec123",
            "rest_url": "http://rest.com",
            "ws_url": "ws://ws.com",
            "terminal_path": "/path/to/terminal",
            "is_active": 1,
        }

        with patch("database.get_all_brokers", return_value=[mock_broker]) as mock_get_brokers, patch(
            "database.save_broker_credentials"
        ) as mock_save:
            # First call returns initial brokers, second call returns updated brokers for verification
            mock_get_brokers.side_effect = [[mock_broker], [mock_broker]]

            result = migrate_credentials.migrate_credentials()
            assert result is True
            mock_save.assert_called_once_with(
                server="demo.server.com",
                account_id="12345",
                password="pass",
                leverage="1:100",
                broker_name="TestBroker",
                environment="Demo",
                protocol_type="MT5",
                api_key="key123",
                api_secret="sec123",
                rest_url="http://rest.com",
                ws_url="ws://ws.com",
                terminal_path="/path/to/terminal",
            )

    def test_migrate_credentials_inactive_broker(self) -> None:
        """Test migrate_credentials with inactive broker credentials."""
        mock_broker = {
            "id": 2,
            "broker_name": "InactiveBroker",
            "account_id": "67890",
            "password": "pass",
            "server": "real.server.com",
            "leverage": "1:50",
            "environment": "Live",
            "protocol_type": "MT5",
            "api_key": "",
            "api_secret": "",
            "rest_url": "",
            "ws_url": "",
            "terminal_path": "",
            "is_active": 0,
        }

        with patch("database.get_all_brokers") as mock_get_brokers, patch(
            "database.delete_broker_account"
        ) as mock_delete, patch("database.add_broker_account") as mock_add:
            mock_get_brokers.side_effect = [[mock_broker], [mock_broker]]

            result = migrate_credentials.migrate_credentials()
            assert result is True
            mock_delete.assert_called_once_with(2)
            mock_add.assert_called_once_with(
                broker_name="InactiveBroker",
                server="real.server.com",
                account_id="67890",
                password="pass",
                leverage="1:50",
                environment="Live",
                protocol_type="MT5",
                api_key="",
                api_secret="",
                rest_url="",
                ws_url="",
                terminal_path="",
                is_active=0,
            )

    def test_migrate_credentials_count_mismatch(self) -> None:
        """Test migrate_credentials when broker count differs after migration."""
        mock_broker = {"id": 1, "broker_name": "Broker1", "is_active": 1}

        with patch("database.get_all_brokers") as mock_get_brokers, patch(
            "database.save_broker_credentials"
        ):
            # First fetch returns 1 broker, verification fetch returns empty list
            mock_get_brokers.side_effect = [[mock_broker], []]

            result = migrate_credentials.migrate_credentials()
            assert result is False

    def test_migrate_credentials_save_exception(self) -> None:
        """Test migrate_credentials when saving credentials raises an exception."""
        mock_broker = {"id": 1, "broker_name": "Broker1", "is_active": 1}

        with patch("database.get_all_brokers", return_value=[mock_broker]), patch(
            "database.save_broker_credentials", side_effect=RuntimeError("DB Write Error")
        ):
            result = migrate_credentials.migrate_credentials()
            assert result is False

    def test_migrate_credentials_outer_exception(self) -> None:
        """Test migrate_credentials when database query raises an exception."""
        with patch("database.get_all_brokers", side_effect=RuntimeError("Database Connection Error")):
            result = migrate_credentials.migrate_credentials()
            assert result is False

    def test_main_success(self) -> None:
        """Test main workflow when all checks and operations succeed."""
        with patch("migrate_credentials.check_cryptography", return_value=True), patch(
            "migrate_credentials.check_master_key", return_value=True
        ), patch("migrate_credentials.backup_database", return_value=True), patch(
            "migrate_credentials.migrate_credentials", return_value=True
        ):
            exit_code = migrate_credentials.main()
            assert exit_code == 0

    def test_main_cryptography_check_failed(self) -> None:
        """Test main workflow when cryptography check fails."""
        with patch("migrate_credentials.check_cryptography", return_value=False):
            exit_code = migrate_credentials.main()
            assert exit_code == 1

    def test_main_master_key_check_failed(self) -> None:
        """Test main workflow when master key check fails."""
        with patch("migrate_credentials.check_cryptography", return_value=True), patch(
            "migrate_credentials.check_master_key", return_value=False
        ):
            exit_code = migrate_credentials.main()
            assert exit_code == 1

    def test_main_backup_database_failed(self) -> None:
        """Test main workflow when database backup fails."""
        with patch("migrate_credentials.check_cryptography", return_value=True), patch(
            "migrate_credentials.check_master_key", return_value=True
        ), patch("migrate_credentials.backup_database", return_value=False):
            exit_code = migrate_credentials.main()
            assert exit_code == 1

    def test_main_migration_failed(self) -> None:
        """Test main workflow when credential migration fails."""
        with patch("migrate_credentials.check_cryptography", return_value=True), patch(
            "migrate_credentials.check_master_key", return_value=True
        ), patch("migrate_credentials.backup_database", return_value=True), patch(
            "migrate_credentials.migrate_credentials", return_value=False
        ):
            exit_code = migrate_credentials.main()
            assert exit_code == 1
