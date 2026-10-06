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
Build setup_pool — global historical setup features + forward outcomes.

Walks history for a limited universe (top-N by mcap), extracts the
feature snapshot at every SetupDetector trigger, and stores it. Then
signature matching can find the N nearest pool rows to any live setup.

Usage:
  python build_setup_pool.py           # top 200 symbols, 5y, step=5
  python build_setup_pool.py 400 10    # top 400, step=10
  python build_setup_pool.py --clear   # wipe and rebuild
"""
import contextlib
import sys
import time

import db
import numpy as np
import pandas as pd
import sector_pit
import setup_sim
from log_utils import get_logger
from setup import SetupDetector

log = get_logger("setup_pool")

MIN_BARS = 280
HOLD_BARS = 30


def _ensure(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS setup_pool(
        symbol TEXT,
        signal_date TEXT,
        close REAL,
        impulse_pct_60d REAL,
        days_since_impulse_peak REAL,
        consolidation_range_pct REAL,
        vol_ratio_20 REAL,
        atr_pct REAL,
        mom_20d REAL,
        mom_60d REAL,
        distance_from_52w_high REAL,
        rsi REAL,
        sector TEXT,
        sector_rs REAL,
        mfe_r REAL,
        mae_r REAL,
        hit_1r INT,
        hit_2r INT,
        hit_3r INT,
        outcome TEXT,
        PRIMARY KEY (symbol, signal_date)
    )
    """)
    with contextlib.suppress(Exception):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pool_sector ON setup_pool(sector)")


def _sma(vals, span):
    if len(vals) < span:
        return None
    return float(np.mean(vals[-span:]))


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - period, len(closes)):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    return 100 - (100 / (1 + gains / losses))


def _features_at(df, i):
    """Feature snapshot at bar `i`. Returns dict or None."""
    if i < 60:
        return None
    c = df["Close"].values.astype(float)[: i + 1]
    h = df["High"].values.astype(float)[: i + 1]
    l = df["Low"].values.astype(float)[: i + 1]
    v = df["Volume"].values.astype(float)[: i + 1]

    close = float(c[-1])
    high52 = float(np.max(h[-252:])) if len(h) >= 252 else float(np.max(h))

    # Impulse/pullback
    lookback = 60
    window = min(lookback, len(c))
    h_seg = h[-window:]
    peak_local = int(np.argmax(h_seg))
    peak_idx = len(c) - window + peak_local
    peak_high = float(h[peak_idx])
    low_start = max(0, peak_idx - 40)
    low_before = float(np.min(l[low_start : peak_idx + 1]))
    impulse_pct = (peak_high - low_before) / low_before if low_before > 0 else None
    days_since = len(c) - 1 - peak_idx
    cons_range = None
    if days_since >= 1:
        cons_high = float(np.max(h[peak_idx + 1 :]))
        cons_low = float(np.min(l[peak_idx + 1 :]))
        if peak_high > 0:
            cons_range = (cons_high - cons_low) / peak_high

    # Vol ratio
    avg_vol_20 = _sma(v, 20)
    vol_ratio = (float(v[-1]) / avg_vol_20) if avg_vol_20 else None

    # ATR%
    atr_pct = None
    if len(c) >= 15:
        trs = []
        for k in range(1, len(c)):
            trs.append(max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])))
        atr = float(np.mean(trs[-14:]))
        atr_pct = atr / close if close > 0 else None

    mom_20d = (c[-1] / c[-21] - 1) if len(c) >= 21 else None
    mom_60d = (c[-1] / c[-61] - 1) if len(c) >= 61 else None
    dist_high = (high52 - close) / high52 if high52 > 0 else None

    return {
        "close": close,
        "impulse_pct_60d": impulse_pct,
        "days_since_impulse_peak": days_since,
        "consolidation_range_pct": cons_range,
        "vol_ratio_20": vol_ratio,
        "atr_pct": atr_pct,
        "mom_20d": mom_20d,
        "mom_60d": mom_60d,
        "distance_from_52w_high": dist_high,
        "rsi": _rsi(c),
    }


def _simulate(df, signal_i, trigger, stop):
    """Adapter over setup_sim.simulate_forward (B5, 2026-10-05).

    Keeps this module's historic 0/1 hit flags; the shared core returns booleans
    and extra fields (hit_4r, bars_to_*). No numeric behaviour changed.
    """
    r = setup_sim.simulate_forward(df, signal_i, trigger, stop, hold_bars=HOLD_BARS)
    if r is None:
        return None
    r["hit_1r"] = 1 if r["hit_1r"] else 0
    r["hit_2r"] = 1 if r["hit_2r"] else 0
    r["hit_3r"] = 1 if r["hit_3r"] else 0
    return r


def _sector_maps(conn):
    sector_of = {}
    for sym, sec in conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL"):
        sector_of[sym] = sec
    try:
        import sector_gate

        g = sector_gate.sector_perf(conn)
        if g is None or g.empty:
            srs = {}
        else:
            n = len(g)
            rank = {r["sector"]: 1.0 - (i / max(1, n - 1)) for i, (_, r) in enumerate(g.iterrows())}
            srs = {sym: rank.get(sector_of.get(sym), 0.5) for sym in sector_of}
    except Exception:
        srs = {}
    return sector_of, srs


def build(limit=200, step=5, clear=False):
    conn = db.get_conn()
    _ensure(conn)
    if clear:
        conn.execute("DELETE FROM setup_pool")
        conn.commit()

    from universe_helper import band_universe

    syms = band_universe(conn, limit=limit)
    log.info(f"building pool: {len(syms)} symbols, step={step}")

    sector_of, _stale_srs = _sector_maps(conn)
    # B4 (2026-10-05): sector RS must be point-in-time. `_sector_maps` above is
    # retained for `sector_of` only; its `srs` used TODAY's universe_broad
    # perf1m/perf3m for every historical row (a lookahead). Compute the real
    # per-date rank once for the whole universe instead.
    srs_by_date = sector_pit.sector_rs_by_date(conn, syms, sector_of)
    log.info(f"sector RS computed for {len(srs_by_date)} dates")
    t0 = time.time()
    added = 0
    failed = 0

    for si, sym in enumerate(syms, 1):
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices_daily "
            "WHERE symbol=? ORDER BY date",
            (sym,),
        ).fetchall()
        if len(rows) < MIN_BARS:
            continue
        df = pd.DataFrame(
            list(rows), columns=["date", "Open", "High", "Low", "Close", "Volume"]
        ).set_index("date")
        df.index = pd.to_datetime(df.index)

        for i in range(MIN_BARS, len(df) - 1, step):
            slice_df = df.iloc[: i + 1]
            try:
                st = SetupDetector.detect(slice_df, sym)
            except Exception:
                continue
            if not st.triggered:
                continue
            feats = _features_at(df, i)
            if not feats:
                continue
            sim = _simulate(df, i, st.entry_price, st.stop_loss)
            if sim is None:
                continue
            sector = sector_of.get(sym)
            signal_date = str(slice_df.index[-1].date())
            rs = srs_by_date.get(signal_date, {}).get(sym, 0.5)
            conn.execute(
                """
                INSERT OR REPLACE INTO setup_pool VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    sym,
                    signal_date,
                    feats["close"],
                    feats["impulse_pct_60d"],
                    feats["days_since_impulse_peak"],
                    feats["consolidation_range_pct"],
                    feats["vol_ratio_20"],
                    feats["atr_pct"],
                    feats["mom_20d"],
                    feats["mom_60d"],
                    feats["distance_from_52w_high"],
                    feats["rsi"],
                    sector,
                    rs,
                    sim["mfe_r"],
                    sim["mae_r"],
                    sim["hit_1r"],
                    sim["hit_2r"],
                    sim["hit_3r"],
                    sim["outcome"],
                ),
            )
            added += 1

        conn.commit()
        if si % 25 == 0:
            elapsed = time.time() - t0
            rate = si / elapsed if elapsed else 0
            eta = (len(syms) - si) / rate if rate else 0
            log.info(
                f"[{si}/{len(syms)}] {sym} · pool={added} · {elapsed:.0f}s elapsed, ETA {eta:.0f}s"
            )

    total = conn.execute("SELECT COUNT(*) FROM setup_pool").fetchone()[0]
    conn.close()
    log.info(
        f"build complete: added={added} failed={failed} "
        f"total_pool={total} in {time.time() - t0:.0f}s"
    )
    return added


def stats():
    conn = db.get_conn()
    _ensure(conn)
    n = conn.execute("SELECT COUNT(*) FROM setup_pool").fetchone()[0]
    n_sym = conn.execute("SELECT COUNT(DISTINCT symbol) FROM setup_pool").fetchone()[0]
    n_trig = conn.execute("SELECT SUM(hit_1r) FROM setup_pool").fetchone()[0]
    print(f"[POOL] {n} setups across {n_sym} symbols · hit_1R total {n_trig or 0}")
    conn.close()
    return n


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--clear" in argv:
        clear = True
        argv = [a for a in argv if a != "--clear"]
    else:
        clear = False

    limit = int(argv[0]) if argv and argv[0].isdigit() else 200
    step = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 5
    build(limit=limit, step=step, clear=clear)
    stats()
