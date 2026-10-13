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
"""BSE live prices for Top Movers' live 1D (runbook §216).

BSE's data API refuses Cloudflare's network (Akamai 403 to the Worker, measured 2026-09-28) while it serves GitHub's
runners, so this job polls BSE's market-watch list (GetMktData = every scrip that traded today, SME groups M/MT
included) about once a minute during market hours and publishes it as bse_live.json on the orphan branch `live-bse`.
docs/movers.html reads it from raw.githubusercontent.com (CORS *, cached ~300 s by GitHub).

Why a separate branch: a push to main under docs/ triggers a Pages deploy — ~375 deploys a day would jam the Pages
queue (see pages.yml header). The branch always holds ONE commit (no parent), so it never grows.

Output shape (same as the Worker's ?bse=1 route):
  {"asOf": <ms>, "source": "bse", "timestamp": "YYYY-MM-DDTHH:MM:SS",
   "data": {"<scripCode>": [ltp, prevClose, pchange, "<scripId>"], ...}}

Usage: python3 scripts/fetch_bse_live.py [--until HH:MM] [--interval 60] [--once] [--no-push]
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_headers  # noqa: E402,F401  — installs the standard BSE header set on every urllib request

URL = "https://api.bseindia.com/BseIndiaAPI/api/GetMktData/w?ordcol=TT&strType=gainer&strfilter=All"
BRANCH = "live-bse"
FILE = "bse_live.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def now_ist():
    return dt.datetime.now(IST)


def fetch():
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # transient network / BSE hiccup: retry, then give up this round
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"BSE fetch failed after 3 tries: {last}")


def compact(j):
    rows = j.get("Table") if isinstance(j, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("BSE reply has no Table list")
    data, ts = {}, ""
    for x in rows:
        try:
            ltp, prev = float(x.get("ltradert")), float(x.get("prevdayclose"))
        except (TypeError, ValueError):
            continue
        if not x.get("scrip_cd") or not ltp > 0 or not prev > 0:
            continue
        try:
            pchg = float(x.get("change_percent"))
        except (TypeError, ValueError):
            pchg = round((ltp - prev) / prev * 100, 2)
        data[str(x["scrip_cd"])] = [ltp, prev, pchg, x.get("scripname") or ""]
        if (x.get("dt_tm") or "") > ts:
            ts = x["dt_tm"]
    if not data:
        raise RuntimeError("BSE reply had no usable rows")
    return {"asOf": int(time.time() * 1000), "source": "bse", "timestamp": ts[:19], "data": data}


def push(body):
    """Replace the live-bse branch with ONE parentless commit holding bse_live.json."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        blob = subprocess.check_output(["git", "hash-object", "-w", path], text=True).strip()
        tree = subprocess.check_output(
            ["git", "mktree"], input=f"100644 blob {blob}\t{FILE}\n", text=True
        ).strip()
        commit = subprocess.check_output(
            [
                "git",
                "commit-tree",
                tree,
                "-m",
                "BSE live prices {}".format(now_ist().strftime("%Y-%m-%d %H:%M IST")),
            ],
            text=True,
        ).strip()
        # force is intended and safe here: live-bse is a single-file data branch nothing else writes
        subprocess.check_call(
            ["git", "push", "-q", "--force", "origin", f"{commit}:refs/heads/{BRANCH}"]
        )
    finally:
        os.unlink(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="15:40", help="stop at this IST time (HH:MM)")
    ap.add_argument("--interval", type=int, default=60, help="seconds between polls")
    ap.add_argument(
        "--max-minutes",
        type=int,
        default=345,
        help="also stop after this many minutes (GitHub job cap is 6 h)",
    )
    ap.add_argument("--once", action="store_true")
    ap.add_argument(
        "--no-push", action="store_true", help="write ./bse_live.json instead of pushing"
    )
    a = ap.parse_args()
    hh, mm = map(int, a.until.split(":"))
    stop = min(
        now_ist().replace(hour=hh, minute=mm, second=0, microsecond=0),
        now_ist() + dt.timedelta(minutes=a.max_minutes),
    )

    last_ts, pushes, fails = None, 0, 0
    while True:
        t0 = time.time()
        try:
            out = compact(fetch())
            today = now_ist().strftime("%Y-%m-%d")
            if (
                out["timestamp"][:10] < today
                and now_ist().hour * 60 + now_ist().minute >= 9 * 60 + 45
            ):
                # 30 min after the open and BSE still shows an older session: market holiday — nothing to poll
                print(
                    "BSE still shows {} at {} — market closed today, stopping".format(
                        out["timestamp"], now_ist().strftime("%H:%M")
                    ),
                    flush=True,
                )
                open(os.environ.get("BSE_LIVE_HOLIDAY_FLAG", os.devnull), "w").write("1")
                break
            if (
                out["timestamp"] != last_ts
            ):  # BSE's own clock moved — publish; unchanged data isn't re-pushed
                body = json.dumps(out, separators=(",", ":"))
                if a.no_push:
                    open(FILE, "w").write(body)
                else:
                    push(body)
                pushes += 1
                last_ts = out["timestamp"]
                print(
                    "%s  %d scrips, BSE time %s, published"
                    % (now_ist().strftime("%H:%M:%S"), len(out["data"]), last_ts),
                    flush=True,
                )
            fails = 0
        except Exception as e:
            fails += 1
            print(
                "%s  round failed (%d in a row): %s" % (now_ist().strftime("%H:%M:%S"), fails, e),
                flush=True,
            )
            if fails >= 15:
                print("::error::BSE live poll failed 15 rounds in a row — stopping", flush=True)
                sys.exit(1)
        if a.once or now_ist() >= stop:
            break
        time.sleep(max(1, a.interval - (time.time() - t0)))
    print("done: %d publishes" % pushes)
    if pushes == 0 and not a.once:
        print("::warning::no BSE data published this run (holiday, or BSE unreachable)")


if __name__ == "__main__":
    main()
