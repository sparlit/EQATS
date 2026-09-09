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


"""System watchdog: silent when healthy, loud when something rots.

    python scripts/health.py        # cron: every 4 waking hours

Checks the things that fail silently; on ANY failure fires a macOS
notification so breakage is noticed the day it happens, not at month-end.
Always appends one line to health.log so the watchdog itself is auditable.
"""
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILURES = []


def check(name, ok, detail=""):
    if not ok:
        FAILURES.append(f"{name}: {detail}")


def weekdays_ago(n):
    d, left = date.today(), n
    while left > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def month_end_catchup():
    """Step 0 — self-heal: if the 23:00 month-end cron was slept through,
    log the SAME formation (asof pinned to month-end) within the 3-day
    window PROTOCOL_GOLIVE gate 1 permits for automated catch-up."""
    today = date.today()
    prev_end = today.replace(day=1) - timedelta(days=1)
    if (today - prev_end).days > 3:
        return  # window closed; humans FAIL
    plog = ROOT / "paper" / "log.csv"
    if plog.exists():
        entries = {l.split(",")[0] for l in plog.read_text().strip().split("\n")[1:]}
        if any(e[:7] == prev_end.isoformat()[:7] and int(e[8:]) >= 24 for e in entries):
            return  # month-end entry present
    # if month-end was a trading weekday, wait (up to 2 days) for its
    # bhav file — else we'd pin the formation to the wrong day; on day 3
    # run regardless (holiday month-ends have no file, correctly)
    if (
        prev_end.weekday() < 5
        and not (ROOT / "data" / "bhav" / f"{prev_end.isoformat()}.parquet").exists()
        and (today - prev_end).days < 3
    ):
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} AUTO-CATCHUP waiting for {prev_end} bhav before logging")
        return
    r = subprocess.run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "-c",
            (f"from screener.paper_log import snapshot; snapshot(asof='{prev_end.isoformat()}')"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    tag = "AUTO-CATCHUP ok" if r.returncode == 0 else "AUTO-CATCHUP FAILED"
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} {tag} (month-end {prev_end})")
    if r.returncode != 0:
        check("catchup", False, r.stderr.strip()[-120:])


def panel_catchup():
    """Step 0b — self-heal a slept-through DAILY cron (added 2026-08-28
    after four consecutive 19:30 pulls were missed: the laptop is now
    asleep by 19:30, so daily.py never ran and its own trailing-week
    backfill never got the chance to help). If the panel is more than 2
    trading days stale, run the daily pull now. Once it succeeds the
    panel is fresh and this is a no-op."""
    bhav = sorted((ROOT / "data" / "bhav").glob("*.parquet"))
    if not bhav:
        return
    last = date.fromisoformat(bhav[-1].stem)
    if last >= weekdays_ago(2):
        return
    r = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "daily.py"], cwd=ROOT, capture_output=True, text=True, timeout=3600
    )
    tag = "PANEL-CATCHUP ok" if r.returncode == 0 else "PANEL-CATCHUP FAILED"
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} {tag} (panel was {last})")


def main():
    panel_catchup()
    month_end_catchup()
    # 1. price panel freshness (allow 2 trading days of lag: NSE evening
    #    publication + one slept-through cron)
    bhav = sorted((ROOT / "data" / "bhav").glob("*.parquet"))
    check("panel", bool(bhav), "no bhav files at all")
    if bhav:
        last = date.fromisoformat(bhav[-1].stem)
        check("panel-freshness", last >= weekdays_ago(3), f"latest bhav is {last} (>3 trading days old)")

    # 2. daily cron ran recently and cleanly
    clog = ROOT / "cron.log"
    check("cron.log", clog.exists(), "daily cron has never written its log")
    if clog.exists():
        age = datetime.now() - datetime.fromtimestamp(clog.stat().st_mtime)
        check("cron-recency", age < timedelta(days=4), f"cron.log last written {age.days}d ago")
        tail = clog.read_text()[-4000:]
        check("cron-errors", "Traceback" not in tail, "Traceback in recent cron.log")

    # 3. paper trial log + month-end entry (checked from the 3rd onward)
    plog = ROOT / "paper" / "log.csv"
    check("paper-log", plog.exists(), "paper/log.csv missing")
    if plog.exists() and date.today().day >= 3:
        lines = plog.read_text().strip().split("\n")[1:]
        last_entry = date.fromisoformat(lines[-1].split(",")[0])
        check(
            "month-end-entry",
            (date.today() - last_entry).days <= 35,
            f"last paper entry {last_entry} — month-end snapshot missed?",
        )

    # 4. status.json valid
    try:
        json.loads((ROOT / "paper" / "status.json").read_text())
    except Exception as e:
        check("status.json", False, str(e))

    # 5. live site serves the same title as the local docs (a Pages
    #    deployment can fail silently — e.g. the 2026-08-06 race where
    #    two quick pushes left the site stale until manually noticed)
    try:
        import re
        import urllib.request

        local = re.search(r"<title>([^<]+)", (ROOT / "docs" / "index.html").read_text()).group(1)
        req = urllib.request.Request(
            "https://deshpanda.github.io/nse-screener/", headers={"User-Agent": "health-check"}
        )
        live = re.search(r"<title>([^<]+)", urllib.request.urlopen(req, timeout=30).read().decode()).group(1)
        check(
            "site-deploy",
            live == local,
            f"live title {live!r} != local {local!r} — Pages deploy stale/failed; push an empty commit to retrigger",
        )
    except Exception:
        pass  # offline is not a failure

    # 6. git remote reachable with cron-like env (publish path works)
    r = subprocess.run(["git", "fetch", "origin", "--dry-run"], cwd=ROOT, capture_output=True, timeout=60)
    check("git-remote", r.returncode == 0, r.stderr.decode()[:80] if r.returncode else "")

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if FAILURES:
        msg = "; ".join(FAILURES)[:200]
        print(f"{stamp} FAIL {msg}")
        subprocess.run(
            [
                "osascript",
                "-e",
                (f'display notification "{msg}" with title "nse-screener: HEALTH CHECK FAILED" sound name "Basso"'),
            ]
        )
        sys.exit(1)
    print(f"{stamp} OK")


if __name__ == "__main__":
    main()
