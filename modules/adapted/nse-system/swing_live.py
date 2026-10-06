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
Swing Desk engine (live, no execution).
EOD: regime gate + breadth gate + sector gate + fund veto -> signals -> Telegram.
When regime is DEFENSIVE, falls back to ALL-WEATHER mode.
Daily: grade pending signals WIN / LOSS / EXPIRED / TIMEOUT.
"""
import contextlib
import datetime as dt

import breadth
import db
import pandas as pd
import sector_gate
from regime import MarketRegime
from scanner import Screener
from setup import SetupDetector
from universe_helper import combined_universe


def universe(conn):
    """Canonical combined universe (band + active)."""
    return combined_universe(conn, band_limit=1000)


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS swing_signals(
        signal_date TEXT, symbol TEXT, entry_trigger REAL,
        stop REAL, target REAL, risk_pct REAL, pullback REAL,
        impulse REAL, ema_zone TEXT, outcome TEXT,
        updated_at TEXT)""")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(swing_signals)")]
    if "mode" not in cols:
        with contextlib.suppress(Exception):
            conn.execute("ALTER TABLE swing_signals ADD COLUMN mode TEXT DEFAULT 'SWING'")


def _is_vetoed(sym, conn):
    try:
        import fund_veto

        return fund_veto.vetoed(sym, conn=conn)
    except Exception:
        return False, None


def _scan_all_weather(conn, today):
    try:
        import all_weather
    except Exception as e:
        print(f"[AW] module missing: {e}")
        return 0

    try:
        b = breadth.compute(conn)
        if b["above50"] < 0.35:
            print(f"[AW] breadth too weak: above50={b['above50']:.2f} < 0.35 -> skip")
            return 0
        print(f"[AW] breadth ok for AW mode: above50={b['above50']:.2f}")
    except Exception as e:
        print(f"[AW] breadth check skipped: {e}")

    conn.execute("DELETE FROM swing_signals WHERE signal_date=? AND mode='ALL_WEATHER'", (today,))

    cands = all_weather.candidates(conn)
    print(f"[AW] {len(cands)} candidates (>=25% below 52w high, within 15% of 52w low)")

    n = 0
    for sym, df, fs, roce, tier in cands:
        st = all_weather.detect(sym, df, fs, roce, tier)
        if not st:
            continue
        bad, why = _is_vetoed(sym, conn)
        if bad:
            print(f"  [AW] {sym} vetoed: {why}")
            continue
        conn.execute(
            "INSERT INTO swing_signals(signal_date, symbol, entry_trigger, "
            "stop, target, risk_pct, pullback, impulse, ema_zone, outcome, "
            "updated_at, mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                today,
                sym,
                st["entry"],
                st["stop"],
                st["target"],
                round(st["risk_pct"] * 100, 2),
                st["pb_depth"],
                st["impulse"],
                st["pattern"],
                "PENDING",
                dt.datetime.now().isoformat(),
                "ALL_WEATHER",
            ),
        )
        n += 1
        print(
            f"  [AW] {sym:<12} {st['pattern']:<18} entry {st['entry']} "
            f"stop {st['stop']} target {st['target']} fund {fs}"
        )
        try:
            from alerts import notify_all_weather

            notify_all_weather(sym, st)
        except Exception as e:
            print(f"  [AW] alert skipped: {e}")
    print(f"[AW] all-weather signals stored: {n}")
    return n


def scan():
    conn = db.get_conn()
    ensure(conn)
    reg = MarketRegime.compute()
    today = dt.date.today().isoformat()
    print(
        f"regime: {reg.level} ({reg.symbol}) "
        f"size_mult={reg.size_mult} allows_swing={reg.allows_swing}"
    )
    conn.execute("DELETE FROM swing_signals WHERE signal_date=? AND mode='SWING'", (today,))

    if not reg.allows_swing:
        print("defensive regime -> running ALL-WEATHER scan")
        n_aw = _scan_all_weather(conn, today)
        conn.commit()
        conn.close()
        print(f"all-weather signals today: {n_aw}")
        return

    try:
        bok = breadth.breadth_ok(conn)
    except Exception:
        bok = True
    if not bok:
        conn.commit()
        conn.close()
        print("breadth weak -> no new signals today")
        return

    allowed = sector_gate.allowed_sectors()
    print(f"sector gate (top-{len(allowed)}): {', '.join(sorted(allowed)) or 'n/a'}")

    n = 0
    veto_skipped = 0
    for sym in universe(conn):
        if not sector_gate.passes(sym, allowed):
            continue
        rows = conn.execute(
            "SELECT date, close, high, low, volume FROM prices_daily WHERE symbol=? ORDER BY date",
            (sym,),
        ).fetchall()
        if len(rows) < 280:
            continue
        df = pd.DataFrame(list(rows), columns=["date", "Close", "High", "Low", "Volume"]).set_index(
            "date"
        )
        df.index = pd.to_datetime(df.index)
        sc = Screener.evaluate(df, sym)
        if not sc.passed:
            continue
        st = SetupDetector.detect(df, sym)
        if not st.triggered:
            continue

        last_bar_date = str(df.index[-1].date())
        if st.signal_date != last_bar_date:
            continue

        bad, why = _is_vetoed(sym, conn)
        if bad:
            veto_skipped += 1
            print(f"  [VETO] {sym} skipped — {why}")
            continue

        risk_pct = (st.entry_price - st.stop_loss) / st.entry_price
        conn.execute(
            "INSERT INTO swing_signals(signal_date, symbol, entry_trigger, "
            "stop, target, risk_pct, pullback, impulse, ema_zone, outcome, "
            "updated_at, mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                today,
                sym,
                st.entry_price,
                st.stop_loss,
                st.target_price,
                round(risk_pct * 100, 2),
                st.pullback_depth,
                st.impulse_pct,
                st.ema_proximity,
                "PENDING",
                dt.datetime.now().isoformat(),
                "SWING",
            ),
        )
        n += 1
        print(
            f"  OK {sym} trigger Rs {st.entry_price}  "
            f"SL Rs {st.stop_loss}  TGT Rs {st.target_price}  "
            f"risk {risk_pct:.1%}  zone {st.ema_proximity}"
        )
        try:
            from alerts import notify_setup

            notify_setup(st)
        except Exception as e:
            print(f"  alert skipped: {e}")
    conn.commit()
    conn.close()
    print(f"swing signals today: {n}  (veto-skipped: {veto_skipped})")


def update_outcomes():
    conn = db.get_conn()
    ensure(conn)
    pend = conn.execute(
        "SELECT rowid, signal_date, symbol, entry_trigger, stop, "
        "target FROM swing_signals WHERE outcome IN "
        "('PENDING','OPEN')"
    ).fetchall()
    for rowid, sd, sym, trig, stop, target in pend:
        rows = conn.execute(
            "SELECT date, high, low FROM prices_daily "
            "WHERE symbol=? AND date>? ORDER BY date LIMIT 35",
            (sym, sd),
        ).fetchall()
        trig_day = None
        for i in range(min(3, len(rows))):
            if rows[i][1] >= trig:
                trig_day = i
                break
        if trig_day is None:
            if len(rows) >= 3:
                conn.execute(
                    "UPDATE swing_signals SET outcome='EXPIRED', updated_at=? WHERE rowid=?",
                    (dt.datetime.now().isoformat(), rowid),
                )
            continue
        out = "OPEN"
        for _d, h, l in rows[trig_day:]:
            if l <= stop:
                out = "LOSS"
                break
            if h >= target:
                out = "WIN"
                break
        if out == "OPEN" and len(rows) >= 30:
            out = "TIMEOUT"
        if out != "OPEN":
            conn.execute(
                "UPDATE swing_signals SET outcome=?, updated_at=? WHERE rowid=?",
                (out, dt.datetime.now().isoformat(), rowid),
            )
    conn.commit()
    conn.close()


def report():
    conn = db.get_conn()
    ensure(conn)
    print("SWING SCORECARD:")
    for r in conn.execute(
        "SELECT outcome, COUNT(*) FROM swing_signals GROUP BY outcome ORDER BY outcome"
    ):
        print(f"   {r[0]:<8} {r[1]}")
    print("BY MODE:")
    for r in conn.execute("SELECT mode, COUNT(*) FROM swing_signals GROUP BY mode ORDER BY mode"):
        print(f"   {r[0] or 'SWING':<12} {r[1]}")
    conn.close()


def backfill(step=10, max_stocks=600):
    conn = db.get_conn()
    ensure(conn)
    syms = universe(conn)[:max_stocks]
    conn.close()
    n = 0
    for sym in syms:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, close, high, low, volume FROM prices_daily WHERE symbol=? ORDER BY date",
            (sym,),
        ).fetchall()
        conn.close()
        if len(rows) < 300:
            continue
        df = pd.DataFrame(list(rows), columns=["date", "Close", "High", "Low", "Volume"]).set_index(
            "date"
        )
        df.index = pd.to_datetime(df.index)
        conn = db.get_conn()
        for i in range(280, len(df), step):
            hist = df.iloc[:i]
            d = str(hist.index[-1])[:10]
            if conn.execute(
                "SELECT 1 FROM swing_signals WHERE symbol=? AND signal_date=?", (sym, d)
            ).fetchone():
                continue
            sc = Screener.evaluate(hist, sym)
            if not sc.passed:
                continue
            st = SetupDetector.detect(hist, sym)
            if not st.triggered:
                continue
            risk_pct = (st.entry_price - st.stop_loss) / st.entry_price
            conn.execute(
                "INSERT INTO swing_signals(signal_date, symbol, "
                "entry_trigger, stop, target, risk_pct, pullback, "
                "impulse, ema_zone, outcome, updated_at, mode) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    d,
                    sym,
                    st.entry_price,
                    st.stop_loss,
                    st.target_price,
                    round(risk_pct * 100, 2),
                    st.pullback_depth,
                    st.impulse_pct,
                    st.ema_proximity,
                    "PENDING",
                    dt.datetime.now().isoformat(),
                    "SWING",
                ),
            )
            n += 1
        conn.commit()
        conn.close()
    print(f"backfilled signals: {n}")
    update_outcomes()
    report()


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if mode == "backfill":
        backfill()
    elif mode == "aw":
        conn = db.get_conn()
        ensure(conn)
        today = dt.date.today().isoformat()
        n = _scan_all_weather(conn, today)
        conn.commit()
        conn.close()
        print(f"all-weather signals: {n}")
    else:
        update_outcomes()
        scan()
        report()
