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


import datetime as dt
import sys

import db
import scoring

MIN_FUND = 65
MIN_ML = 55
MAX_RECOMMEND = 25


def run():
    conn = db.get_conn()
    today = dt.date.today().isoformat()
    conn.execute("DELETE FROM scan_results WHERE scan_date=?", (today,))
    conn.execute("DELETE FROM scan_reasons WHERE scan_date=?", (today,))
    medians = scoring.sector_pe_medians(conn)
    stocks = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1 ORDER BY symbol")]

    mlmap = {}
    for s, v in conn.execute(
        "SELECT symbol, final_ml_score FROM ml_predictions "
        "WHERE prediction_date=(SELECT MAX(prediction_date) "
        "FROM ml_predictions)"
    ).fetchall():
        mlmap[s] = v
    sentmap = {}
    for s, v in conn.execute(
        "SELECT symbol, sentiment_score FROM sentiment_results WHERE created_at >= date('now','-7 days')"
    ).fetchall():
        sentmap[s] = v
    pending = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT symbol FROM corp_calendar "
            "WHERE kind='RESULTS' AND event_date>=date('now') "
            "AND event_date<=date('now','+7 days')"
        )
    }

    allres = []
    for sym in stocks:
        r = scoring.score_stock(conn, sym, medians)
        if r is None or r["composite"] is None:
            continue
        allres.append(r)

    eligible = []
    for r in allres:
        sym = r["symbol"]
        if not all(g[1] for g in r["gates"]):
            continue
        if r["incomplete"] or r["above200"] is not True:
            continue
        mv = mlmap.get(sym)
        if r["composite"] < MIN_FUND or mv is None or mv < MIN_ML:
            continue
        if sym in pending:
            continue
        sv = sentmap.get(sym)
        if sv is not None and sv < 50:
            continue
        r["blend"] = round(0.6 * r["composite"] + 0.4 * mv, 1)
        eligible.append(r)
    eligible.sort(key=lambda r: -r["blend"])
    rec_set = {r["symbol"] for r in eligible[:MAX_RECOMMEND]}

    passed = 0
    results = []
    for r in allres:
        sym = r["symbol"]
        passed_all = all(g[1] for g in r["gates"])
        recommend = sym in rec_set
        passed += passed_all

        flags = []
        if r["incomplete"]:
            flags.append("incomplete data")
        if r["above200"] is False:
            flags.append("below 200DMA")
        if sym in pending:
            flags.append("results pending")
        conn.execute(
            "INSERT OR REPLACE INTO scan_results VALUES (?,?,?,?,?,?,?)",
            (today, sym, 1 if passed_all else 0, r["composite"], r.get("blend"), "; ".join(flags), None),
        )

        for name, ok, actual, expected, reason in r["gates"]:
            conn.execute(
                "INSERT INTO scan_reasons VALUES (?,?,?,?,?,?,?)",
                (
                    today,
                    sym,
                    name,
                    1 if ok else 0,
                    actual if isinstance(actual, (int, float)) else None,
                    str(expected),
                    reason,
                ),
            )
        for name, sc, w in [("ROCE", r["roce_s"], 40), ("Growth", r["growth_s"], 30), ("Valuation", r["val_s"], 30)]:
            conn.execute(
                "INSERT INTO scan_reasons VALUES (?,?,?,?,?,?,?)",
                (
                    today,
                    sym,
                    f"BAND {name} (w{w}%)",
                    1 if sc is not None else 0,
                    sc,
                    "",
                    f"{name} score {sc}" if sc is not None else f"{name} data missing",
                ),
            )

        cur = conn.execute("SELECT status FROM pipeline WHERE symbol=?", (sym,)).fetchone()
        status = cur[0] if cur else None
        protected = {"Watchlisted", "Invested", "Review", "Discarded"}
        now = dt.datetime.now().isoformat()
        if recommend and status not in protected and status != "Recommended":
            conn.execute(
                "INSERT INTO pipeline(symbol,status,added_date,"
                "updated_date,reason) VALUES(?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET "
                "status=excluded.status, "
                "updated_date=excluded.updated_date, "
                "reason=excluded.reason",
                (sym, "Recommended", now, now, f"Auto: blended {r['blend']}"),
            )
        elif not recommend and status == "Recommended":
            conn.execute(
                "UPDATE pipeline SET status='Passed Scan', "
                "updated_date=?, reason='Auto: agreement lost' "
                "WHERE symbol=?",
                (now, sym),
            )
        elif passed_all and status is None:
            conn.execute(
                "INSERT INTO pipeline(symbol,status,added_date,updated_date,reason) VALUES(?,?,?,?,?)",
                (sym, "Passed Scan", now, now, "Auto: all gates passed"),
            )
        results.append((sym, r["composite"], r.get("blend"), passed_all, recommend))

    conn.commit()
    results.sort(key=lambda x: -(x[2] or 0))
    print(
        f"Scan {today}: scored {len(results)} | passed {passed} | eligible {len(eligible)} | recommended {len(rec_set)}"
    )
    print("TOP 10 BY BLEND:")
    for sym, comp, bl, p, rc in results[:10]:
        tag = "REC" if rc else ("PASS" if p else "-")
        print(f"  {sym:<12} fund {comp:>5}  blend {bl or 0:>5}  {tag}")
    conn.close()


if len(sys.argv) > 1 and sys.argv[1] == "run":
    run()
