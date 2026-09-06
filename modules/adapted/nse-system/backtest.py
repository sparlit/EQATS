"""
Optimized + corrected backtester.
- Precomputed indicators (no per-day recomputation)
- O(1) prefilter; setup detector only on survivors
- Pending buy-stop orders (enter at trigger, not close)
- PDL stop + 5% rule enforced
"""
from dataclasses import dataclass, field
from typing import List
import time
import numpy as np
import pandas as pd
import yfinance as yf

import db
from regime import MarketRegime
from setup import SetupDetector

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

@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    initial_capital: float = 1_000_000
    slippage_pct: float = 0.001
    commission_pct: float = 0.0005
    max_positions: int = 5
    max_pending_orders: int = 20

    @property
    def total_trades(self): return len(self.trades)

    @property
    def wins(self): return sum(1 for t in self.trades if t.pnl_pct > 0)

    @property
    def losses(self): return sum(1 for t in self.trades if t.pnl_pct <= 0)

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
        eq = np.array([self.initial_capital] +
                      [self.initial_capital * (1 + t.pnl_pct)
                       for t in self.trades])
        peak = np.maximum.accumulate(eq)
        return float(np.max((peak - eq) / peak))

    @property
    def avg_holding_days(self):
        return float(np.mean([t.holding_days for t in self.trades])) \
            if self.trades else 0.0

    @property
    def total_return(self):
        r = 1.0
        for t in self.trades:
            r *= (1 + t.pnl_pct)
        return r - 1.0 if self.trades else 0.0

    def summary(self):
        return (
            f"\n{'='*60}\n  BACKTEST SUMMARY\n{'='*60}\n"
            f"  Total trades      : {self.total_trades}\n"
            f"  Wins / Losses     : {self.wins} / {self.losses}\n"
            f"  Win Rate          : {self.win_rate:.1%}\n"
            f"  Avg Win           : {self.avg_win:+.2%}\n"
            f"  Avg Loss          : {self.avg_loss:+.2%}\n"
            f"  Avg R:R           : {self.avg_rr:.2f}\n"
            f"  Profit Factor     : {self.profit_factor:.2f}\n"
            f"  Total Return      : {self.total_return:+.2%}\n"
            f"  Max Drawdown      : {self.max_drawdown:.2%}\n"
            f"  Avg Holding Days  : {self.avg_holding_days:.1f}\n"
            f"{'='*60}")

def _naive_index(df):
    try:
        df.index = pd.to_datetime(df.index.date)
    except Exception:
        df.index = pd.to_datetime(df.index)
    return df

class Backtester:
    HOLD_DAYS_MAX = 30
    ORDER_EXPIRY_BARS = 3
    TICK_SIZE = 0.05
    TARGET_R = 2.0

    def __init__(self, result: BacktestResult = None):
        self.result = result or BacktestResult()

    @staticmethod
    def _load(sym, start, end):
        db_sym = sym.split(".")[0]
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume "
            "FROM prices_daily WHERE symbol=? AND date>=? "
            "AND date<=? ORDER BY date", (db_sym, start, end)).fetchall()
        conn.close()
        if len(rows) >= 260:
            df = pd.DataFrame(list(rows), columns=["date", "Open",
                              "High", "Low", "Close", "Volume"])
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["Volume"] = df["Volume"].fillna(0)
            return df.dropna(subset=["Open", "High", "Low", "Close"])
        try:
            time.sleep(0.25)
            d = yf.Ticker(sym).history(start=start, end=end,
                                       auto_adjust=True)
            return _naive_index(d) if d is not None and len(d) > 260 \
                else None
        except Exception:
            return None

    @staticmethod
    def _precompute(dfr):
        c = dfr["Close"].values.astype(float)
        h = dfr["High"].values.astype(float)
        l = dfr["Low"].values.astype(float)
        v = dfr["Volume"].values.astype(float)
        e200 = pd.Series(c).ewm(span=200, adjust=False).mean().values
        vs20 = pd.Series(v).rolling(20).mean().values
        hh252 = pd.Series(h).rolling(252).max().values
        expl = (v > 2.5 * pd.Series(v).rolling(50).mean().values)
        volok = pd.Series(expl.astype(float)).rolling(60).max().shift(1)\
            .fillna(0).values
        pos = {d: i for i, d in enumerate(dfr.index)}
        return dict(c=c, h=h, l=l, v=v, e200=e200, vs20=vs20,
                    hh252=hh252, volok=volok, pos=pos, idx=dfr.index)

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

        for date in all_dates:
            # ---- manage open positions ----
            to_close = []
            for sym, pos in list(open_positions.items()):
                if date not in data[sym].index:
                    continue
                row = data[sym].loc[date]
                held = (date - pos["entry_date"]).days
                if row["Low"] <= pos["stop"]:
                    ex = pos["stop"] * (1 - self.result.slippage_pct
                                        - self.result.commission_pct)
                    self.result.trades.append(Trade(
                        sym, str(pos["entry_date"].date()),
                        str(date.date()), "LONG", pos["entry_price"],
                        ex, pos["stop"], pos["target"],
                        (ex - pos["entry_price"]) / pos["entry_price"],
                        held, "STOP"))
                    to_close.append(sym)
                    continue
                if row["High"] >= pos["target"]:
                    ex = pos["target"] * (1 - self.result.slippage_pct
                                          - self.result.commission_pct)
                    self.result.trades.append(Trade(
                        sym, str(pos["entry_date"].date()),
                        str(date.date()), "LONG", pos["entry_price"],
                        ex, pos["stop"], pos["target"],
                        (ex - pos["entry_price"]) / pos["entry_price"],
                        held, "TARGET"))
                    to_close.append(sym)
                    continue
                if held >= self.HOLD_DAYS_MAX:
                    ex = row["Close"] * (1 - self.result.slippage_pct
                                         - self.result.commission_pct)
                    self.result.trades.append(Trade(
                        sym, str(pos["entry_date"].date()),
                        str(date.date()), "LONG", pos["entry_price"],
                        ex, pos["stop"], pos["target"],
                        (ex - pos["entry_price"]) / pos["entry_price"],
                        held, "TIME_STOP"))
                    to_close.append(sym)
            for sym in to_close:
                open_positions.pop(sym, None)

            # ---- pending buy-stop orders ----
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
                    fill = od["trigger"] * (1 + self.result.slippage_pct
                                            + self.result.commission_pct)
                    if od["stop"] < fill:
                        open_positions[sym] = {
                            "entry_date": date, "entry_price": fill,
                            "stop": od["stop"],
                            "target": fill + self.TARGET_R *
                            (fill - od["stop"])}
                    to_rm.append(sym)
                else:
                    pending_orders[sym]["bars"] += 1
            for sym in to_rm:
                pending_orders.pop(sym, None)

            # ---- regime gate ----
            if date not in regime.index or not regime.loc[date]:
                continue
            if len(open_positions) >= self.result.max_positions:
                continue

            # ---- EOD scan with O(1) prefilter ----
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
                    {"Close": c[:i + 1], "High": h[:i + 1],
                     "Low": l[:i + 1], "Volume": v[:i + 1]},
                    index=p["idx"][:i + 1])
                st = SetupDetector.detect(df_slice, sym)
                if not st.triggered:
                    continue
                trig = st.entry_price + self.TICK_SIZE
                risk_pct = (trig - st.stop_loss) / trig
                if risk_pct <= 0 or risk_pct > 0.05:
                    continue
                pending_orders[sym] = {"signal_date": date,
                                       "trigger": trig,
                                       "stop": st.stop_loss, "bars": 0}
                if len(pending_orders) >= self.result.max_pending_orders:
                    break

        for sym, pos in open_positions.items():
            if data[sym].empty:
                continue
            ld = data[sym].index[-1]
            ex = data[sym].iloc[-1]["Close"] * (
                1 - self.result.slippage_pct - self.result.commission_pct)
            self.result.trades.append(Trade(
                sym, str(pos["entry_date"].date()), str(ld.date()),
                "LONG", pos["entry_price"], ex, pos["stop"],
                pos["target"],
                (ex - pos["entry_price"]) / pos["entry_price"],
                (ld - pos["entry_date"]).days, "EOD_CLOSE"))

        print(f"   prefilter hits: {prefilter_hits}")
        return self.result