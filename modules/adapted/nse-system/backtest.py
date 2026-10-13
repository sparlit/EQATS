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
Optimized backtester. All parameters in strategy_config.BACKTEST.

v5 (2026-09-12): migrated to central config.
"""
import time
from dataclasses import dataclass, field

import db
import numpy as np
import pandas as pd
import yfinance as yf
from regime import MarketRegime
from setup import SetupDetector
from strategy_config import BACKTEST as CFG


@dataclass
class Trade:
    symbol: str
    entry_date: str
    exit_date: str
    direction: str
    entry_price: float
    exit_price: float
    stop_loss: float
    target_price: float
    pnl_pct: float
    holding_days: int
    exit_reason: str
    n_exits: int = 1


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    initial_capital: float = CFG["INITIAL_CAPITAL"]
    slippage_pct: float = CFG["SLIPPAGE_PCT"]
    commission_pct: float = CFG["COMMISSION_PCT"]
    max_positions: int = CFG["MAX_POSITIONS"]
    max_pending_orders: int = CFG["MAX_PENDING_ORDERS"]

    @property
    def total_trades(self):
        return len(self.trades)

    @property
    def wins(self):
        return sum(1 for t in self.trades if t.pnl_pct > 0)

    @property
    def losses(self):
        return sum(1 for t in self.trades if t.pnl_pct <= 0)

    @property
    def win_rate(self):
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def avg_win(self):
        ws = [t.pnl_pct for t in self.trades if t.pnl_pct > 0]
        return float(np.mean(ws)) if ws else 0.0

    @property
    def avg_loss(self):
        ls = [t.pnl_pct for t in self.trades if t.pnl_pct <= 0]
        return float(np.mean(ls)) if ls else 0.0

    @property
    def avg_rr(self):
        return abs(self.avg_win / self.avg_loss) if self.avg_loss else 0.0

    @property
    def profit_factor(self):
        gp = sum(t.pnl_pct for t in self.trades if t.pnl_pct > 0)
        gl = abs(sum(t.pnl_pct for t in self.trades if t.pnl_pct <= 0))
        return gp / gl if gl else float("inf")

    @property
    def max_drawdown(self):
        if not self.trades:
            return 0.0
        # This is a research-only sequential trade ledger, not an executable
        # portfolio curve.  Build it cumulatively; the old implementation
        # compared each individual trade return with initial capital.
        equity = [self.initial_capital]
        for t in self.trades:
            equity.append(equity[-1] * (1 + t.pnl_pct))
        eq = np.array(equity)
        peak = np.maximum.accumulate(eq)
        return float(np.max((peak - eq) / peak))

    @property
    def avg_holding_days(self):
        return float(np.mean([t.holding_days for t in self.trades])) if self.trades else 0.0

    @property
    def total_return(self):
        r = 1.0
        for t in self.trades:
            r *= 1 + t.pnl_pct
        return r - 1.0 if self.trades else 0.0

    def summary(self):
        """Human-readable legacy API, with honest metric scope labels."""
        return (
            f"Research-only synthetic closed-trade sequence (not a portfolio)\n"
            f"Trades: {self.total_trades} | Win rate: {self.win_rate:.1%} | "
            f"Profit factor: {self.profit_factor:.2f}\n"
            f"Sequence return: {self.total_return:.2%} | "
            f"Sequence max drawdown: {self.max_drawdown:.2%}\n"
            f"Average holding days: {self.avg_holding_days:.1f}"
        )


def _naive_index(df):
    try:
        df.index = pd.to_datetime(df.index.date)
    except Exception:
        df.index = pd.to_datetime(df.index)
    return df


class Backtester:
    HOLD_DAYS_MAX = CFG["HOLD_DAYS_MAX"]
    ORDER_EXPIRY_BARS = CFG["ORDER_EXPIRY_BARS"]
    TICK_SIZE = CFG["TICK_SIZE"]
    TARGET_R = CFG["TARGET_R"]
    TRANCHES_ENABLED = CFG["TRANCHES_ENABLED"]
    T_LEVEL_1 = CFG["T_LEVEL_1"]
    T_LEVEL_2 = CFG["T_LEVEL_2"]
    T_PCT_1 = CFG["T_PCT_1"]
    T_PCT_2 = CFG["T_PCT_2"]
    TRAIL_EMA = CFG["TRAIL_EMA"]

    def __init__(self, result: BacktestResult = None):
        self.result = result or BacktestResult()

    @staticmethod
    def _load(sym, start, end):
        db_sym = sym.split(".")[0]
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume "
            "FROM prices_daily WHERE symbol=? AND date>=? "
            "AND date<=? ORDER BY date",
            (db_sym, start, end),
        ).fetchall()
        conn.close()
        if len(rows) >= 260:
            df = pd.DataFrame(
                list(rows), columns=["date", "Open", "High", "Low", "Close", "Volume"]
            )
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["Volume"] = df["Volume"].fillna(0)
            return df.dropna(subset=["Open", "High", "Low", "Close"])
        try:
            time.sleep(0.25)
            d = yf.Ticker(sym).history(start=start, end=end, auto_adjust=True)
            return _naive_index(d) if d is not None and len(d) > 260 else None
        except Exception:
            return None

    @staticmethod
    def _precompute(dfr):
        c = dfr["Close"].values.astype(float)
        h = dfr["High"].values.astype(float)
        l = dfr["Low"].values.astype(float)
        v = dfr["Volume"].values.astype(float)
        e10 = pd.Series(c).ewm(span=10, adjust=False).mean().values
        e200 = pd.Series(c).ewm(span=200, adjust=False).mean().values
        vs20 = pd.Series(v).rolling(20).mean().values
        hh252 = pd.Series(h).rolling(252).max().values
        expl = v > 2.5 * pd.Series(v).rolling(50).mean().values
        volok = pd.Series(expl.astype(float)).rolling(60).max().shift(1).fillna(0).values
        pos = {d: i for i, d in enumerate(dfr.index)}
        return {
            "c": c,
            "h": h,
            "l": l,
            "v": v,
            "e10": e10,
            "e200": e200,
            "vs20": vs20,
            "hh252": hh252,
            "volok": volok,
            "pos": pos,
            "idx": dfr.index,
        }

    def _close_tranche(self, pos, date, raw_price, pct, reason):
        net = raw_price * (1 - self.result.slippage_pct - self.result.commission_pct)
        pos["exits"].append(
            {
                "date": str(date.date()) if hasattr(date, "date") else str(date),
                "net": float(net),
                "pct": float(pct),
                "reason": reason,
            }
        )

    def _finalize_trade(self, sym, pos, exit_date):
        entry = pos["entry_price"]
        total_pnl = 0.0
        weighted_exit = 0.0
        total_pct = 0.0
        for e in pos["exits"]:
            total_pnl += (e["net"] - entry) / entry * e["pct"]
            weighted_exit += e["net"] * e["pct"]
            total_pct += e["pct"]
        if total_pct > 0:
            weighted_exit /= total_pct
        reasons = [e["reason"] for e in pos["exits"]]
        unique = list(dict.fromkeys(reasons))
        reason = unique[0] if len(unique) == 1 else "TRANCHED"
        held = (exit_date - pos["entry_date"]).days
        self.result.trades.append(
            Trade(
                sym,
                str(pos["entry_date"].date()),
                str(exit_date.date()),
                "LONG",
                entry,
                round(weighted_exit, 4),
                pos["initial_stop"],
                pos["target_r"],
                total_pnl,
                held,
                reason,
                n_exits=len(pos["exits"]),
            )
        )

    def run(self, symbols, start, end):
        days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 30
        idx_df, used = MarketRegime._fetch(days)
        if idx_df is None:
            print("No benchmark data available")
            return self.result
        idx_df = _naive_index(idx_df)
        print(f"   regime benchmark: {used}")
        regime = MarketRegime.check_series(idx_df)

        data = {}
        for sym in symbols:
            d = self._load(sym, start, end)
            if d is not None and len(d) >= 280:
                data[sym] = d
        print(f"   loaded {len(data)} stocks")
        if not data:
            return self.result

        P = {s: self._precompute(d) for s, d in data.items()}
        all_dates = sorted(set().union(*(d.index for d in data.values())))
        open_positions = {}
        pending_orders = {}
        prefilter_hits = 0
        stale_signals = 0

        for date in all_dates:
            date_str = str(date.date())

            to_close = []
            for sym, pos in list(open_positions.items()):
                if date not in data[sym].index:
                    continue
                row = data[sym].loc[date]
                p = P[sym]
                i = p["pos"].get(date)
                if i is None:
                    continue

                if row["Low"] <= pos["stop"]:
                    self._close_tranche(pos, date, pos["stop"], pos["remaining_pct"], "STOP")
                    pos["remaining_pct"] = 0.0
                    self._finalize_trade(sym, pos, date)
                    to_close.append(sym)
                    continue

                if self.TRANCHES_ENABLED:
                    risk = pos["entry_price"] - pos["initial_stop"]
                    if risk > 0:
                        if not pos["t1_done"]:
                            t1_price = pos["entry_price"] + self.T_LEVEL_1 * risk
                            if row["High"] >= t1_price:
                                self._close_tranche(pos, date, t1_price, self.T_PCT_1, "T2R")
                                pos["t1_done"] = True
                                pos["remaining_pct"] -= self.T_PCT_1
                                if pos["entry_price"] > pos["stop"]:
                                    pos["stop"] = pos["entry_price"]
                        if not pos["t2_done"] and pos["t1_done"]:
                            t2_price = pos["entry_price"] + self.T_LEVEL_2 * risk
                            if row["High"] >= t2_price:
                                self._close_tranche(pos, date, t2_price, self.T_PCT_2, "T3R")
                                pos["t2_done"] = True
                                pos["remaining_pct"] -= self.T_PCT_2
                                pos["trail_active"] = True
                    if pos["trail_active"] and pos["remaining_pct"] > 0.001:
                        ema = p["e10"][i]
                        if not np.isnan(ema) and row["Close"] < ema:
                            self._close_tranche(
                                pos, date, row["Close"], pos["remaining_pct"], "TRAIL"
                            )
                            pos["remaining_pct"] = 0.0
                            self._finalize_trade(sym, pos, date)
                            to_close.append(sym)
                            continue
                else:
                    if row["High"] >= pos["target_r"]:
                        self._close_tranche(
                            pos, date, pos["target_r"], pos["remaining_pct"], "TARGET"
                        )
                        pos["remaining_pct"] = 0.0
                        self._finalize_trade(sym, pos, date)
                        to_close.append(sym)
                        continue

                held = (date - pos["entry_date"]).days
                if held >= self.HOLD_DAYS_MAX:
                    self._close_tranche(pos, date, row["Close"], pos["remaining_pct"], "TIME")
                    pos["remaining_pct"] = 0.0
                    self._finalize_trade(sym, pos, date)
                    to_close.append(sym)
                    continue

            for sym in to_close:
                open_positions.pop(sym, None)

            to_rm = []
            for sym, od in list(pending_orders.items()):
                if date <= od["signal_date"]:
                    continue
                if date not in data[sym].index:
                    continue
                if od["bars"] >= self.ORDER_EXPIRY_BARS:
                    to_rm.append(sym)
                    continue
                row = data[sym].loc[date]
                if row["High"] >= od["trigger"]:
                    fill = od["trigger"] * (
                        1 + self.result.slippage_pct + self.result.commission_pct
                    )
                    if od["stop"] < fill:
                        risk = fill - od["stop"]
                        target = fill + self.TARGET_R * risk
                        open_positions[sym] = {
                            "entry_date": date,
                            "entry_price": fill,
                            "initial_stop": od["stop"],
                            "stop": od["stop"],
                            "target_r": target,
                            "exits": [],
                            "remaining_pct": 1.0,
                            "t1_done": False,
                            "t2_done": False,
                            "trail_active": False,
                        }
                    to_rm.append(sym)
                else:
                    pending_orders[sym]["bars"] += 1
            for sym in to_rm:
                pending_orders.pop(sym, None)

            if date not in regime.index or not regime.loc[date]:
                continue
            if len(open_positions) >= self.result.max_positions:
                continue

            for sym, p in P.items():
                if sym in open_positions or sym in pending_orders:
                    continue
                i = p["pos"].get(date)
                if i is None or i < 280:
                    continue
                c, h, l, v = p["c"], p["h"], p["l"], p["v"]
                e200 = p["e200"]
                if not (c[i] > e200[i] and e200[i] > e200[i - 21]):
                    continue
                if p["vs20"][i] * c[i] < 2e7:
                    continue
                m1 = c[i] / c[i - 22] - 1 >= 0.20
                m3 = c[i] / c[i - 64] - 1 >= 0.30
                near = c[i] >= 0.75 * p["hh252"][i]
                if not (m1 or m3 or near):
                    continue
                if p["volok"][i] < 1:
                    continue
                prefilter_hits += 1
                df_slice = pd.DataFrame(
                    {
                        "Close": c[: i + 1],
                        "High": h[: i + 1],
                        "Low": l[: i + 1],
                        "Volume": v[: i + 1],
                    },
                    index=p["idx"][: i + 1],
                )
                st = SetupDetector.detect(df_slice, sym)
                if not st.triggered:
                    continue
                if st.signal_date != date_str:
                    stale_signals += 1
                    continue
                trig = st.entry_price + self.TICK_SIZE
                risk_pct = (trig - st.stop_loss) / trig
                if risk_pct <= 0 or risk_pct > 0.05:
                    continue
                pending_orders[sym] = {
                    "signal_date": date,
                    "trigger": trig,
                    "stop": st.stop_loss,
                    "bars": 0,
                }
                if len(pending_orders) >= self.result.max_pending_orders:
                    break

        for sym, pos in list(open_positions.items()):
            if data[sym].empty:
                continue
            ld = data[sym].index[-1]
            self._close_tranche(
                pos, ld, data[sym].iloc[-1]["Close"], pos["remaining_pct"], "EOD_CLOSE"
            )
            self._finalize_trade(sym, pos, ld)

        print(f"   prefilter hits: {prefilter_hits}")
        print(f"   stale signals skipped: {stale_signals}")
        return self.result
