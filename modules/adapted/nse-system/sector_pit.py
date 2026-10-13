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


"""Point-in-time sector relative strength (batch B4, 2026-10-05).

WHY THIS EXISTS
`build_setup_pool` stamps every historical `setup_pool` row with `sector_rs`,
but it used `sector_gate.sector_perf(conn)`, which has **no as-of date** -- it
reads `universe_broad.perf1m / perf3m`, i.e. TODAY's values. Every historical row
therefore carried today's sector rank: a lookahead.

`research_cockpit.signature_match` explores `setup_pool`, so "similar historical
setups" were being matched partly on information that did not exist at the time.

Blast radius is deliberately narrow: `sector_rs` is NOT one of the meta-model
FEATURES (they exclude the context fields), so live signals, Top Picks and the
meta-model are untouched. Only the research corpus changes.

WHAT IT COMPUTES
For each date it reproduces the same definition as `universe_broad`:

    perf1m = close/close[-21 bars] - 1
    perf3m = close/close[-63 bars] - 1

then averages those across each sector's symbols and ranks sectors by the same
`0.6*perf1m + 0.4*perf3m` score `sector_gate` uses. The result is keyed by date
so a caller can ask "what was the sector rank on this bar?".

Sector membership (`stocks.sector`) is current state. That survivorship is
unavoidable without historical sector mapping, and it is unchanged from before.
"""

from collections import defaultdict

MOM_1M_BARS = 21
MOM_3M_BARS = 63
W_1M = 0.6
W_3M = 0.4


def sector_rs_by_date(conn, symbols, sector_of):
    """Return {date_str: {symbol: rs_in_0_to_1}}.

    `symbols`   -- iterable of symbols to include (the build universe).
    `sector_of` -- {symbol: sector} from stocks.

    A symbol with no sector, or <64 bars of history, gets no entry for the
    affected dates; callers should fall back to the neutral 0.5.
    """
    import pandas as pd

    syms = [s for s in symbols if sector_of.get(s)]
    if not syms:
        return {}

    placeholders = ",".join("?" * len(syms))
    rows = conn.execute(
        f"SELECT symbol, date, close FROM prices_daily "
        f"WHERE symbol IN ({placeholders}) ORDER BY date",
        syms,
    ).fetchall()
    if not rows:
        return {}

    df = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    wide = df.pivot_table(
        index="date", columns="symbol", values="close", aggfunc="last"
    ).sort_index()

    # Vectorised per-symbol momentum, in one pass for every date and symbol.
    perf1 = wide.pct_change(MOM_1M_BARS)
    perf3 = wide.pct_change(MOM_3M_BARS)
    if perf1.empty:
        return {}

    # Group columns by sector once, then aggregate per date.
    cols_by_sector = defaultdict(list)
    for s in wide.columns:
        sec = sector_of.get(s)
        if sec:
            cols_by_sector[sec].append(s)

    sec_1m = pd.DataFrame({sec: perf1[cols].mean(axis=1) for sec, cols in cols_by_sector.items()})
    sec_3m = pd.DataFrame({sec: perf3[cols].mean(axis=1) for sec, cols in cols_by_sector.items()})
    if sec_1m.empty:
        return {}

    score = W_1M * sec_1m + W_3M * sec_3m
    score = score.dropna(how="all")
    if score.empty:
        return {}

    # Rank sectors per date: best sector -> 1.0, worst -> 0.0 (mirrors
    # sector_gate's normalisation of 1 - i/(n-1)).
    #
    # Computed per date with an explicit rank index rather than pandas
    # rank/rsub broadcasting: the vectorised form silently produced
    # out-of-range values when a sector scored NaN, which would have written
    # rs < 0 or > 1 into setup_pool. One classification per date is cheap.
    out = {}
    for dt_key, row in score.iterrows():
        valid = {sec: float(v) for sec, v in row.items() if pd.notna(v)}
        if not valid:
            continue
        ordered = sorted(valid.items(), key=lambda kv: kv[1], reverse=True)
        n = len(ordered)
        per_sector = {}
        for i, (sec, _v) in enumerate(ordered):
            per_sector[sec] = 1.0 if n == 1 else 1.0 - (i / (n - 1))
        d = str(pd.Timestamp(dt_key).date())
        out[d] = {
            sym: per_sector[sec]
            for sec, syms_in in cols_by_sector.items()
            if sec in per_sector
            for sym in syms_in
        }
    return out
