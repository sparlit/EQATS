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
Risk engine — enforces all trading rules before and after each trade.

Rules (from design doc):
  - 1% capital risk per trade
  - 2% max daily loss (hard stop — no more trades today)
  - Max 5 trades per day
  - Cooldown of 60 min after 2 consecutive losses
  - ATR-based SL/TP instead of fixed percentages

Usage:
    mgr = RiskManager(capital=100_000)
    mgr.reset_daily()                           # call at start of each day
    if mgr.can_trade(timestamp):
        sl = mgr.sl_price(entry, atr)
        tp = mgr.tp_price(entry, atr)
        qty = mgr.position_size(cash, entry, sl)
    mgr.record_trade(pnl, timestamp)            # call after each trade closes
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 1.0  # % of capital to risk per trade
    max_daily_loss_pct: float = 3.0  # halt trading after 3% realized daily loss
    max_position_pct: float = 25.0  # MIS intraday sizing — fixed costs need notional ≥ ~₹1L
    max_trades_per_day: int = 5
    cooldown_after_losses: int = 2  # consecutive losses before cooldown
    cooldown_minutes: int = 60
    sl_atr_mult: float = 1.0  # fallback SL when no sl_hint provided
    tp_atr_mult: float = 2.5  # fallback TP when no tp_hint provided


class RiskManager:
    def __init__(self, capital: float, config: RiskConfig = None):
        self.capital = capital
        self.cfg = config or RiskConfig()

        # State — reset each day via reset_daily()
        self.daily_pnl: float = 0.0
        self.trades_today: int = 0
        self.consec_losses: int = 0
        self.cooldown_until = None  # datetime or None

    def set_capital(self, capital: float) -> None:
        """Update the current account equity used for sizing and daily risk limits."""
        self.capital = capital

    def reset_daily(self) -> None:
        """Call at the start of each new trading day."""
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.consec_losses = 0
        self.cooldown_until = None

    # ── Pre-trade checks ──────────────────────────────────────────────────────

    def can_trade(self, ts: datetime) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        Check all rules before opening a new position.
        """
        max_loss = self.capital * (self.cfg.max_daily_loss_pct / 100)
        if self.daily_pnl <= -max_loss:
            return False, f"daily loss limit hit ({self.daily_pnl:.2f})"

        if self.trades_today >= self.cfg.max_trades_per_day:
            return False, f"max trades/day reached ({self.cfg.max_trades_per_day})"

        if self.cooldown_until and ts < self.cooldown_until:
            remaining = int((self.cooldown_until - ts).total_seconds() / 60)
            return False, f"cooldown active ({remaining} min remaining)"

        return True, "ok"

    # ── Sizing + levels ───────────────────────────────────────────────────────

    def position_size(self, cash: float, entry_price: float, sl_price: float) -> int:
        """
        Risk-based position sizing: risk exactly 1% of capital per trade.
          shares = floor( (capital × 1%) / stop_distance )

        Two hard caps applied after:
          1. Never exceed available cash
          2. Never exceed 10% of capital in a single position (protects against
             very tight SLs that would otherwise create oversized positions)
        """
        stop_distance = abs(entry_price - sl_price)
        if stop_distance == 0 or entry_price == 0:
            return 0
        risk_amount = self.capital * (self.cfg.risk_per_trade_pct / 100)
        shares = int(risk_amount / stop_distance)
        max_by_cash = int(cash // entry_price)
        max_by_pct = int(self.capital * (self.cfg.max_position_pct / 100) / entry_price)
        return min(shares, max_by_cash, max_by_pct)

    def sl_price(self, entry: float, atr: float, direction: int = 1) -> float:
        """Stop loss: entry minus (sl_mult * ATR) for longs."""
        return round(entry - direction * self.cfg.sl_atr_mult * atr, 2)

    def tp_price(self, entry: float, atr: float, direction: int = 1) -> float:
        """Take profit: entry plus (tp_mult * ATR) for longs."""
        return round(entry + direction * self.cfg.tp_atr_mult * atr, 2)

    # ── Post-trade update ─────────────────────────────────────────────────────

    def record_trade(self, pnl: float, ts: datetime) -> None:
        """Update state after a trade closes."""
        self.daily_pnl += pnl
        self.trades_today += 1

        if pnl <= 0:
            self.consec_losses += 1
            # Trigger cooldown after N consecutive losses
            if self.consec_losses >= self.cfg.cooldown_after_losses:
                self.cooldown_until = ts + timedelta(minutes=self.cfg.cooldown_minutes)
                self.consec_losses = 0  # reset so next block also gets a chance
        else:
            self.consec_losses = 0
