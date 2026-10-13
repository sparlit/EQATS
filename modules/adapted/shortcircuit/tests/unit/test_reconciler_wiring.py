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
The reconciler has to be told which positions are ours.

`TradeManager.reconciliation_engine` was initialised to None and never assigned
by anything. Every call site guarded it with `getattr(..., None)` and moved on,
so entry could not call `mark_dirty()` or `mark_recently_modified()` and nothing
anywhere said so. Over 7-10 Sep 2026 that produced:

  * 1,031 CRITICAL "DISCREPANCY: Orphans=1" — the reconciler comparing live
    positions against a DB snapshot last refreshed before the market opened, and
    a `reconciliation_log` INSERT every 6 seconds;
  * 16 QTY MISMATCH alerts on NSE:RAYMOND-EQ after its own partial;
  * NSE:RAYMOND-EQ adopted as a "manual entry" 541ms after the bot placed it,
    with a "TWO POSITIONS OPEN — CRITICAL, close one manually" alert about a
    single position.

`Suppressed orphan` appears zero times in four days of logs, which is how the
dead wire was found.
"""

import ast
import pathlib

from shortcircuit.execution.order_manager import OrderManager

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "shortcircuit"


class _Engine:
    def __init__(self):
        self.dirty = 0
        self.modified: list[str] = []

    def mark_dirty(self):
        self.dirty += 1

    def mark_recently_modified(self, symbol):
        self.modified.append(symbol)


class _TradeManager:
    def __init__(self, engine=None):
        self.reconciliation_engine = engine


# ── the notification itself ──────────────────────────────────────────────────


def test_the_reconciler_is_told_when_we_touch_a_symbol():
    engine = _Engine()
    om = OrderManager(broker=None, telegram_bot=None, trade_manager=_TradeManager(engine))

    om._notify_reconciler("NSE:X-EQ", dirty=True)

    assert engine.dirty == 1
    assert engine.modified == ["NSE:X-EQ"]


def test_the_grace_marker_can_be_set_without_dirtying_the_db_cache():
    """Pre-execution claims the symbol before any DB row exists to refresh."""
    engine = _Engine()
    om = OrderManager(broker=None, telegram_bot=None, trade_manager=_TradeManager(engine))

    om._notify_reconciler("NSE:X-EQ")

    assert engine.dirty == 0
    assert engine.modified == ["NSE:X-EQ"]


def test_a_missing_engine_is_reported_not_swallowed(caplog):
    """The regression. Silence here cost four days of false CRITICALs."""
    om = OrderManager(broker=None, telegram_bot=None, trade_manager=_TradeManager(None))

    with caplog.at_level("ERROR"):
        om._notify_reconciler("NSE:X-EQ", dirty=True)

    assert any("[WIRING]" in r.message for r in caplog.records), (
        "an unwired reconciler is a deployment fault and must say so"
    )


def test_the_missing_engine_warning_does_not_spam(caplog):
    om = OrderManager(broker=None, telegram_bot=None, trade_manager=_TradeManager(None))

    with caplog.at_level("ERROR"):
        for _ in range(50):
            om._notify_reconciler("NSE:X-EQ")

    assert sum("[WIRING]" in r.message for r in caplog.records) == 1


def test_no_trade_manager_at_all_is_survivable():
    OrderManager(broker=None, telegram_bot=None, trade_manager=None)._notify_reconciler("NSE:X-EQ")


# ── the wiring that has to exist for any of the above to run in production ───


def _assigns_reconciliation_engine(path: pathlib.Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "reconciliation_engine"
                and isinstance(target.value, ast.Name)
                and target.value.id == "trade_manager"
            ):
                return True
    return False


def test_the_supervisor_back_injects_the_engine():
    """
    Static, because the failure mode is that this line does not exist. A unit
    test on OrderManager passes happily while production is unwired — that is
    exactly the gap the 7-10 Sep sessions fell through.
    """
    assert _assigns_reconciliation_engine(SRC / "runtime" / "supervisor.py"), (
        "supervisor must set trade_manager.reconciliation_engine; without it "
        "orphan suppression is inactive for the whole session"
    )


def test_entry_claims_the_symbol_before_placing_the_order():
    """
    The grace window has to open before the order exists. A fill can land at the
    broker milliseconds after placement and a reconcile cycle can see it before
    enter_position has registered anything.
    """
    src = (SRC / "execution" / "order_manager.py").read_text()
    pre_exec = src.index("[PRE-EXEC]")
    notify = src.index("_notify_reconciler", pre_exec)
    place = src.index("await self.broker.place_order", pre_exec)
    assert notify < place, "the reconciler must be told about the symbol before the order is placed"
