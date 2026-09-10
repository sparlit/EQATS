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


"""v4-regime live portfolio: what the strategy holds as of today.

    python -m screener.monthly_portfolio

Prints regime state and the current top-20 momentum names. PAPER TRADING
ONLY until the 2-3 month paper phase confirms live behavior matches the
backtest (PROTOCOL_V4.md passed 2026-07-09; that is necessary, not
sufficient). Rebalance only on the month's last trading day.
"""
import pandas as pd
from backtest import features

import config


def main() -> None:
    p = features._panel(None, None)
    ctx = features._context(p)
    close = p["close"]
    t = close.index[-1]

    mom = (close.shift(21) / close.shift(252) - 1).loc[t]
    liquid = (p["turnover_lacs"].rolling(20).median() >= 500).loc[t]
    ok = liquid.reindex(mom.index, fill_value=False)
    ok[[s for s in mom.index if s not in ctx["stocks"]]] = False

    bench = ctx["bench"]
    regime_on = bench.loc[t] >= bench.rolling(200).mean().loc[t]

    top = mom[ok].dropna().nlargest(20)
    out = pd.DataFrame(
        {
            "mom_12_1_pct": (100 * top).round(1),
            "close": close.loc[t, top.index].round(2),
            "rs_pctile": ctx["rs_pctile"].loc[t, top.index].round(0),
        }
    )

    print(f"as of {t.date()}  |  regime: {'ON — hold the portfolio' if regime_on else 'OFF — be in cash'}")
    print(out.to_string())
    path = config.DATA_DIR / f"v4_portfolio_{t.date()}.csv"
    out.to_csv(path)
    print(f"→ {path}")


if __name__ == "__main__":
    main()
