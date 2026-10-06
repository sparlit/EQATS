"""
EQATS Credential & Security Manager Module

This independent module provides a unified API, CLI, and standalone GUI interface to:
1. Reset, add, modify, update, and remove operator user credentials and passwords/PINs (including system admin QUANT_OPERATOR).
2. Configure all broker credentials, broker login details, MT5 account details, leverage, servers, API keys, and validate MT5 terminal paths.
3. Configure all security-related features, master encryption keys (Fernet PBKDF2), database credential re-encryption, hash security diagnostics, and circuit breaker resets.

Usage:
    - Programmatic API:
        from src.credential_manager import CredentialManager
        cm = CredentialManager()
    - CLI Interface:
        python -m src.credential_manager [args]
    - Standalone GUI Interface:
        python -m src.credential_manager --gui
"""

import argparse
import logging
import os
import sys
from typing import Any

# Ensure parent directory and src directory are in Python path for imports
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import tkinter as tk
    from tkinter import messagebox, ttk

    _TKINTER_AVAILABLE = True
except ImportError:
    _TKINTER_AVAILABLE = False

import config
import database

_log = logging.getLogger("credential_manager")


class CredentialManager:
    """
    Programmatic API Class for managing EQATS User Credentials, Broker & MT5 Configurations,
    and Security Engine Parameters.
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:
            config.DB_PATH = db_path
        database.init_db()

    # =========================================================================
    # USER CREDENTIALS MANAGEMENT (CRUD)
    # =========================================================================

    def add_user(
        self,
        username: str,
        password: str,
        pin: str,
        role: str = "QUANT_TRADER",
        mfa_enabled: int = 1,
    ) -> bool:
        """Adds a new operator account with bcrypt hashed password and PIN."""
        if not username or not password or not pin:
            _log.error("Username, password, and PIN must be provided.")
            return False
        try:
            database.add_user(username.strip(), password, pin, role=role, mfa_enabled=mfa_enabled)
            _log.info("User '%s' added successfully.", username)
            return True
        except Exception as e:
            _log.error("Failed to add user '%s': %s", username, e)
            return False

    def get_all_users(self) -> list[dict[str, Any]]:
        """Retrieves all registered user account profiles."""
        return database.get_all_users()

    def get_user(self, username: str) -> dict[str, Any] | None:
        """Retrieves user profile details by username."""
        users = self.get_all_users()
        for u in users:
            if u["username"].lower() == username.lower():
                return u
        return None

    def update_user(
        self,
        username: str,
        new_password: str | None = None,
        new_pin: str | None = None,
        new_role: str | None = None,
        new_username: str | None = None,
        login_style: str | None = None,
    ) -> bool:
        """Modifies credentials, role, username, or login style for an existing user account."""
        try:
            database.update_user(
                username=new_username or username,
                new_password=new_password,
                new_pin=new_pin,
                new_role=new_role,
                original_username=username if new_username else None,
                login_style=login_style,
            )
            _log.info("User '%s' updated successfully.", username)
            return True
        except Exception as e:
            _log.error("Failed to update user '%s': %s", username, e)
            return False

    def delete_user(self, username: str) -> bool:
        """Removes a user account."""
        try:
            database.delete_user(username)
            _log.info("User '%s' deleted successfully.", username)
            return True
        except Exception as e:
            _log.error("Failed to delete user '%s': %s", username, e)
            return False

    def reset_admin_credentials(
        self,
        new_password: str = "admin",
        new_pin: str = "741295",
        admin_username: str = "QUANT_OPERATOR",
    ) -> bool:
        """Resets the system administrator credentials (QUANT_OPERATOR / SOVEREIGN_ADMIN)."""
        try:
            user = self.get_user(admin_username)
            if not user:
                database.add_user(
                    admin_username,
                    new_password,
                    new_pin,
                    role="SOVEREIGN_ADMIN",
                    mfa_enabled=1,
                )
            else:
                database.update_user(
                    username=admin_username,
                    new_password=new_password,
                    new_pin=new_pin,
                    new_role="SOVEREIGN_ADMIN",
                )
            _log.info("System Admin '%s' credentials reset successfully.", admin_username)
            return True
        except Exception as e:
            _log.error("Failed to reset system admin credentials: %s", e)
            return False

    def verify_user_credentials(self, username: str, password: str, pin: str | None = None) -> bool:
        """Validates username, password, and optional secondary PIN."""
        return database.verify_user_credentials(username, password, pin)

    # =========================================================================
    # BROKER & MT5 CREDENTIALS MANAGEMENT (CRUD)
    # =========================================================================

    def add_broker_account(
        self,
        broker_name: str,
        server: str,
        account_id: str,
        password: str,
        leverage: str = "1:100",
        environment: str = "Demo",
        protocol_type: str = "MT5",
        api_key: str = "",
        api_secret: str = "",
        rest_url: str = "",
        ws_url: str = "",
        terminal_path: str = "",
        is_active: int = 0,
    ) -> bool:
        """Adds a new broker gateway configuration with encrypted secrets and validated terminal path."""
        try:
            database.add_broker_account(
                broker_name=broker_name,
                server=server,
                account_id=account_id,
                password=password,
                leverage=leverage,
                environment=environment,
                protocol_type=protocol_type,
                api_key=api_key,
                api_secret=api_secret,
                rest_url=rest_url,
                ws_url=ws_url,
                terminal_path=terminal_path,
                is_active=is_active,
            )
            _log.info("Broker account '%s' (%s) added successfully.", broker_name, account_id)
            return True
        except Exception as e:
            _log.error("Failed to add broker account '%s': %s", broker_name, e)
            return False

    def save_primary_broker_credentials(
        self,
        server: str,
        account_id: str,
        password: str,
        leverage: str = "1:100",
        broker_name: str = "Primary Gateway",
        environment: str = "Demo",
        protocol_type: str = "MT5",
        api_key: str = "",
        api_secret: str = "",
        rest_url: str = "",
        ws_url: str = "",
        terminal_path: str = "",
    ) -> bool:
        """Saves or updates active primary broker credentials in SQLite."""
        try:
            database.save_broker_credentials(
                server=server,
                account_id=account_id,
                password=password,
                leverage=leverage,
                broker_name=broker_name,
                environment=environment,
                protocol_type=protocol_type,
                api_key=api_key,
                api_secret=api_secret,
                rest_url=rest_url,
                ws_url=ws_url,
                terminal_path=terminal_path,
            )
            _log.info("Primary broker credentials updated for '%s'.", broker_name)
            return True
        except Exception as e:
            _log.error("Failed to save primary broker credentials: %s", e)
            return False

    def get_all_brokers(self) -> list[dict[str, Any]]:
        """Retrieves all registered broker profiles with decrypted secrets."""
        return database.get_all_brokers()

    def get_active_broker_credentials(self) -> dict[str, Any] | None:
        """Retrieves the currently active primary broker configuration."""
        return database.get_broker_credentials()

    def set_active_broker(self, broker_id: int) -> bool:
        """Sets a specific broker configuration as active primary gateway."""
        try:
            database.set_active_broker(broker_id)
            _log.info("Set active broker ID: %s", broker_id)
            return True
        except Exception as e:
            _log.error("Failed to set active broker ID %s: %s", broker_id, e)
            return False

    def delete_broker_account(self, broker_id: int) -> bool:
        """Removes a broker profile from database."""
        try:
            database.delete_broker_account(broker_id)
            _log.info("Deleted broker account ID: %s", broker_id)
            return True
        except Exception as e:
            _log.error("Failed to delete broker account ID %s: %s", broker_id, e)
            return False

    def validate_terminal_path(self, terminal_path: str) -> tuple[bool, str]:
        """Validates MT5 executable path for security compliance."""
        try:
            validated = database.validate_terminal_path(terminal_path)
            return (True, validated)
        except ValueError as e:
            return (False, str(e))

    def get_all_broker_profiles(self) -> list[dict[str, Any]]:
        """Retrieves all operational broker profile templates."""
        return database.get_all_broker_profiles()

    def add_broker_profile(
        self,
        broker_key: str,
        display_name: str,
        protocol_type: str = "REST_WS",
        auth_type: str = "api_key_secret",
        rest_url: str = "",
        ws_url: str = "",
        volume_min: float = 0.01,
        volume_max: float = 100.0,
        volume_step: float = 0.01,
        rate_limit_per_sec: int = 10,
        extra_params_json: str = "{}",
        is_active: bool = True,
    ) -> bool:
        """Adds or updates a operational parameter broker profile."""
        try:
            database.add_broker_profile(
                broker_key=broker_key,
                display_name=display_name,
                protocol_type=protocol_type,
                auth_type=auth_type,
                rest_url=rest_url,
                ws_url=ws_url,
                volume_min=volume_min,
                volume_max=volume_max,
                volume_step=volume_step,
                rate_limit_per_sec=rate_limit_per_sec,
                extra_params_json=extra_params_json,
                is_active=is_active,
            )
            return True
        except Exception as e:
            _log.error("Failed to add broker profile: %s", e)
            return False

    # =========================================================================
    # SECURITY & SYSTEM CONFIGURATION
    # =========================================================================

    def get_security_health_status(self) -> dict[str, Any]:
        """Returns security status report including hash migration and cryptography state."""
        migration_status = database.get_credential_migration_status()
        master_key_set = bool(os.environ.get("EQATS_MASTER_KEY"))

        try:
            import cryptography  # type: ignore

            crypto_available = cryptography is not None
        except ImportError:
            crypto_available = False

        bcrypt_available = database._BCRYPT_AVAILABLE

        return {
            "master_key_env_set": master_key_set,
            "cryptography_available": crypto_available,
            "bcrypt_available": bcrypt_available,
            "migration_status": migration_status,
            "overall_security_grade": "SECURE (A+)"
            if (master_key_set and crypto_available and bcrypt_available)
            else "DEGRADED (NEEDS ATTENTION)",
        }

    def reencrypt_all_broker_credentials(self) -> bool:
        """Re-encrypts all broker credentials in database using Fernet master key."""
        try:
            brokers = self.get_all_brokers()
            for b in brokers:
                if b.get("is_active"):
                    self.save_primary_broker_credentials(
                        server=b.get("server", ""),
                        account_id=b.get("account_id", ""),
                        password=b.get("password", ""),
                        leverage=b.get("leverage", "1:100"),
                        broker_name=b.get("broker_name", "Primary Gateway"),
                        environment=b.get("environment", "Demo"),
                        protocol_type=b.get("protocol_type", "MT5"),
                        api_key=b.get("api_key", ""),
                        api_secret=b.get("api_secret", ""),
                        rest_url=b.get("rest_url", ""),
                        ws_url=b.get("ws_url", ""),
                        terminal_path=b.get("terminal_path", ""),
                    )
                else:
                    self.delete_broker_account(b["id"])
                    self.add_broker_account(
                        broker_name=b.get("broker_name", "Gateway"),
                        server=b.get("server", ""),
                        account_id=b.get("account_id", ""),
                        password=b.get("password", ""),
                        leverage=b.get("leverage", "1:100"),
                        environment=b.get("environment", "Demo"),
                        protocol_type=b.get("protocol_type", "MT5"),
                        api_key=b.get("api_key", ""),
                        api_secret=b.get("api_secret", ""),
                        rest_url=b.get("rest_url", ""),
                        ws_url=b.get("ws_url", ""),
                        terminal_path=b.get("terminal_path", ""),
                        is_active=0,
                    )
            _log.info("Re-encrypted %d broker credential records.", len(brokers))
            return True
        except Exception as e:
            _log.error("Re-encryption failed: %s", e)
            return False

    def load_circuit_breaker_state(self) -> dict[str, Any] | None:
        """Retrieves current emergency circuit breaker state."""
        return database.load_circuit_breaker_state()

    def reset_circuit_breaker_halt(self) -> bool:
        """Clears emergency circuit breaker halt status."""
        return database.clear_circuit_breaker_halt()


# =============================================================================
# STANDALONE TKINTER GUI INTERFACE
# =============================================================================


if _TKINTER_AVAILABLE:

    class CredentialManagerGUI:
        """Standalone GUI Application for EQATS Credential and Security Management."""

        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.root.title("EQATS — CREDENTIAL & SECURITY MANAGER")
            self.root.geometry("1000x700")
            self.root.minsize(900, 600)
            self.root.configure(bg="#000000")

            self.cm = CredentialManager()

            self._build_header()
            self._build_tabs()

        def _build_header(self) -> None:
            hdr = tk.Frame(self.root, bg="#05090e", pady=10, padx=20, bd=1, relief=tk.SOLID)
            hdr.pack(fill=tk.X)
            tk.Label(
                hdr,
                text="🔑 EQATS CREDENTIAL & SECURITY MANAGEMENT DESK",
                font=("Consolas", 14, "bold"),
                bg="#05090e",
                fg="#00ffcc",
            ).pack(side=tk.LEFT)
            tk.Label(
                hdr,
                text="STANDALONE CONTROL MODULE",
                font=("Consolas", 9, "bold"),
                bg="#1e40af",
                fg="#ffffff",
                padx=10,
                pady=3,
            ).pack(side=tk.RIGHT)

        def _build_tabs(self) -> None:
            style = ttk.Style()
            style.theme_use("clam")
            style.configure("TNotebook", background="#000000", borderwidth=0)
            style.configure(
                "TNotebook.Tab",
                background="#121212",
                foreground="#ffaa00",
                font=("Consolas", 9, "bold"),
                padding=8,
            )
            style.map(
                "TNotebook.Tab",
                background=[("selected", "#000000")],
                foreground=[("selected", "#00ffcc")],
            )

            self.notebook = ttk.Notebook(self.root, style="TNotebook")
            self.notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

            # Tab 1: User Credentials CRUD
            self.tab_users = tk.Frame(self.notebook, bg="#000000", padx=15, pady=15)
            self.notebook.add(self.tab_users, text="👤 User Accounts (Users Table)")
            self._build_users_tab()

            # Tab 2: Broker & MT5 Credentials
            self.tab_brokers = tk.Frame(self.notebook, bg="#000000", padx=15, pady=15)
            self.notebook.add(self.tab_brokers, text="🏦 Broker & MT5 Credentials")
            self._build_brokers_tab()

            # Tab 3: Security & Circuit Breaker
            self.tab_security = tk.Frame(self.notebook, bg="#000000", padx=15, pady=15)
            self.notebook.add(self.tab_security, text="🛡️ Security & Circuit Breaker")
            self._build_security_tab()

        # -------------------------------------------------------------------------
        # TAB 1: USERS CRUD
        # -------------------------------------------------------------------------
        def _build_users_tab(self) -> None:
            top_frame = tk.Frame(self.tab_users, bg="#000000")
            top_frame.pack(fill=tk.X, pady=(0, 10))

            tk.Button(
                top_frame,
                text="➕ ADD NEW USER",
                font=("Consolas", 9, "bold"),
                bg="#15803d",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._dialog_add_user,
            ).pack(side=tk.LEFT, padx=(0, 5))

            tk.Button(
                top_frame,
                text="✏️ EDIT USER",
                font=("Consolas", 9, "bold"),
                bg="#1d4ed8",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._dialog_edit_user,
            ).pack(side=tk.LEFT, padx=5)

            tk.Button(
                top_frame,
                text="🗑️ DELETE USER",
                font=("Consolas", 9, "bold"),
                bg="#991b1b",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._action_delete_user,
            ).pack(side=tk.LEFT, padx=5)

            tk.Button(
                top_frame,
                text="🔄 RESET ADMIN CREDENTIALS",
                font=("Consolas", 9, "bold"),
                bg="#b45309",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._action_reset_admin,
            ).pack(side=tk.RIGHT)

            cols = ("ID", "Username", "Role", "MFA Enabled", "Created At")
            self.users_tree = ttk.Treeview(self.tab_users, columns=cols, show="headings", height=12)
            for c in cols:
                self.users_tree.heading(c, text=c)
                self.users_tree.column(c, anchor=tk.CENTER, width=120)
            self.users_tree.column("Username", anchor=tk.W, width=180)
            self.users_tree.column("Created At", anchor=tk.W, width=200)
            self.users_tree.pack(fill=tk.BOTH, expand=True)

            self._refresh_users_tree()

        def _refresh_users_tree(self) -> None:
            self.users_tree.delete(*self.users_tree.get_children())
            users = self.cm.get_all_users()
            for u in users:
                self.users_tree.insert(
                    "",
                    tk.END,
                    values=(
                        u["id"],
                        u["username"],
                        u["role"],
                        "ENABLED" if u.get("mfa_enabled") else "DISABLED",
                        u.get("created_at", "-"),
                    ),
                )

        def _dialog_add_user(self) -> None:
            win = tk.Toplevel(self.root)
            win.title("ADD NEW USER ACCOUNT")
            win.geometry("400x320")
            win.configure(bg="#121212")

            tk.Label(
                win,
                text="USERNAME:",
                font=("Consolas", 9, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", padx=20, pady=(15, 2))
            ent_user = tk.Entry(win, font=("Consolas", 10), bg="#000000", fg="#ffffff")
            ent_user.pack(fill=tk.X, padx=20)

            tk.Label(
                win,
                text="PASSWORD:",
                font=("Consolas", 9, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", padx=20, pady=(10, 2))
            ent_pass = tk.Entry(win, show="*", font=("Consolas", 10), bg="#000000", fg="#ffffff")
            ent_pass.pack(fill=tk.X, padx=20)

            tk.Label(
                win,
                text="SECONDARY MFA PIN:",
                font=("Consolas", 9, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", padx=20, pady=(10, 2))
            ent_pin = tk.Entry(win, show="*", font=("Consolas", 10), bg="#000000", fg="#ffffff")
            ent_pin.pack(fill=tk.X, padx=20)

            tk.Label(
                win,
                text="ROLE:",
                font=("Consolas", 9, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", padx=20, pady=(10, 2))
            role_var = tk.StringVar(value="QUANT_TRADER")
            role_menu = tk.OptionMenu(
                win, role_var, "QUANT_TRADER", "SOVEREIGN_ADMIN", "RISK_AUDITOR"
            )
            role_menu.config(font=("Consolas", 9), bg="#1c1c1c", fg="#ffffff")
            role_menu.pack(fill=tk.X, padx=20)

            def submit() -> None:
                u = ent_user.get().strip()
                p = ent_pass.get().strip()
                pin = ent_pin.get().strip()
                if self.cm.add_user(u, p, pin, role=role_var.get()):
                    messagebox.showinfo("Success", f"User '{u}' created successfully!")
                    self._refresh_users_tree()
                    win.destroy()
                else:
                    messagebox.showerror("Error", "Failed to create user.")

            tk.Button(
                win,
                text="SUBMIT",
                font=("Consolas", 10, "bold"),
                bg="#15803d",
                fg="#ffffff",
                command=submit,
            ).pack(pady=15)

        def _dialog_edit_user(self) -> None:
            selected = self.users_tree.selection()
            if not selected:
                messagebox.showwarning("Warning", "Select a user from the list first.")
                return
            item = self.users_tree.item(selected[0])
            old_username = item["values"][1]

            win = tk.Toplevel(self.root)
            win.title(f"EDIT USER — {old_username}")
            win.geometry("400x320")
            win.configure(bg="#121212")

            tk.Label(
                win,
                text=f"NEW USERNAME (current: {old_username}):",
                font=("Consolas", 9, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", padx=20, pady=(15, 2))
            ent_user = tk.Entry(win, font=("Consolas", 10), bg="#000000", fg="#ffffff")
            ent_user.insert(0, old_username)
            ent_user.pack(fill=tk.X, padx=20)

            tk.Label(
                win,
                text="NEW PASSWORD (leave blank to keep current):",
                font=("Consolas", 9, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", padx=20, pady=(10, 2))
            ent_pass = tk.Entry(win, show="*", font=("Consolas", 10), bg="#000000", fg="#ffffff")
            ent_pass.pack(fill=tk.X, padx=20)

            tk.Label(
                win,
                text="NEW PIN (leave blank to keep current):",
                font=("Consolas", 9, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", padx=20, pady=(10, 2))
            ent_pin = tk.Entry(win, show="*", font=("Consolas", 10), bg="#000000", fg="#ffffff")
            ent_pin.pack(fill=tk.X, padx=20)

            tk.Label(
                win,
                text="ROLE:",
                font=("Consolas", 9, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", padx=20, pady=(10, 2))
            role_var = tk.StringVar(value=item["values"][2])
            role_menu = tk.OptionMenu(
                win, role_var, "QUANT_TRADER", "SOVEREIGN_ADMIN", "RISK_AUDITOR"
            )
            role_menu.config(font=("Consolas", 9), bg="#1c1c1c", fg="#ffffff")
            role_menu.pack(fill=tk.X, padx=20)

            def submit() -> None:
                new_u = ent_user.get().strip()
                new_p = ent_pass.get().strip() or None
                new_pin = ent_pin.get().strip() or None
                if self.cm.update_user(
                    username=old_username,
                    new_password=new_p,
                    new_pin=new_pin,
                    new_role=role_var.get(),
                    new_username=new_u,
                ):
                    messagebox.showinfo("Success", f"User '{old_username}' updated successfully!")
                    self._refresh_users_tree()
                    win.destroy()
                else:
                    messagebox.showerror("Error", "Failed to update user.")

            tk.Button(
                win,
                text="SAVE CHANGES",
                font=("Consolas", 10, "bold"),
                bg="#1d4ed8",
                fg="#ffffff",
                command=submit,
            ).pack(pady=15)

        def _action_delete_user(self) -> None:
            selected = self.users_tree.selection()
            if not selected:
                messagebox.showwarning("Warning", "Select a user from the list first.")
                return
            item = self.users_tree.item(selected[0])
            username = item["values"][1]
            if messagebox.askyesno("Confirm Delete", f"Delete user account '{username}'?"):
                if self.cm.delete_user(username):
                    messagebox.showinfo("Deleted", f"User '{username}' deleted.")
                    self._refresh_users_tree()
                else:
                    messagebox.showerror("Error", "Failed to delete user.")

        def _action_reset_admin(self) -> None:
            if messagebox.askyesno(
                "Confirm Reset",
                "Reset QUANT_OPERATOR admin user to default password 'admin' & PIN '741295'?",
            ):
                if self.cm.reset_admin_credentials():
                    messagebox.showinfo(
                        "Reset Complete", "QUANT_OPERATOR credentials reset to default."
                    )
                    self._refresh_users_tree()
                else:
                    messagebox.showerror("Error", "Failed to reset admin credentials.")

        # -------------------------------------------------------------------------
        # TAB 2: BROKER & MT5 CREDENTIALS CRUD
        # -------------------------------------------------------------------------
        def _build_brokers_tab(self) -> None:
            top_frame = tk.Frame(self.tab_brokers, bg="#000000")
            top_frame.pack(fill=tk.X, pady=(0, 10))

            tk.Button(
                top_frame,
                text="➕ ADD BROKER ACCOUNT",
                font=("Consolas", 9, "bold"),
                bg="#15803d",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._dialog_add_broker,
            ).pack(side=tk.LEFT, padx=(0, 5))

            tk.Button(
                top_frame,
                text="⭐ SET ACTIVE GATEWAY",
                font=("Consolas", 9, "bold"),
                bg="#1d4ed8",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._action_set_active_broker,
            ).pack(side=tk.LEFT, padx=5)

            tk.Button(
                top_frame,
                text="🗑️ DELETE BROKER",
                font=("Consolas", 9, "bold"),
                bg="#991b1b",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._action_delete_broker,
            ).pack(side=tk.LEFT, padx=5)

            cols = ("ID", "Broker Name", "Server", "Account ID", "Leverage", "Protocol", "Active")
            self.brokers_tree = ttk.Treeview(
                self.tab_brokers, columns=cols, show="headings", height=12
            )
            for c in cols:
                self.brokers_tree.heading(c, text=c)
                self.brokers_tree.column(c, anchor=tk.CENTER, width=110)
            self.brokers_tree.column("Broker Name", anchor=tk.W, width=160)
            self.brokers_tree.column("Server", anchor=tk.W, width=160)
            self.brokers_tree.pack(fill=tk.BOTH, expand=True)

            self._refresh_brokers_tree()

        def _refresh_brokers_tree(self) -> None:
            self.brokers_tree.delete(*self.brokers_tree.get_children())
            brokers = self.cm.get_all_brokers()
            for b in brokers:
                self.brokers_tree.insert(
                    "",
                    tk.END,
                    values=(
                        b["id"],
                        b.get("broker_name", "Gateway"),
                        b.get("server", ""),
                        b.get("account_id", ""),
                        b.get("leverage", "1:100"),
                        b.get("protocol_type", "MT5"),
                        "★ ACTIVE PRIMARY" if b.get("is_active") else "INACTIVE",
                    ),
                )

        def _dialog_add_broker(self) -> None:
            win = tk.Toplevel(self.root)
            win.title("ADD BROKER / MT5 ACCOUNT")
            win.geometry("450x520")
            win.configure(bg="#121212")

            fields = [
                ("BROKER NAME:", "broker_name", "Primary Gateway"),
                ("SERVER:", "server", "MetaQuotes-Demo"),
                ("ACCOUNT ID:", "account_id", "12345678"),
                ("PASSWORD:", "password", "Password123"),
                ("LEVERAGE (e.g. 1:100 or 1:500):", "leverage", "1:100"),
                ("PROTOCOL TYPE (MT5/REST_WS/FIX/CCXT):", "protocol_type", "MT5"),
                ("TERMINAL PATH (optional MT5 terminal64.exe):", "terminal_path", ""),
            ]

            entries = {}
            for label, key, default in fields:
                tk.Label(
                    win,
                    text=label,
                    font=("Consolas", 8, "bold"),
                    bg="#121212",
                    fg="#00ffcc",
                ).pack(anchor="w", padx=20, pady=(8, 2))
                show_char = "*" if key == "password" else ""
                ent = tk.Entry(
                    win, show=show_char, font=("Consolas", 9), bg="#000000", fg="#ffffff"
                )
                ent.insert(0, default)
                ent.pack(fill=tk.X, padx=20)
                entries[key] = ent

            def submit() -> None:
                if self.cm.add_broker_account(
                    broker_name=entries["broker_name"].get().strip(),
                    server=entries["server"].get().strip(),
                    account_id=entries["account_id"].get().strip(),
                    password=entries["password"].get().strip(),
                    leverage=entries["leverage"].get().strip(),
                    protocol_type=entries["protocol_type"].get().strip(),
                    terminal_path=entries["terminal_path"].get().strip(),
                    is_active=1,
                ):
                    messagebox.showinfo("Success", "Broker account added and set active!")
                    self._refresh_brokers_tree()
                    win.destroy()
                else:
                    messagebox.showerror("Error", "Failed to add broker account.")

            tk.Button(
                win,
                text="SAVE BROKER",
                font=("Consolas", 10, "bold"),
                bg="#15803d",
                fg="#ffffff",
                command=submit,
            ).pack(pady=15)

        def _action_set_active_broker(self) -> None:
            selected = self.brokers_tree.selection()
            if not selected:
                messagebox.showwarning("Warning", "Select a broker entry first.")
                return
            item = self.brokers_tree.item(selected[0])
            b_id = item["values"][0]
            if self.cm.set_active_broker(b_id):
                messagebox.showinfo(
                    "Active Gateway Set", f"Broker ID {b_id} set as active primary gateway."
                )
                self._refresh_brokers_tree()
            else:
                messagebox.showerror("Error", "Failed to set active broker.")

        def _action_delete_broker(self) -> None:
            selected = self.brokers_tree.selection()
            if not selected:
                messagebox.showwarning("Warning", "Select a broker entry first.")
                return
            item = self.brokers_tree.item(selected[0])
            b_id = item["values"][0]
            if messagebox.askyesno("Confirm Delete", f"Delete broker entry ID {b_id}?"):
                if self.cm.delete_broker_account(b_id):
                    messagebox.showinfo("Deleted", f"Broker ID {b_id} deleted.")
                    self._refresh_brokers_tree()
                else:
                    messagebox.showerror("Error", "Failed to delete broker.")

        # -------------------------------------------------------------------------
        # TAB 3: SECURITY & CIRCUIT BREAKER CONTROLS
        # -------------------------------------------------------------------------
        def _build_security_tab(self) -> None:
            frame_sec = tk.Frame(
                self.tab_security, bg="#121212", bd=1, relief=tk.SOLID, padx=15, pady=15
            )
            frame_sec.pack(fill=tk.X, pady=(0, 15))

            tk.Label(
                frame_sec,
                text="🛡️ SYSTEM SECURITY & ENCRYPTION HEALTH DIAGNOSTICS",
                font=("Consolas", 10, "bold"),
                bg="#121212",
                fg="#00ffcc",
            ).pack(anchor="w", pady=(0, 10))

            sec_status = self.cm.get_security_health_status()
            info_text = (
                f"Overall Grade:              {sec_status['overall_security_grade']}\n"
                f"EQATS_MASTER_KEY Env:       {sec_status['master_key_env_set']}\n"
                f"Cryptography Fernet:        {sec_status['cryptography_available']}\n"
                f"bcrypt Work Factor (12):    {sec_status['bcrypt_available']}\n"
                f"Credentials Migration Complete: {sec_status['migration_status']['migration_complete']}\n"
                f"Total Operator Accounts:    {sec_status['migration_status']['total_users']}"
            )

            tk.Label(
                frame_sec,
                text=info_text,
                font=("Consolas", 9),
                bg="#121212",
                fg="#ffffff",
                justify=tk.LEFT,
            ).pack(anchor="w", pady=(0, 10))

            tk.Button(
                frame_sec,
                text="🔐 RE-ENCRYPT ALL BROKER CREDENTIALS",
                font=("Consolas", 9, "bold"),
                bg="#1d4ed8",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._action_reencrypt_credentials,
            ).pack(anchor="w")

            # Circuit Breaker Section
            frame_cb = tk.Frame(
                self.tab_security, bg="#121212", bd=1, relief=tk.SOLID, padx=15, pady=15
            )
            frame_cb.pack(fill=tk.X)

            tk.Label(
                frame_cb,
                text="⚡ EMERGENCY CIRCUIT BREAKER STATE & HALT RESET",
                font=("Consolas", 10, "bold"),
                bg="#121212",
                fg="#ffaa00",
            ).pack(anchor="w", pady=(0, 10))

            cb_state = self.cm.load_circuit_breaker_state()
            if cb_state:
                cb_info = (
                    f"Trading Date:       {cb_state['trading_date']}\n"
                    f"Daily Baseline:     ${cb_state['daily_start_balance']:,.2f}\n"
                    f"Is Halted:          {'🔴 YES (HALTED)' if cb_state['is_halted'] else '🟢 NO (NORMAL)'}\n"
                    f"Halt Reason:        {cb_state.get('halt_reason', 'None')}"
                )
            else:
                cb_info = "No circuit breaker state recorded in database."

            tk.Label(
                frame_cb,
                text=cb_info,
                font=("Consolas", 9),
                bg="#121212",
                fg="#ffffff",
                justify=tk.LEFT,
            ).pack(anchor="w", pady=(0, 10))

            tk.Button(
                frame_cb,
                text="🔄 RESET CIRCUIT BREAKER HALT",
                font=("Consolas", 9, "bold"),
                bg="#b45309",
                fg="#ffffff",
                padx=10,
                pady=5,
                relief=tk.FLAT,
                command=self._action_reset_cb,
            ).pack(anchor="w")

        def _action_reencrypt_credentials(self) -> None:
            if messagebox.askyesno(
                "Confirm Re-encryption",
                "Re-encrypt all broker credentials in database using current master key?",
            ):
                if self.cm.reencrypt_all_broker_credentials():
                    messagebox.showinfo(
                        "Success", "All broker credentials re-encrypted successfully."
                    )
                else:
                    messagebox.showerror("Error", "Re-encryption failed.")

        def _action_reset_cb(self) -> None:
            if messagebox.askyesno(
                "Confirm Reset",
                "Clear emergency circuit breaker halt status and resume trading admissions?",
            ):
                if self.cm.reset_circuit_breaker_halt():
                    messagebox.showinfo("Reset Complete", "Circuit breaker halt cleared.")
                else:
                    messagebox.showwarning("Notice", "No halt was active or reset failed.")

else:
    CredentialManagerGUI = None  # type: ignore


# =============================================================================
# CLI INTERFACE & ENTRYPOINT
# =============================================================================


def _run_interactive_cli(cm: CredentialManager) -> None:
    """Runs interactive CLI menu for credential and security management."""
    print("================================================================================")
    print("  EQATS CREDENTIAL & SECURITY MANAGER — INTERACTIVE CLI")
    print("================================================================================")
    while True:
        print("\nMain Menu:")
        print("  1. List User Accounts")
        print("  2. Add New User Account")
        print("  3. Update User Password / PIN / Role")
        print("  4. Delete User Account")
        print("  5. Reset System Admin (QUANT_OPERATOR)")
        print("  6. List Broker & MT5 Credentials")
        print("  7. Add / Update Broker Credentials")
        print("  8. Set Active Broker Gateway")
        print("  9. Delete Broker Account")
        print(" 10. Check Security & Hash Health")
        print(" 11. Re-encrypt All Broker Credentials")
        print(" 12. View / Reset Circuit Breaker State")
        print(" 13. Launch Standalone GUI")
        print("  0. Exit")

        choice = input("\nSelect option [0-13]: ").strip()
        if choice == "0":
            print("Exiting Credential Manager CLI.")
            break
        if choice == "1":
            users = cm.get_all_users()
            print(f"\nFound {len(users)} user(s):")
            for u in users:
                print(
                    f"  ID: {u['id']} | Username: {u['username']} | Role: {u['role']} | MFA: {u.get('mfa_enabled')}"
                )
        elif choice == "2":
            u = input("Username: ").strip()
            p = input("Password: ").strip()
            pin = input("Secondary MFA PIN: ").strip()
            r = input("Role [QUANT_TRADER/SOVEREIGN_ADMIN]: ").strip() or "QUANT_TRADER"
            if cm.add_user(u, p, pin, role=r):
                print(f"✓ User '{u}' created.")
            else:
                print("✗ Failed to create user.")
        elif choice == "3":
            u = input("Target Username: ").strip()
            p = input("New Password (blank to skip): ").strip() or None
            pin = input("New PIN (blank to skip): ").strip() or None
            r = input("New Role (blank to skip): ").strip() or None
            if cm.update_user(u, new_password=p, new_pin=pin, new_role=r):
                print(f"✓ User '{u}' updated.")
            else:
                print("✗ Failed to update user.")
        elif choice == "4":
            u = input("Username to delete: ").strip()
            if cm.delete_user(u):
                print(f"✓ User '{u}' deleted.")
            else:
                print("✗ Failed to delete user.")
        elif choice == "5":
            p = input("New Admin Password [default: admin]: ").strip() or "admin"
            pin = input("New Admin PIN [default: 741295]: ").strip() or "741295"
            if cm.reset_admin_credentials(new_password=p, new_pin=pin):
                print("✓ QUANT_OPERATOR admin credentials reset.")
            else:
                print("✗ Failed to reset admin credentials.")
        elif choice == "6":
            brokers = cm.get_all_brokers()
            print(f"\nFound {len(brokers)} broker configuration(s):")
            for b in brokers:
                active_str = " [PRIMARY ACTIVE]" if b.get("is_active") else ""
                print(
                    f"  ID: {b['id']} | Name: {b.get('broker_name')} | Account: {b.get('account_id')} | Server: {b.get('server')}{active_str}"
                )
        elif choice == "7":
            name = input("Broker Name [Primary Gateway]: ").strip() or "Primary Gateway"
            server = input("Server [MetaQuotes-Demo]: ").strip() or "MetaQuotes-Demo"
            acc = input("Account ID: ").strip()
            pwd = input("Password: ").strip()
            lev = input("Leverage [1:100]: ").strip() or "1:100"
            proto = input("Protocol [MT5/REST_WS/FIX/CCXT]: ").strip() or "MT5"
            term = input("Terminal Path (optional): ").strip()
            if cm.add_broker_account(
                broker_name=name,
                server=server,
                account_id=acc,
                password=pwd,
                leverage=lev,
                protocol_type=proto,
                terminal_path=term,
                is_active=1,
            ):
                print("✓ Broker account saved and set active.")
            else:
                print("✗ Failed to save broker account.")
        elif choice == "8":
            b_id = input("Broker ID to set active: ").strip()
            if b_id.isdigit() and cm.set_active_broker(int(b_id)):
                print(f"✓ Broker ID {b_id} set as active primary gateway.")
            else:
                print("✗ Failed to set active broker.")
        elif choice == "9":
            b_id = input("Broker ID to delete: ").strip()
            if b_id.isdigit() and cm.delete_broker_account(int(b_id)):
                print(f"✓ Broker ID {b_id} deleted.")
            else:
                print("✗ Failed to delete broker account.")
        elif choice == "10":
            health = cm.get_security_health_status()
            print("\nSecurity Diagnostics Report:")
            print(f"  Overall Grade:                  {health['overall_security_grade']}")
            print(f"  EQATS_MASTER_KEY Env Set:       {health['master_key_env_set']}")
            print(f"  Cryptography Fernet Available:  {health['cryptography_available']}")
            print(f"  bcrypt 12-round Available:      {health['bcrypt_available']}")
            print(
                f"  Migration Status Complete:      {health['migration_status']['migration_complete']}"
            )
        elif choice == "11":
            if cm.reencrypt_all_broker_credentials():
                print("✓ All broker credentials re-encrypted.")
            else:
                print("✗ Re-encryption failed.")
        elif choice == "12":
            cb = cm.load_circuit_breaker_state()
            if cb:
                print(
                    f"\nCircuit Breaker State: Halted={cb['is_halted']}, Date={cb['trading_date']}, Baseline=${cb['daily_start_balance']:,.2f}"
                )
                if cb["is_halted"]:
                    ans = input("Clear halt status now? (y/N): ").strip().lower()
                    if ans == "y":
                        cm.reset_circuit_breaker_halt()
                        print("✓ Circuit breaker halt cleared.")
            else:
                print("No circuit breaker state logged.")
        elif choice == "13":
            if _TKINTER_AVAILABLE and CredentialManagerGUI:
                root = tk.Tk()
                CredentialManagerGUI(root)
                root.mainloop()
            else:
                print("✗ Tkinter is not installed or GUI is unavailable in this environment.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EQATS Credential & Security Management CLI Utility"
    )
    parser.add_argument("--gui", action="store_true", help="Launch standalone GUI application")
    parser.add_argument(
        "--list-users", action="store_true", help="List all registered user accounts"
    )
    parser.add_argument("--add-user", action="store_true", help="Add a new user account")
    parser.add_argument("--username", type=str, help="Username parameter")
    parser.add_argument("--password", type=str, help="Password parameter")
    parser.add_argument("--pin", type=str, help="PIN parameter")
    parser.add_argument("--role", type=str, default="QUANT_TRADER", help="User role parameter")
    parser.add_argument(
        "--reset-admin", action="store_true", help="Reset QUANT_OPERATOR admin user to default"
    )
    parser.add_argument("--list-brokers", action="store_true", help="List all broker profiles")
    parser.add_argument(
        "--reset-circuit-breaker", action="store_true", help="Clear emergency circuit breaker halt"
    )
    parser.add_argument(
        "--check-security", action="store_true", help="Check security diagnostics and health grade"
    )

    args = parser.parse_args()
    cm = CredentialManager()

    if args.gui:
        if _TKINTER_AVAILABLE and CredentialManagerGUI:
            root = tk.Tk()
            CredentialManagerGUI(root)
            root.mainloop()
        else:
            print("Error: Tkinter library is not available in this environment.")
            sys.exit(1)
    elif args.list_users:
        users = cm.get_all_users()
        print(f"Total Users: {len(users)}")
        for u in users:
            print(f"  - ID: {u['id']} | Username: {u['username']} | Role: {u['role']}")
    elif args.add_user:
        if not args.username or not args.password or not args.pin:
            print("Error: --username, --password, and --pin are required to add user.")
            sys.exit(1)
        if cm.add_user(args.username, args.password, args.pin, role=args.role):
            print(f"User '{args.username}' created successfully.")
        else:
            print(f"Failed to create user '{args.username}'.")
    elif args.reset_admin:
        new_pass = args.password or "admin"
        new_pin = args.pin or "741295"
        if cm.reset_admin_credentials(new_password=new_pass, new_pin=new_pin):
            print("QUANT_OPERATOR credentials reset successfully.")
        else:
            print("Failed to reset QUANT_OPERATOR credentials.")
    elif args.list_brokers:
        brokers = cm.get_all_brokers()
        print(f"Total Brokers: {len(brokers)}")
        for b in brokers:
            active_str = " (ACTIVE)" if b.get("is_active") else ""
            print(
                f"  - ID: {b['id']} | Name: {b.get('broker_name')} | Account: {b.get('account_id')}{active_str}"
            )
    elif args.reset_circuit_breaker:
        if cm.reset_circuit_breaker_halt():
            print("Circuit breaker halt cleared.")
        else:
            print("No halt active or reset failed.")
    elif args.check_security:
        diag = cm.get_security_health_status()
        print("Security Health Report:")
        print(f"  Overall Security Grade: {diag['overall_security_grade']}")
        print(f"  bcrypt 12-round:        {diag['bcrypt_available']}")
        print(f"  Fernet Cryptography:    {diag['cryptography_available']}")
        print(f"  Master Key Set:         {diag['master_key_env_set']}")
    else:
        # If run with no CLI flags, start interactive CLI
        _run_interactive_cli(cm)


if __name__ == "__main__":
    main()
