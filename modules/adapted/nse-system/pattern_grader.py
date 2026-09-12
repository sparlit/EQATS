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
Pattern Hit-Rate Gate v4.
Grading rule (literature-compatible, stop-first):
  trigger  = breakout_level, must hit within 3 bars else EXPIRED
  LOSS     = low <= stop_level before win
  WIN      = high >= breakout + 1R   (R = breakout - stop)
  TIMEOUT  = neither within 45 bars
Gate rules (stored in settings.pattern_gate):
  graded >= 30 : ENABLED only if win-rate >= 60%
  graded >= 15 : PROVISIONAL, kept if win-rate >= 55%
  graded <  15 : PROVISIONAL (kept, not enough evidence)
  v4: patterns with NO grades yet stay enabled (provisional),
      so rare patterns (e.g. H&S top warning) keep flowing.
Usage:
  python pattern_grader.py grade     -> grade pending tags + report
  python pattern_grader.py regrade   -> clear grades, regrade all, report
  python pattern_grader.py report    -> print/save gate report only
  python pattern_grader.py stats     -> print raw per-pattern stats
"""
import datetime as dt
import json
import sys

import db

HOLD_BARS = 45
WIN_R = 1.0
MIN_GRADES_FOR_GATE = 30
MIN_WINRATE = 0.60
PROVISIONAL_GRADES = 15
PROVISIONAL_WINRATE = 0.55

ALL_PATTERNS = [
    "HIGH_TIGHT_FLAG",
    "ASCENDING_TRIANGLE",
    "DOUBLE_BOTTOM",
    "BULL_FLAG",
    "INVERSE_HEAD_SHOULDERS",
    "HEAD_SHOULDERS_TOP_WARNING",
]


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS pattern_grades(
        tag_date TEXT, symbol TEXT, pattern TEXT, outcome TEXT,
        exit_date TEXT, r_multiple REAL, graded_at TEXT,
        PRIMARY KEY(tag_date, symbol, pattern))""")


def _grade_one(conn, tag_date, symbol, breakout, stop):
    if not breakout or not stop or breakout <= stop:
        return None
    risk = breakout - stop
    target = breakout + WIN_R * risk
    rows = conn.execute(
        "SELECT date, high, low FROM prices_daily WHERE symbol=? AND date>? ORDER BY date LIMIT ?",
        (symbol, tag_date, HOLD_BARS + 5),
    ).fetchall()
    trig_idx = None
    for i in range(min(3, len(rows))):
        if rows[i][1] >= breakout:
            trig_idx = i
            break
    if trig_idx is None:
        if len(rows) >= 3:
            return ("EXPIRED", None, 0.0)
        return None
    out = "OPEN"
    exit_date = None
    for d, h, l in rows[trig_idx:]:
        if l <= stop:
            out = "LOSS"
            exit_date = d
            break
        if h >= target:
            out = "WIN"
            exit_date = d
            break
    if out == "OPEN":
        if len(rows) >= HOLD_BARS:
            out = "TIMEOUT"
            exit_date = rows[-1][0]
        else:
            return None
    r = {"WIN": 1.0, "LOSS": -1.0, "TIMEOUT": 0.0, "EXPIRED": 0.0}[out]
    return (out, exit_date, r)


def grade_all():
    conn = db.get_conn()
    _ensure(conn)
    tags = conn.execute("SELECT date, symbol, pattern, breakout_level, stop_level FROM pattern_tags").fetchall()
    done = 0
    pending = 0
    for td, sym, pat, brk, stp in tags:
        exists = conn.execute(
            "SELECT 1 FROM pattern_grades WHERE tag_date=? AND symbol=? AND pattern=?", (td, sym, pat)
        ).fetchone()
        if exists:
            continue
        res = _grade_one(conn, td, sym, brk, stp)
        if res is None:
            pending += 1
            continue
        out, exd, r = res
        conn.execute(
            "INSERT OR REPLACE INTO pattern_grades VALUES (?,?,?,?,?,?,?)",
            (td, sym, pat, out, exd, r, dt.datetime.now().isoformat(timespec="seconds")),
        )
        done += 1
        if done % 2000 == 0:
            conn.commit()
            print(f"[GRADE] {done} graded so far...")
    conn.commit()
    conn.close()
    print(f"[GRADE] complete: graded {done}, pending {pending}")
    return done


def stats():
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute("SELECT pattern, outcome, COUNT(*) FROM pattern_grades GROUP BY pattern, outcome").fetchall()
    conn.close()
    raw = {}
    for pat, out, n in rows:
        s = raw.setdefault(pat, {"wins": 0, "losses": 0, "expired": 0, "timeout": 0, "n": 0})
        s["n"] += n
        if out == "WIN":
            s["wins"] += n
        elif out == "LOSS":
            s["losses"] += n
        elif out == "EXPIRED":
            s["expired"] += n
        else:
            s["timeout"] += n
    out = {}
    for pat, s in raw.items():
        gl = s["wins"] + s["losses"]
        wr = s["wins"] / gl if gl else 0.0
        if gl >= MIN_GRADES_FOR_GATE:
            enabled = wr >= MIN_WINRATE
            status = "ENABLED" if enabled else "DISABLED"
        elif gl >= PROVISIONAL_GRADES:
            enabled = wr >= PROVISIONAL_WINRATE
            status = "PROVISIONAL"
        else:
            enabled = True
            status = "PROVISIONAL"
        out[pat] = {
            "wins": s["wins"],
            "losses": s["losses"],
            "expired": s["expired"],
            "timeout": s["timeout"],
            "n": s["n"],
            "graded": gl,
            "win_rate": round(wr, 3),
            "enabled": enabled,
            "status": status,
        }
    return out


def report(save_gate=True):
    st = stats()
    print(f"[PATTERN GATE] hit rates (WIN at +1R vs LOSS, stop-first, {HOLD_BARS}-bar window):")
    for pat, s in sorted(st.items()):
        print(
            f"   {pat:<28} n={s['graded']:<6} W/L={s['wins']}/{s['losses']}  WR={s['win_rate']:.1%}  -> {s['status']}"
        )
    if not st:
        print("   (no graded patterns yet)")
    if save_gate:
        conn = db.get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('pattern_gate',?)",
            (json.dumps({"date": dt.date.today().isoformat(), "gate": st}),),
        )
        conn.commit()
        conn.close()
    return st


def regrade():
    conn = db.get_conn()
    _ensure(conn)
    conn.execute("DELETE FROM pattern_grades")
    conn.commit()
    conn.close()
    print("[GRADE] cleared old grades, regrading with retuned rules")
    grade_all()
    return report()


def enabled_patterns(conn=None):
    """All known patterns EXCEPT explicitly disabled ones.
    Patterns with no grades yet stay enabled (provisional)."""
    own = conn is None
    if own:
        conn = db.get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key='pattern_gate'").fetchone()
    if own:
        conn.close()
    gate = {}
    if row:
        try:
            gate = json.loads(row[0]).get("gate", {})
        except Exception:
            gate = {}
    return {p for p in ALL_PATTERNS if gate.get(p, {}).get("enabled", True)}


def disabled_patterns(conn=None):
    return set(ALL_PATTERNS) - enabled_patterns(conn)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "grade":
        grade_all()
        report()
    elif cmd == "regrade":
        regrade()
    elif cmd == "stats":
        print(json.dumps(stats(), indent=1))
    else:
        report()
