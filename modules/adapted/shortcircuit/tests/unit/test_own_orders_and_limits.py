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
Three ways the bot mistook itself, or the broker's budget, for something else.

All three showed up in the 7-10 Sep 2026 sessions:

  * NSE:ASIANENE-EQ, 8 Sep — the bot stood down 131ms after its own TP-1 partial
    filled, because manual-override detection compared every working order
    against the stop's id alone. Its own exit order was indistinguishable from
    the operator's.
  * 54 leverage lookups failed, all HTTP 429, on a `requests.post` that never
    took a rate-limit token.
  * The depth call runs once per candidate, concurrently across a scan, and was
    likewise unmetered — so the limiter's HIGH-priority reserve was protecting a
    budget that had already been spent behind its back.
"""

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "shortcircuit"


# ── a bot order is not an override ───────────────────────────────────────────


def test_every_placed_order_id_is_remembered():
    """
    Membership of `bot_order_ids` is the only honest test of "did we place this".
    It has to be written on the success path of place_order, which every order
    in the process goes through.
    """
    src = (SRC / "broker" / "fyers_broker_interface.py").read_text()
    assert "self.bot_order_ids: set[str] = set()" in src, "the set must exist"

    ok_branch = src.index("if isinstance(response, dict) and response.get('s') == 'ok':")
    returned = src.index("return order_id", ok_branch)
    remembered = src.index("self.bot_order_ids.add(order_id)", ok_branch)
    assert remembered < returned, (
        "the id must be recorded before place_order hands it back, or a fast "
        "reconcile can see the order before we admit to owning it"
    )


def test_override_detection_consults_the_bot_order_set():
    src = (SRC / "execution" / "order_manager.py").read_text()
    start = src.index("# Manual-override detection")
    end = src.index("manual_override_detected and not pos.get('manual_override')")
    block = src[start:end]
    assert "bot_order_ids" in block, (
        "without this the bot's own partial-exit order reads as operator "
        "intervention and it stops managing a position it is mid-way through "
        "scaling out of"
    )


def test_an_operator_stop_drag_is_still_an_override():
    """The fix must not disarm the detector — rule 2 has to survive."""
    src = (SRC / "execution" / "order_manager.py").read_text()
    start = src.index("# Manual-override detection")
    end = src.index("manual_override_detected and not pos.get('manual_override')")
    block = src[start:end]
    assert "stopPrice" in block and "internal_sl" in block, (
        "a stop the operator dragged keeps its id, so the price comparison is "
        "the only thing that catches it"
    )


# ── nothing may spend the broker's budget without telling the limiter ────────


def _calls_in(path: pathlib.Path, attr: str) -> list[int]:
    """Line numbers of every `<something>.<attr>(...)` call in the file."""
    tree = ast.parse(path.read_text())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
    ]


def _acquires_within(path: pathlib.Path, lineno: int, window: int = 12) -> bool:
    lines = path.read_text().splitlines()
    before = lines[max(0, lineno - window - 1) : lineno]
    return any("rest_limiter.acquire" in ln for ln in before)


def test_the_5hz_position_check_is_metered():
    """
    Runs from the focus loop on every websocket cache miss. Unmetered, one open
    position could outspend the entire per-second budget on its own.
    """
    path = SRC / "execution" / "focus_engine.py"
    for lineno in _calls_in(path, "positions"):
        assert _acquires_within(path, lineno), (
            f"focus_engine.py:{lineno} calls positions() without a token"
        )


def test_the_per_candidate_depth_call_is_metered():
    path = SRC / "execution" / "analyzer.py"
    for lineno in _calls_in(path, "depth"):
        assert _acquires_within(path, lineno), (
            f"analyzer.py:{lineno} calls depth() without a token; a scan fires "
            f"one of these per candidate, concurrently"
        )


def test_the_trade_manager_position_reads_are_metered():
    path = SRC / "execution" / "trade_manager.py"
    for lineno in _calls_in(path, "positions"):
        assert _acquires_within(path, lineno), (
            f"trade_manager.py:{lineno} calls positions() without a token"
        )


def test_the_leverage_lookup_is_metered():
    """
    A bare requests.post, so it bypasses the SDK entirely — but it spends the
    same account-wide budget. All 54 of its failures over 7-10 Sep were 429s.
    """
    path = SRC / "broker" / "fyers_broker_interface.py"
    src = path.read_text()
    post = src.index('requests.post(f"{base}/multiorder/margin"')
    preceding = src[max(0, post - 500) : post]
    assert "rest_limiter.acquire" in preceding


def test_the_adoption_orderbook_read_is_metered():
    """Runs while placing an emergency stop — the worst moment to be throttled."""
    path = SRC / "state" / "reconciliation.py"
    src = path.read_text()
    call = src.index("asyncio.to_thread(client.orderbook)")
    preceding = src[max(0, call - 300) : call]
    assert "rest_limiter.acquire" in preceding
