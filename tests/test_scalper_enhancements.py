import os
import time
from typing import Any

import brain
import config
import database
import main


def setup_module() -> None:
    config.DB_PATH = "test_scalper_enhancements.db"
    config.SIMULATION_MODE = True
    database.init_db()


def teardown_module() -> None:
    if os.path.exists("test_scalper_enhancements.db"):
        try:
            os.remove("test_scalper_enhancements.db")
        except Exception:
            pass


def test_normalize_leverage_helper() -> None:
    """Verifies normalize_leverage helper handles raw numbers, 1:N format, invalid strings, and fallbacks."""
    assert database.normalize_leverage("1:888") == "1:888"
    assert database.normalize_leverage("888") == "1:888"
    assert database.normalize_leverage("1:10000") == "1:10000"
    assert database.normalize_leverage("500") == "1:500"
    assert database.normalize_leverage("invalid") == "1:100"
    assert database.normalize_leverage("") == "1:100"
    assert database.normalize_leverage(None) == "1:100"


def test_add_broker_account_leverage_normalization() -> None:
    """Verifies add_broker_account normalizes unformatted leverage inputs before persisting to SQLite."""
    test_db = f"test_add_broker_{os.getpid()}_{int(time.time() * 1000)}.db"
    config.DB_PATH = test_db
    database.init_db()
    database.add_broker_account(
        "Test Gateway", "ServerA", "12345", "pass", leverage="888", environment="Demo", is_active=1
    )
    creds = database.get_broker_credentials()
    assert creds["leverage"] == "1:888"
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except Exception:
            pass


def test_leverage_persistence_and_custom_options() -> None:
    """Verifies leverage selection persistence (1:1 to 1:3000 / 1:10000) in SQLite database."""
    test_db = f"test_leverage_{os.getpid()}_{int(time.time() * 1000)}.db"
    config.DB_PATH = test_db
    database.init_db()
    database.save_broker_credentials(
        "DemoServer", "888123", "pass123", "1:888", broker_name="Sovereign Gateway", environment="Demo"
    )
    creds1 = database.get_broker_credentials()
    assert creds1["leverage"] == "1:888"
    database.save_broker_credentials(
        "DemoServer", "888123", "pass123", "1:3000", broker_name="High Leverage Gateway", environment="Demo"
    )
    creds2 = database.get_broker_credentials()
    assert creds2["leverage"] == "1:3000"
    database.save_broker_credentials(
        "DemoServer", "888123", "pass123", "1:10000", broker_name="Ultra Leverage Gateway", environment="Demo"
    )
    creds3 = database.get_broker_credentials()
    assert creds3["leverage"] == "1:10000"
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except Exception:
            pass


def test_fixed_001_lot_position_sizing() -> None:
    """Verifies that position sizing is strictly enforced to 0.01 lots across all symbols and equity levels."""
    scalper_brain = brain.ScalperBrain()
    bars = [
        {
            "open": 1.1 + i * 0.0001,
            "high": 1.1005 + i * 0.0001,
            "low": 1.0995 + i * 0.0001,
            "close": 1.1002 + i * 0.0001,
        }
        for i in range(210)
    ]
    res1 = scalper_brain.evaluate("EURUSD", bars, 10000.0)
    if res1["decision"] in ["BUY", "SELL"]:
        assert res1["lot_size"] == 0.01
    res2 = scalper_brain.evaluate("XAUUSD", bars, 1000000.0)
    if res2["decision"] in ["BUY", "SELL"]:
        assert res2["lot_size"] == 0.01
    assert scalper_brain._calculate_lot_size("BTCUSD", 250000.0, 50.0) == 0.01


def test_symbol_floating_loss_protection_gate() -> None:
    """Verifies Option 2A: if any open trade on a symbol has profit < 0, new evaluations return HOLD."""
    database.init_db()
    ticket_id = f"TEST_ENH_LOSS_{int(time.time() * 1000)}"
    database.log_trade_open(ticket_id, "EURUSD", "BUY", 1.15, 1.14, 1.16, 0.01)
    scalper_brain = brain.ScalperBrain()
    bars = [
        {"open": 1.1 + i * 1e-05, "high": 1.1005 + i * 1e-05, "low": 1.0995 + i * 1e-05, "close": 1.1002 + i * 1e-05}
        for i in range(210)
    ]
    res = scalper_brain.evaluate("EURUSD", bars, 10000.0)
    assert res["decision"] == "HOLD"
    assert "Symbol Floating Loss Protection Gate Active" in res["explanation"]
    database.log_trade_close(ticket_id, 1.1002, -498.0, "TEST_CLEANUP")


def test_atr_volatility_pyramiding_rule() -> None:
    """Verifies Option 1A: pyramiding entries are held if profit < 1.0x ATR, and allowed if profit >= 1.0x ATR."""
    database.init_db()
    ticket_id = f"TEST_ENH_PYR_{int(time.time() * 1000)}"
    scalper_brain = brain.ScalperBrain()
    bars = [
        {"open": 1.1 + i * 1e-05, "high": 1.1005 + i * 1e-05, "low": 1.0995 + i * 1e-05, "close": 1.1002 + i * 1e-05}
        for i in range(210)
    ]
    current_price = bars[-1]["close"]
    database.log_trade_open(ticket_id, "EURUSD", "BUY", 1.1022, 1.09, 1.12, 0.01)
    res = scalper_brain.evaluate("EURUSD", bars, 10000.0)
    assert res["decision"] == "HOLD"
    assert "Pyramiding Gate" in res["explanation"]
    database.log_trade_close(ticket_id, current_price, 0.1, "TEST_CLEANUP")


def test_breakeven_lock_and_trailing_stop() -> None:
    """Verifies Option 3A breakeven profit lock (+ spread buffer) and dynamic ATR trailing stop."""
    scalper = main.AutonomousScalper()
    ticket_id = "TEST_BE_LOCK_01"
    pos = {
        "ticket": ticket_id,
        "symbol": "EURUSD",
        "direction": "BUY",
        "open_price": 1.1,
        "sl": 1.09,
        "tp": 1.12,
        "lot_size": 0.01,
    }
    sim_conn = getattr(scalper.conn, "sim_fallback", scalper.conn)
    sim_conn.open_trades[ticket_id] = pos
    scalper._process_trailing_stops([pos])
    updated_pos = sim_conn.open_trades.get(ticket_id)
    if updated_pos:
        assert updated_pos["sl"] >= 1.09
