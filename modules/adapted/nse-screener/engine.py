"""Event-driven portfolio simulator. The discipline is hard-coded so it
cannot be overridden emotionally:

  - risk-based sizing: every trade risks BT_RISK_PCT of equity
  - stop = entry − BT_ATR_MULT × ATR(14), evaluated on the CLOSE
    (an EOD system has no business pretending it can act on intraday lows);
    gap-opens below the stop fill at the open
  - scale out half at +BT_TARGET_R × initial risk, stop moves to breakeven
  - trail the remainder: exit on close below the 50-DMA
  - new entries only while regime is on (index trend AND breadth)
  - costs charged on every fill, both sides

Exits use the same day's prices as the fill day; entries use signals from
day t-1 filled at day t's open.
"""
from dataclasses import dataclass, field

import pandas as pd

import config


@dataclass
class Position:
    symbol: str
    shares: int
    entry: float
    stop: float
    target: float
    entry_date: pd.Timestamp
    scaled: bool = False
    last: float = 0.0          # last known close, for marking suspended names


@dataclass
class Result:
    equity: pd.Series
    bench: pd.Series
    trades: pd.DataFrame
    summary: dict = field(default_factory=dict)


def run(f: dict) -> Result:
    dates = f["close"].index
    start = max(251, 201)          # RS needs 250 lags; regime needs 200
    cash = float(config.BT_START_CASH)
    positions: dict[str, Position] = {}
    last_exit: dict[str, int] = {}     # symbol → date index of last exit
    trades, curve = [], []
    cost = config.BT_COST_PCT

    def book(p: Position, shares: int, price: float, d, reason: str):
        nonlocal cash
        proceeds = shares * price * (1 - cost)
        cash += proceeds
        trades.append({
            "symbol": p.symbol, "entry_date": p.entry_date.date(),
            "exit_date": d.date(), "entry": round(p.entry, 2),
            "exit": round(price, 2), "shares": shares,
            "pnl": round(proceeds - shares * p.entry * (1 + cost), 2),
            "pct": round(100 * (price * (1 - cost)
                                / (p.entry * (1 + cost)) - 1), 2),
            "reason": reason,
        })

    for i in range(start, len(dates)):
        d = dates[i]
        o, c = f["open"].loc[d], f["close"].loc[d]
        h = f["high"].loc[d]
        ma50 = f["ma50"].loc[d]

        # --- exits first (day-d prices) ---
        for sym in list(positions):
            p = positions[sym]
            if pd.isna(c.get(sym)):        # suspended today: hold
                continue
            po, ph, pc = o[sym], h[sym], c[sym]
            p.last = pc
            if po <= p.stop:               # gapped below the stop overnight
                book(p, p.shares, po, d, "stop_gap")
                del positions[sym]
                last_exit[sym] = i
                continue
            if not p.scaled and ph >= p.target:
                half = p.shares // 2
                if half:
                    book(p, half, p.target, d, "scale_out")
                    p.shares -= half
                p.scaled, p.stop = True, max(p.stop, p.entry)  # breakeven
            if pc <= p.stop:               # close-based stop: noise-resistant
                book(p, p.shares, pc, d, "stop")
                del positions[sym]
                last_exit[sym] = i
                continue
            if pc < ma50.get(sym, float("nan")):
                book(p, p.shares, pc, d, "trail_ma50")
                del positions[sym]
                last_exit[sym] = i

        # --- entries at day-d open from day-(d-1) breakout signals ---
        prev = dates[i - 1]
        if bool(f["regime"].loc[prev]):
            sig = f["signal"].loc[prev]
            cands = (f["rs_pctile"].loc[prev][sig[sig].index]
                     .sort_values(ascending=False).index)
            for sym in cands:
                if len(positions) >= config.BT_MAX_POSITIONS:
                    break
                atr = f["atr"].loc[prev].get(sym)
                if sym in positions or pd.isna(o.get(sym)) or pd.isna(atr):
                    continue
                if i - last_exit.get(sym, -10**9) <= config.BT_COOLDOWN:
                    continue               # churn guard: no instant re-entry
                entry = o[sym]
                risk_per_share = config.BT_ATR_MULT * atr
                if risk_per_share <= 0:
                    continue
                equity_now = cash + sum(p.shares * p.last
                                        for p in positions.values())
                fill = entry * (1 + cost)
                shares = int(min(
                    config.BT_RISK_PCT * equity_now / risk_per_share,
                    config.BT_MAX_POS_PCT * equity_now / fill,
                    cash / fill))
                if shares <= 0:
                    continue
                cash -= shares * fill
                positions[sym] = Position(
                    sym, shares, entry,
                    stop=entry - risk_per_share,
                    target=entry + config.BT_TARGET_R * risk_per_share,
                    entry_date=d, last=entry)

        mark = sum(p.shares * p.last for p in positions.values())
        curve.append({"date": d, "equity": cash + mark,
                      "n_pos": len(positions)})

    equity = pd.DataFrame(curve).set_index("date")["equity"]
    bench = f["bench"].loc[equity.index]
    bench = equity.iloc[0] * bench / bench.iloc[0]
    return Result(equity, bench, pd.DataFrame(trades))
