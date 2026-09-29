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
Compare tool — side-by-side metrics for 2-4 symbols.

Reads only from existing tables + caches. No on-demand compute.
Symbols with uncached research stats simply show '—' in those rows.

Usage:
  python compare_tool.py TANLA KPITTECH DIXON
"""
import json
import sys

import db


def _row(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchone()
    except Exception:
        return None


def compare(symbols, max_n=4):
    symbols = [s.strip().upper() for s in symbols if s and s.strip()][:max_n]
    conn = db.get_conn()
    rows = []
    for sym in symbols:
        r = {"symbol": sym}

        # Sector + mcap
        row = _row(conn, "SELECT sector FROM stocks WHERE symbol=?", (sym,))
        r["sector"] = row[0] if row else None
        row = _row(conn, "SELECT mcap_cr, close, pe, perf1m, perf3m FROM universe_broad WHERE symbol=?", (sym,))
        if row:
            r["mcap_cr"] = row[0]
            r["close"] = row[1]
            r["pe"] = row[2]
            r["perf1m"] = row[3]
            r["perf3m"] = row[4]

        # Fundamentals
        row = _row(
            conn,
            "SELECT roce, roe, pe, debt_to_equity, "
            "operating_margin, net_profit_margin "
            "FROM fundamentals WHERE symbol=?",
            (sym,),
        )
        if row:
            r["roce"] = row[0]
            r["roe"] = row[1]
            if r.get("pe") is None:
                r["pe"] = row[2]
            r["debt_to_equity"] = row[3]
            r["operating_margin"] = row[4]
            r["net_profit_margin"] = row[5]

        # Fundamental score
        row = _row(
            conn, "SELECT fundamental_score FROM scan_results WHERE symbol=? ORDER BY scan_date DESC LIMIT 1", (sym,)
        )
        r["fund_score"] = row[0] if row else None

        # P(WIN)
        row = _row(conn, "SELECT p_win FROM pwin_daily WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,))
        r["p_win"] = row[0] if row else None

        # Swing stats
        row = _row(
            conn,
            "SELECT COUNT(*), "
            "COALESCE(SUM(outcome='WIN'),0), "
            "COALESCE(SUM(outcome='LOSS'),0) "
            "FROM swing_signals WHERE symbol=?",
            (sym,),
        )
        if row:
            r["swing_total"] = row[0] or 0
            r["swing_wins"] = row[1] or 0
            r["swing_losses"] = row[2] or 0

        # Latest pattern
        row = _row(
            conn,
            "SELECT pattern, direction, status, confidence "
            "FROM pattern_tags WHERE symbol=? "
            "ORDER BY date DESC, confidence DESC LIMIT 1",
            (sym,),
        )
        if row:
            r["pattern"] = row[0]
            r["pattern_direction"] = row[1]
            r["pattern_status"] = row[2]
            r["pattern_confidence"] = row[3]

        # Research cache — historical + candle + signature
        try:
            cached = _row(conn, "SELECT payload FROM research_cache WHERE symbol=?", (sym,))
            if cached:
                payload = json.loads(cached[0])
                h = payload.get("historical") or {}
                r["hist_n_setups"] = h.get("n_setups")
                r["hist_n_triggered"] = h.get("n_triggered")
                r["hist_p_1r"] = h.get("p_1r_given_trigger")
                r["hist_p_2r"] = h.get("p_2r_given_trigger")
                r["hist_median_mfe_r"] = h.get("median_mfe_r")
                r["hist_median_mae_r"] = h.get("median_mae_r")

                cs = payload.get("candle_stats") or {}
                best = None
                for mt, s in cs.items():
                    if s.get("p_2r") is None:
                        continue
                    if (s.get("n_triggered") or 0) < 2:
                        continue
                    if best is None or s["p_2r"] > best[1]:
                        best = (mt, s["p_2r"], s["n_triggered"])
                if best:
                    r["best_candle"] = best[0]
                    r["best_candle_p2r"] = best[1]

                sm = payload.get("signature_match") or {}
                if not sm.get("error"):
                    r["sig_p_2r"] = sm.get("p_2r")
                    r["sig_matches"] = sm.get("k")
                    r["sig_pool"] = sm.get("n_pool")

                cs_setup = payload.get("current_setup")
                if cs_setup:
                    r["live_setup"] = True
                    r["live_entry"] = cs_setup.get("entry")
                    r["live_stop"] = cs_setup.get("stop")
                    r["live_mother"] = cs_setup.get("mother_type")
        except Exception:
            pass

        rows.append(r)

    conn.close()
    return {"symbols": symbols, "rows": rows}


if __name__ == "__main__":
    syms = sys.argv[1:] if len(sys.argv) > 1 else ["TANLA", "KPITTECH"]
    print(json.dumps(compare(syms), indent=2, default=str))
