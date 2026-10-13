from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
What the logs record, and what they must not.

* The Telegram bot token was in plain text in every session log: httpx logs each
  request URL at INFO, and a Bot API URL embeds the token.
* `[ENTRY] ... slippage` printed only when the fill was more than 0.1% from the
  signal price, and measured against the signal price rather than the trigger. The
  0.212% "measured slippage" used in the research was built from those lines; 0.094
  percentage points of it was the move from signal to trigger, which is the trade
  happening, not a cost. Against the trigger it was 0.118%.
"""

import logging
import pathlib

from shortcircuit.runtime.supervisor import _RedactTelegramToken

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "shortcircuit"
FAKE = "bot1234567890:" + "A" * 35


def _record(msg, *args):
    return logging.LogRecord("httpx", logging.INFO, __file__, 1, msg, args or None, None)


def test_a_bot_token_in_a_url_is_masked():
    r = _record("HTTP Request: POST %s", f"https://api.telegram.org/{FAKE}/getUpdates")
    assert _RedactTelegramToken().filter(r) is True
    out = r.getMessage()
    assert FAKE not in out and "bot<redacted>/getUpdates" in out


def test_a_token_inside_an_exception_message_is_masked_too():
    r = _record(f"send failed: ConnectError for url https://api.telegram.org/{FAKE}/sendMessage")
    _RedactTelegramToken().filter(r)
    assert FAKE not in r.getMessage()


def test_ordinary_lines_pass_through_unchanged():
    r = _record("[ENTRY] NSE:KSCL-EQ fill ₹%.2f", 801.45)
    _RedactTelegramToken().filter(r)
    assert r.getMessage() == "[ENTRY] NSE:KSCL-EQ fill ₹801.45"


def test_httpx_is_silenced_below_warning():
    src = (SRC / "runtime" / "supervisor.py").read_text()
    assert 'logging.getLogger("httpx").setLevel(logging.WARNING)' in src
    assert src.count("addFilter(_RedactTelegramToken())") == 2, "file and console handlers"


def test_every_fill_is_logged_against_its_trigger():
    om = (SRC / "execution" / "order_manager.py").read_text()
    fe = (SRC / "execution" / "focus_engine.py").read_text()
    assert "pending['data']['gate_trigger'] = trigger_price" in fe
    assert "vs trigger" in om
    assert "if abs(actual_fill - ltp) / max(ltp, 0.01) > 0.001:" not in om, (
        "logging only large deviations biases every slippage figure read back from the logs"
    )
