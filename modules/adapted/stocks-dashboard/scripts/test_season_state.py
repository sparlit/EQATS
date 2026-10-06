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


# -*- coding: utf-8 -*-
"""Replay test for scripts/season_state.py (runbook §222) — the automatic results-season switch.

Synthetic feeds are built from the stored announcement dates (docs/sf_fundamentals.json rows [qe, pat, ann, ...] for NSE
names; docs/bse_fundamentals.json px[scrip][qe].ann for BSE-only names), one feed row per company-quarter, trimmed to the
feed's rolling 31 days, and replayed day by day through four seasons: Jun-2026, Mar-2026, Dec-2025, Sep-2025. The real
feed counts every result filing (revisions, names without stored numbers), so it runs HIGHER than this replay — live,
ignition can only come sooner than here, never later.

For each season (quarter end QE, SEBI deadline D) it asserts:
  A  OFF on QE+1 .. QE+8, end-of-day view         the previous quarter's late-filer trickle never opens a season
  B  IN by QE+15, end-of-day view                  within a day or two of the first real filing day
  C  IN every day after the first IN through D+3   no flaps across weekends / Diwali inside the window (morning view too)
  D  IN on the MORNING of the first working day after D, before its filings land (the post-deadline Monday flood)
  E  OFF by D+8, morning view                      the tail is cut 1-2 days after the collapse
Plus: the live feed evaluates and --vision-slot agrees with the state; a stale/empty feed reads IN inside the window and
OFF outside; vision_slot RUN/SKIP per slot and state; the routine's fixed cron matches VISION_SLOTS_UTC; cron_dispatch
picks the tagged slots per state.

  python3 scripts/test_season_state.py            (~5 s; reads the two JSONs, writes nothing)
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.chdir(ROOT)
import cron_dispatch as CD  # noqa: E402
import season_state as S  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ann_by_day():
    """{'YYYY-MM-DD': filings} from the stored announcement dates, NSE + BSE-only."""
    by = {}

    def add(a):
        if not isinstance(a, int) or a < 20000000:
            return
        try:
            d = dt.date(a // 10000, (a // 100) % 100, a % 100)
        except ValueError:
            return
        by[d.isoformat()] = by.get(d.isoformat(), 0) + 1

    sf = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    for rows in sf.values():
        for r in rows:
            if r and len(r) > 2:
                add(r[2])
    n_nse = sum(by.values())
    bf = json.load(open(os.path.join(ROOT, "docs", "bse_fundamentals.json"), encoding="utf-8")).get(
        "px", {}
    )
    for qs in bf.values():
        for d in qs.values():
            add((d or {}).get("ann"))
    print("synthetic feed: %d NSE + %d BSE announcement dates" % (n_nse, sum(by.values()) - n_nse))
    return by


def rows_for(by, day, include_today):
    """The feed as it would look on `day`: rows dated within the last 31 days, today's only if include_today."""
    lo = (day - dt.timedelta(days=31)).isoformat()
    hi = day.isoformat()
    out = []
    for k, n in by.items():
        if k < lo or k > hi or (k == hi and not include_today):
            continue
        out.extend([["X", "", k + " 18:00:00", 0, "", ""]] * n)
    return out


def state_on(by, day, include_today):
    # end-of-day view = 23:59 IST = 18:29 UTC; morning view = 09:00 IST = 03:30 UTC
    now = dt.datetime(
        day.year,
        day.month,
        day.day,
        18 if include_today else 3,
        29 if include_today else 30,
        tzinfo=dt.UTC,
    )
    return S.evaluate(now, rows=rows_for(by, day, include_today))["state"]


def next_working_day(d):
    d += dt.timedelta(days=1)
    while d.isoweekday() >= 6:
        d += dt.timedelta(days=1)
    return d


def replay(by, label, qe, deadline):
    print(
        f"\n== {label}  (QE {qe}, deadline {deadline}, window {qe + dt.timedelta(days=S.WINDOW_OPEN_DAYS)} .. {deadline + dt.timedelta(days=S.WINDOW_CLOSE_DAYS)})"
    )
    days = [qe + dt.timedelta(days=i) for i in range(1, (deadline - qe).days + 12)]
    eod = {d: state_on(by, d, True) for d in days}
    morn = {d: state_on(by, d, False) for d in days}
    # timeline of transitions (end-of-day view)
    prev, trans = None, []
    for d in days:
        if eod[d] != prev:
            trans.append(f"{d} {eod[d].upper()}")
            prev = eod[d]
    print("  end-of-day transitions: " + "  ->  ".join(trans))
    prev, trans = None, []
    for d in days:
        if morn[d] != prev:
            trans.append(f"{d} {morn[d].upper()}")
            prev = morn[d]
    print("  morning    transitions: " + "  ->  ".join(trans))
    peak = max(days, key=lambda d: by.get(d.isoformat(), 0))
    print(
        "  peak day %s: %d filings; first working day after the deadline %s: %d filings"
        % (
            peak,
            by.get(peak.isoformat(), 0),
            next_working_day(deadline),
            by.get(next_working_day(deadline).isoformat(), 0),
        )
    )

    first_in = next((d for d in days if eod[d] == "in"), None)
    check(
        all(eod[qe + dt.timedelta(days=i)] == "off" for i in range(1, 9)),
        "A  OFF through QE+8 (trickle never ignites)",
    )
    check(
        first_in is not None and first_in <= qe + dt.timedelta(days=15),
        "B  IN by QE+15 (first IN {} = QE+{})".format(
            first_in, (first_in - qe).days if first_in else "-"
        ),
    )
    close = deadline + dt.timedelta(days=S.WINDOW_CLOSE_DAYS)
    if first_in:
        span = [d for d in days if first_in <= d <= close]
        flaps = [d for d in span if eod[d] != "in"] + [
            d for d in span if d > first_in and morn[d] != "in"
        ]
        check(
            not flaps,
            f"C  IN every day {first_in} .. {close}, both views (flaps: {[str(x) for x in flaps][:5]})",
        )
    nwd = next_working_day(deadline)
    check(
        morn.get(nwd) == "in",
        f"D  IN on the morning of {nwd}, the first working day after the deadline",
    )
    first_off = next((d for d in days if d > deadline and morn[d] == "off"), None)
    check(
        first_off is not None and first_off <= deadline + dt.timedelta(days=8),
        "E  OFF by D+8 in the morning view (first OFF {} = D+{})".format(
            first_off, (first_off - deadline).days if first_off else "-"
        ),
    )


def main():
    by = ann_by_day()
    replay(by, "Jun-2026 season (Q1 FY27)", dt.date(2026, 6, 30), dt.date(2026, 8, 14))
    replay(by, "Mar-2026 season (Q4 FY26)", dt.date(2026, 3, 31), dt.date(2026, 5, 30))
    replay(by, "Dec-2025 season (Q3 FY26)", dt.date(2025, 12, 31), dt.date(2026, 2, 14))
    replay(by, "Sep-2025 season (Q2 FY26)", dt.date(2025, 9, 30), dt.date(2025, 11, 14))

    print("\n== live feed + edge cases")
    live = S.evaluate()
    print("  live: " + live["summary"])
    check(
        live["state"] in ("in", "off")
        and len(live["vision"]["slots_ist"]) == (4 if live["state"] == "in" else 1),
        "live feed evaluates; vision slot list matches the state",
    )
    now = dt.datetime.now(dt.UTC)
    ok, slot = S.vision_slot(now, live["state"])
    check(
        isinstance(ok, bool) and slot,
        "vision_slot answers for now ({} {})".format("RUN" if ok else "SKIP", slot),
    )
    # empty / stale feed
    check(
        S.evaluate(dt.datetime(2026, 10, 20, 6, 0, tzinfo=dt.UTC), rows=[])["state"] == "in",
        "empty feed inside the window -> IN (fail open)",
    )
    check(
        S.evaluate(dt.datetime(2026, 9, 20, 6, 0, tzinfo=dt.UTC), rows=[])["state"] == "off",
        "empty feed outside the window -> OFF",
    )
    # calendar
    for d, qe, dl in (
        (dt.date(2026, 10, 6), "2026-09-30", "2026-11-14"),
        (dt.date(2026, 1, 5), "2025-12-31", "2026-02-14"),
        (dt.date(2026, 4, 2), "2026-03-31", "2026-05-30"),
        (dt.date(2026, 12, 31), "2026-09-30", "2026-11-14"),
        (dt.date(2026, 7, 1), "2026-06-30", "2026-08-14"),
    ):
        c = S.calendar(d)
        check(
            c["qe"].isoformat() == qe and c["deadline"].isoformat() == dl,
            "calendar({}): qe {} deadline {}".format(d, c["qe"], c["deadline"]),
        )

    # vision slots
    def T(h, m):
        return dt.datetime(2026, 10, 6, h, m, tzinfo=dt.UTC)

    check(
        S.vision_slot(T(18, 46), "off")[0] is True, "off-season 18:46Z -> RUN (the 00:15 IST slot)"
    )
    check(S.vision_slot(T(7, 46), "off")[0] is False, "off-season 07:46Z -> SKIP")
    check(S.vision_slot(T(10, 50), "off")[0] is False, "off-season 10:50Z -> SKIP")
    check(S.vision_slot(T(15, 47), "off")[0] is False, "off-season 15:47Z -> SKIP")
    check(
        all(S.vision_slot(T(h, 46), "in")[0] for h in (7, 10, 15, 18)),
        "in-season every slot -> RUN",
    )
    check(S.vision_slot(T(5, 0), "off")[0] is True, "no slot in the last 3 h (manual run) -> RUN")
    cron = CD.Cron(S.VISION_CRON)
    fired = sorted(
        {
            (t.hour, t.minute)
            for t in (
                dt.datetime(2026, 10, 6, tzinfo=dt.UTC) + dt.timedelta(minutes=i)
                for i in range(1440)
            )
            if cron.match(t)
        }
    )
    check(
        fired == sorted(S.VISION_SLOTS_UTC["in"]),
        f"VISION_CRON {S.VISION_CRON} fires exactly the in-season slots {fired}",
    )
    # dispatcher picks tagged slots per state
    F, R, B = (
        ".github/workflows/refresh-fundamentals.yml",
        ".github/workflows/refresh-results-hourly.yml",
        ".github/workflows/refresh-bse.yml",
    )
    off, on = CD.load_schedules("off"), CD.load_schedules("in")

    def ex(m, f):
        return [c.expr for c in m.get(f, [])]

    check(
        ex(off, F) == ["0 4-14 * * *"] and ex(on, F) == ["0,30 4-14 * * *"],
        f"dispatcher: refresh-fundamentals off {ex(off, F)} / in {ex(on, F)}",
    )
    check(
        ex(off, R) == ["0 3,7,11,15,17,19 * * *"] and ex(on, R) == ["0 3-19 * * *"],
        f"dispatcher: refresh-results-hourly off {ex(off, R)} / in {ex(on, R)}",
    )
    check(
        ex(off, B) == ex(on, B) and len(ex(off, B)) == 2,
        f"dispatcher: untagged refresh-bse identical in both states {ex(off, B)}",
    )
    # the dispatcher's own season() agrees with season_state on the live feed
    st, line = CD.season(now)
    check(st == live["state"], f"cron_dispatch.season() == season_state ({st})")

    print(
        "\n%s"
        % (
            "ALL CHECKS PASSED"
            if not FAILS
            else "%d CHECK(S) FAILED:\n  " % len(FAILS) + "\n  ".join(FAILS)
        )
    )
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
