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
Backtest Simulation — Portfolio State + Rebalance Mechanics WITH Transaction Costs

Buy  cost : 0.118% on buy  value
Sell cost : 0.119% on sell value

Cost applied only on BUY and SELL, not HOLD.
Sell proceeds are net of sell cost.
Buy shares are reduced so total cash spent (shares * price * (1 + buy_cost)) <= cap_per_entry.
"""

import numpy as np
import pandas as pd

BUY_COST = 0.00118  # 0.118%
SELL_COST = 0.00119  # 0.119%


class PortfolioStateWithCosts:
    def __init__(self, initial_capital: float = 10_000_000.0):
        self.initial_capital = initial_capital
        self.holdings = {}
        self.cash_pool = initial_capital
        self.week_num = 0

    def reset(self):
        self.holdings = {}
        self.cash_pool = self.initial_capital
        self.week_num = 0

    def rebalance(
        self,
        top25: list,
        close_prices: dict,
        friday_date: pd.Timestamp,
        cell_id: str,
    ) -> tuple:

        self.week_num += 1
        activity = []

        # ── Step 1: Pre-Rebalance State ───────────────────────────────────────
        cash_pool_carryover = self.cash_pool

        held_values = {}
        for sym, shares in self.holdings.items():
            price = close_prices.get(sym, np.nan)
            if pd.notna(price) and price > 0:
                held_values[sym] = shares * price
            else:
                held_values[sym] = 0.0

        market_value_holdings = sum(held_values.values())
        portfolio_value_pre = market_value_holdings + cash_pool_carryover

        # ── Step 2: Derive exits / entries / held ─────────────────────────────
        current_holdings = set(self.holdings.keys())
        new_top25 = set(top25)

        valid_top25 = {s for s in new_top25 if pd.notna(close_prices.get(s, np.nan)) and close_prices.get(s, 0) > 0}

        exits = current_holdings - valid_top25
        entries = valid_top25 - current_holdings
        held = current_holdings & valid_top25

        num_entries = len(entries)

        # ── Step 3: Sell exits (net of sell cost) ─────────────────────────────
        sell_proceeds = 0.0
        for sym in exits:
            shares = self.holdings[sym]
            price = close_prices.get(sym, np.nan)
            if pd.notna(price) and price > 0:
                gross_value = shares * price
                cost = gross_value * SELL_COST
                net_value = gross_value - cost
            else:
                gross_value = net_value = cost = 0.0
            sell_proceeds += net_value
            activity.append(
                {
                    "friday_date": friday_date,
                    "cell_id": cell_id,
                    "symbol": sym,
                    "action": "SELL",
                    "shares": shares,
                    "price": price,
                    "gross_value": gross_value,
                    "transaction_cost": cost,
                    "value": net_value,
                    "portfolio_value": np.nan,
                    "cash_pool": np.nan,
                }
            )
            del self.holdings[sym]

        available_cash = cash_pool_carryover + sell_proceeds

        # ── Step 4: Allocation cap ────────────────────────────────────────────
        if num_entries == 0:
            cap_per_entry = 0.0
        elif self.week_num == 1 or len(held) == 0:
            cap_per_entry = available_cash / num_entries
        else:
            avg_held_value = sum(held_values[s] for s in held) / len(held)
            cap_per_entry = min(available_cash / num_entries, avg_held_value)

        # ── Step 5: Buy entries (shares reduced by buy cost) ──────────────────
        cash_deployed = 0.0
        for sym in entries:
            price = close_prices[sym]
            # cash spent per share = price * (1 + BUY_COST)
            # shares = cap_per_entry / (price * (1 + BUY_COST))
            shares = cap_per_entry / (price * (1 + BUY_COST))
            market_val = shares * price  # actual market value
            cost = market_val * BUY_COST  # = cap_per_entry - market_val
            cash_spent = market_val + cost  # = cap_per_entry
            self.holdings[sym] = shares
            cash_deployed += cash_spent
            activity.append(
                {
                    "friday_date": friday_date,
                    "cell_id": cell_id,
                    "symbol": sym,
                    "action": "BUY",
                    "shares": shares,
                    "price": price,
                    "gross_value": market_val,
                    "transaction_cost": cost,
                    "value": market_val,
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
                    "gross_value": shares * price,
                    "transaction_cost": 0.0,
                    "value": shares * price,
                    "portfolio_value": np.nan,
                    "cash_pool": np.nan,
                }
            )

        # ── Step 6: Post-Rebalance State ──────────────────────────────────────
        cash_pool_after = available_cash - cash_deployed

        market_value_post = sum(
            self.holdings[s] * close_prices[s] for s in self.holdings if pd.notna(close_prices.get(s, np.nan))
        )
        portfolio_value_post = market_value_post + cash_pool_after

        self.cash_pool = cash_pool_after

        for row in activity:
            row["portfolio_value"] = portfolio_value_post
            row["cash_pool"] = cash_pool_after

        return portfolio_value_post, portfolio_value_pre, activity
