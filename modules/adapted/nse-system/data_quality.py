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
Data Quality Monitor for NSE Intelligence.
Checks core tables, staleness, duplicates, OHLC integrity,
tracked-universe coverage, suspicious jumps. Logs + Telegram alert.
"""
import datetime as dt

import db

CRITICAL_STALE_DAYS = 5
WARN_STALE_DAYS = 3
RECENT_SYMBOL_DAYS = 10
MAX_MISSING_SYMBOLS_SHOWN = 20
SUSPICIOUS_JUMP_PCT = 0.35


def _today():
    return dt.date.today()


def _parse_date(x):
    if x is None:
        return None
    try:
        return dt.datetime.strptime(str(x)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _safe_send(text):
    try:
        import swing_alerts

        swing_alerts.send(text)
    except Exception as e:
        print(f"[DQ] telegram skipped: {e}")


def _ensure(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_quality_log(
            run_at TEXT, status TEXT, severity TEXT,
            check_name TEXT, message TEXT)
    """)


def _log(conn, rows, severity, check_name, message):
    status = "OK" if severity == "OK" else "ISSUE"
    rows.append(
        {
            "run_at": dt.datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "severity": severity,
            "check_name": check_name,
            "message": message,
        }
    )


def _table_exists(conn, table):
    r = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return r is not None


def _get_universe_symbols(conn):
    """Tracked universe = smallcap band + active core stocks."""
    symbols = set()
    if _table_exists(conn, "universe_broad"):
        try:
            rows = conn.execute(
                "SELECT symbol FROM universe_broad "
                "WHERE mcap_cr BETWEEN 1000 AND 8000 "
                "AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %'"
            ).fetchall()
            symbols.update(r[0] for r in rows)
        except Exception:
            pass
    if _table_exists(conn, "stocks"):
        try:
            rows = conn.execute("SELECT symbol FROM stocks WHERE active=1").fetchall()
            symbols.update(r[0] for r in rows)
        except Exception:
            pass
    return sorted(symbols)


def check_stale_price_date(conn, logs):
    if not _table_exists(conn, "prices_daily"):
        _log(conn, logs, "CRITICAL", "prices_daily_exists", "prices_daily table does not exist")
        return None
    r = conn.execute("SELECT MAX(date) FROM prices_daily").fetchone()
    max_date = _parse_date(r[0] if r else None)
    if max_date is None:
        _log(conn, logs, "CRITICAL", "latest_price_date", "No valid max(date) found in prices_daily")
        return None
    age = (_today() - max_date).days
    if age >= CRITICAL_STALE_DAYS:
        _log(conn, logs, "CRITICAL", "latest_price_date", f"Latest price date is stale: {max_date} ({age} days old)")
    elif age >= WARN_STALE_DAYS:
        _log(conn, logs, "WARN", "latest_price_date", f"Latest price date may be stale: {max_date} ({age} days old)")
    else:
        _log(conn, logs, "OK", "latest_price_date", f"Latest price date OK: {max_date} ({age} days old)")
    return max_date


def check_duplicate_rows(conn, logs):
    try:
        r = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT symbol, date, COUNT(*) AS n
                FROM prices_daily GROUP BY symbol, date HAVING n > 1)
        """).fetchone()
        dupes = int(r[0] or 0)
        if dupes:
            _log(conn, logs, "CRITICAL", "duplicate_prices", f"Duplicate symbol/date price rows found: {dupes}")
        else:
            _log(conn, logs, "OK", "duplicate_prices", "No duplicate symbol/date rows")
    except Exception as e:
        _log(conn, logs, "WARN", "duplicate_prices", f"Duplicate check skipped: {e}")


def check_invalid_ohlc(conn, logs):
    try:
        invalid = conn.execute("""
            SELECT COUNT(*) FROM prices_daily
            WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR high < low
               OR close > high * 1.02
               OR close < low * 0.98
        """).fetchone()[0]
        if invalid:
            _log(conn, logs, "CRITICAL", "invalid_ohlc", f"Invalid OHLC rows found: {invalid}")
        else:
            _log(conn, logs, "OK", "invalid_ohlc", "OHLC integrity OK")
    except Exception as e:
        _log(conn, logs, "WARN", "invalid_ohlc", f"OHLC check skipped: {e}")


def check_missing_recent_symbols(conn, logs, latest_date):
    if latest_date is None:
        return
    universe = _get_universe_symbols(conn)
    if not universe:
        _log(conn, logs, "WARN", "universe_coverage", "No tracked universe symbols found")
        return
    cutoff = latest_date - dt.timedelta(days=RECENT_SYMBOL_DAYS)
    recent_rows = conn.execute(
        "SELECT DISTINCT symbol FROM prices_daily WHERE date>=?", (cutoff.isoformat(),)
    ).fetchall()
    recent = {r[0] for r in recent_rows}
    missing = [s for s in universe if s not in recent]
    pct_missing = len(missing) / max(1, len(universe))
    if pct_missing > 0.25:
        sev = "CRITICAL"
    elif pct_missing > 0.10:
        sev = "WARN"
    else:
        sev = "OK"
    shown = ", ".join(missing[:MAX_MISSING_SYMBOLS_SHOWN])
    msg = f"Tracked symbols: {len(universe)}, missing recent data: {len(missing)} ({pct_missing:.1%})"
    if missing:
        msg += f". Examples: {shown}"
    _log(conn, logs, sev, "universe_recent_coverage", msg)


def check_suspicious_jumps(conn, logs):
    try:
        symbols = _get_universe_symbols(conn)
        bad = []
        for sym in symbols[:1500]:
            rows = conn.execute(
                "SELECT date, close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 12", (sym,)
            ).fetchall()
            rows = list(reversed(rows))
            if len(rows) < 2:
                continue
            for i in range(1, len(rows)):
                prev = rows[i - 1][1]
                cur = rows[i][1]
                if prev is None or cur is None or prev <= 0:
                    continue
                jump = abs((cur / prev) - 1)
                if jump >= SUSPICIOUS_JUMP_PCT:
                    bad.append((sym, rows[i][0], round(jump * 100, 1)))
                    break
        if bad:
            shown = ", ".join([f"{s} {d} {j}%" for s, d, j in bad[:15]])
            sev = "WARN" if len(bad) < 10 else "CRITICAL"
            _log(conn, logs, sev, "suspicious_price_jumps", f"Suspicious jumps found: {len(bad)}. {shown}")
        else:
            _log(conn, logs, "OK", "suspicious_price_jumps", "No suspicious recent jumps")
    except Exception as e:
        _log(conn, logs, "WARN", "suspicious_price_jumps", f"Jump check skipped: {e}")


def check_core_tables(conn, logs):
    required = ["prices_daily", "universe_broad", "swing_signals"]
    missing = [t for t in required if not _table_exists(conn, t)]
    if missing:
        _log(conn, logs, "CRITICAL", "core_tables", "Missing core tables: " + ", ".join(missing))
    else:
        _log(conn, logs, "OK", "core_tables", "Core tables exist")


def run(send_alert=True):
    conn = db.get_conn()
    _ensure(conn)
    logs = []
    check_core_tables(conn, logs)
    latest_date = check_stale_price_date(conn, logs)
    check_duplicate_rows(conn, logs)
    check_invalid_ohlc(conn, logs)
    check_missing_recent_symbols(conn, logs, latest_date)
    check_suspicious_jumps(conn, logs)

    conn.execute("DELETE FROM data_quality_log")
    for r in logs:
        conn.execute(
            "INSERT INTO data_quality_log VALUES (?,?,?,?,?)",
            (r["run_at"], r["status"], r["severity"], r["check_name"], r["message"]),
        )
    conn.commit()
    conn.close()

    critical = [r for r in logs if r["severity"] == "CRITICAL"]
    warns = [r for r in logs if r["severity"] == "WARN"]

    print("[DQ] DATA QUALITY REPORT")
    for r in logs:
        icon = "✅" if r["severity"] == "OK" else ("️" if r["severity"] == "WARN" else "🛑")
        print(f"[DQ] {icon} {r['check_name']}: {r['message']}")

    if send_alert and (critical or warns):
        lines = []
        if critical:
            lines.append(f"🛑 DATA QUALITY CRITICAL: {len(critical)}")
            for r in critical[:5]:
                lines.append(f"- {r['check_name']}: {r['message'][:180]}")
        if warns:
            lines.append(f"⚠️ DATA QUALITY WARNINGS: {len(warns)}")
            for r in warns[:5]:
                lines.append(f"- {r['check_name']}: {r['message'][:180]}")
        _safe_send("\n".join(lines))

    return {"critical": len(critical), "warnings": len(warns), "total_checks": len(logs)}


if __name__ == "__main__":
    print(run(send_alert=True))
