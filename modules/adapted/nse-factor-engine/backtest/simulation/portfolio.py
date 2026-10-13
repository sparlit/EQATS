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
Backtest Simulation — Portfolio State + Rebalance Mechanics

Per METHODOLOGY.md §6.7. Single cell, one Friday at a time.

Usage:
    state = PortfolioState(initial_capital=10_000_000)
    port_value, activity = state.rebalance(top25, close_prices, friday_date, cell_id)
"""

import numpy as np
import pandas as pd


class PortfolioState:
    def __init__(self, initial_capital: float = 10_000_000.0):
        """
        initial_capital : starting cash (default ₹1cr = 10M)
        """
        self.initial_capital = initial_capital
        self.holdings = {}  # {symbol: shares}
        self.cash_pool = initial_capital
        self.week_num = 0  # increments each rebalance

    def reset(self):
        """Reset to initial state — used between cells in simulation."""
        self.holdings = {}
        self.cash_pool = self.initial_capital
        self.week_num = 0

    def rebalance(
        self,
        top25: list,  # ordered list of symbols (top-25 for this cell/Friday)
        close_prices: dict,  # {symbol: close_price} for this Friday
        friday_date: pd.Timestamp,
        cell_id: str,
    ) -> tuple:
        """
        Executes one weekly rebalance per §6.7.

        Returns:
            portfolio_value_post : float
            activity             : list of dicts (one row per position action)
        """
        self.week_num += 1
        activity = []

        # ── Step 1: Pre-Rebalance State ───────────────────────────────────────
        cash_pool_carryover = self.cash_pool

        # value holdings at Friday close
        # drop any held symbol with no price data this Friday
        held_values = {}
        for sym, shares in self.holdings.items():
            price = close_prices.get(sym, np.nan)
            if pd.notna(price) and price > 0:
                held_values[sym] = shares * price
            else:
                # no price — carry at 0 value, log as anomaly
                held_values[sym] = 0.0

        market_value_holdings = sum(held_values.values())
        portfolio_value_pre = market_value_holdings + cash_pool_carryover

        # ── Step 2: Derive exits / entries / held ─────────────────────────────
        current_holdings = set(self.holdings.keys())
        new_top25 = set(top25)

        # exclude symbols with no price from new entries
        valid_top25 = {
            s
            for s in new_top25
            if pd.notna(close_prices.get(s, np.nan)) and close_prices.get(s, 0) > 0
        }

        exits = current_holdings - valid_top25
        entries = valid_top25 - current_holdings
        held = current_holdings & valid_top25

        num_entries = len(entries)

        # ── Step 3: Sell exits ────────────────────────────────────────────────
        sell_proceeds = 0.0
        for sym in exits:
            shares = self.holdings[sym]
            price = close_prices.get(sym, np.nan)
            value = shares * price if pd.notna(price) and price > 0 else 0.0
            sell_proceeds += value
            activity.append(
                {
                    "friday_date": friday_date,
                    "cell_id": cell_id,
                    "symbol": sym,
                    "action": "SELL",
                    "shares": shares,
                    "price": price,
                    "value": value,
                    "portfolio_value": np.nan,  # filled post-rebalance
                    "cash_pool": np.nan,
                }
            )
            del self.holdings[sym]

        available_cash = cash_pool_carryover + sell_proceeds

        # ── Step 4: Allocation cap ────────────────────────────────────────────
        if num_entries == 0:
            cap_per_entry = 0.0
        elif self.week_num == 1 or len(held) == 0:
            # week 1 or full turnover — no cap, deploy evenly
            cap_per_entry = available_cash / num_entries
        else:
            avg_held_value = sum(held_values[s] for s in held) / len(held)
            cap_per_entry = min(available_cash / num_entries, avg_held_value)

        # ── Step 5: Buy entries ───────────────────────────────────────────────
        cash_deployed = 0.0
        for sym in entries:
            price = close_prices[sym]
            shares = cap_per_entry / price
            value = shares * price  # = cap_per_entry exactly
            self.holdings[sym] = shares
            cash_deployed += value
            activity.append(
                {
                    "friday_date": friday_date,
                    "cell_id": cell_id,
                    "symbol": sym,
                    "action": "BUY",
                    "shares": shares,
                    "price": price,
                    "value": value,
                    "portfolio_value": np.nan,
                    "cash_pool": np.nan,
                }
            )

        # log held positions
        for sym in held:
            price = close_prices[sym]
            shares = self.holdings[sym]
            activity.append(
                {
                    "friday_date": friday_date,
                    "cell_id": cell_id,
                    "symbol": sym,
                    "action": "HOLD",
                    "shares": shares,
                    "price": price,
                    "value": shares * price,
                    "portfolio_value": np.nan,
                    "cash_pool": np.nan,
                }
            )

        # ── Step 6: Post-Rebalance State ──────────────────────────────────────
        cash_pool_after = available_cash - cash_deployed

        # market value of all held positions (held + newly bought)
        market_value_post = sum(
            self.holdings[s] * close_prices[s]
            for s in self.holdings
            if pd.notna(close_prices.get(s, np.nan))
        )
        portfolio_value_post = market_value_post + cash_pool_after

        # update state
        self.cash_pool = cash_pool_after

        # sanity check — portfolio value should be conserved on rebalance day
        if abs(portfolio_value_post - portfolio_value_pre) > 0.01:
            print(
                f"  WARNING [{cell_id}] {friday_date.date()}: "
                f"value not conserved: pre={portfolio_value_pre:.2f} "
                f"post={portfolio_value_post:.2f} "
                f"diff={portfolio_value_post - portfolio_value_pre:.4f}"
            )

        # fill portfolio_value and cash_pool into activity rows
        for row in activity:
            row["portfolio_value"] = portfolio_value_post
            row["cash_pool"] = cash_pool_after

        return portfolio_value_post, portfolio_value_pre, activity
