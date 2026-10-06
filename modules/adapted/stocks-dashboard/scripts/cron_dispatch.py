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
"""Start scheduled workflows on time — GitHub's own cron runs 4-7 h late in this repo (runbook §217).

Measured 2026-09-27..29 over 45 scheduled workflows: median start 4-7 h after the slot (refresh-bse 6 h, portfolio-feed
ran 2 of 32 slots, ci-janitor 8 of 83, bse-live's 09:10 IST slot not at all). So schedules no longer live in `on:
schedule:`. Each workflow carries its slots as comment lines

    # dispatch-cron: "20 4 * * *"

(UTC, standard 5-field cron) plus `repository_dispatch: types: [tick-<file stem>]`. cron-dispatch.yml runs this script
on every cron-job.org tick (~5 min). For each workflow it takes the most recent slot in (now-180 min, now-2 min]; if
the workflow has no run created since one minute before that slot (any trigger — a manual or cron-job.org run counts),
it sends repository_dispatch "tick-<stem>" with client_payload {"schedule": "<cron>", "slot": "<ISO UTC>"}. A missed
tick is caught by the next one; a slot older than 3 h is dropped rather than run absurdly late.

Workflows that read github.event.schedule to pick a slot-specific branch must also read
github.event.client_payload.schedule (refresh-shareholding does).

RESULTS-SEASON CADENCE (runbook §222). A slot line may carry a tag:

    # dispatch-cron[in-season]: "0,30 4-14 * * *"
    # dispatch-cron[off-season]: "0 4-14 * * *"

Untagged lines apply always; tagged lines only while scripts/season_state.py reads that state from the filing counts in
docs/results_feed.json + the quarter calendar (both are in this job's sparse checkout). The state is re-measured on every
tick, so the whole cadence moves with the season and nobody edits crons by hand. If season_state fails, the IN-season
slots are used — an idle run is cheaper than a missed result. `--list` prints the active slots for the current state.

Usage: python3 scripts/cron_dispatch.py [--dry-run] [--now 2026-09-29T03:42:00Z]
Needs GITHUB_TOKEN (actions: read, contents: write — repository_dispatch) and GITHUB_REPOSITORY.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import urllib.parse
import urllib.request

WINDOW_MIN = 180  # a slot older than this is skipped, not run hours late
GRACE_MIN = 2  # leave a just-passed slot to any external trigger aimed at the same minute
CRON_RE = re.compile(r'^\s*#\s*dispatch-cron(?:\[(in-season|off-season)\])?:\s*"([^"]+)"', re.M)


# ---- minimal 5-field cron matcher (numbers, *, ranges, lists, steps; DOM/DOW OR-ed like POSIX cron) ----
def _field(spec, lo, hi):
    vals = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = map(int, part.split("-"))
        else:
            a = b = int(part)
            if step > 1:
                b = hi
        vals.update(range(a, b + 1, step))
    return vals


class Cron:
    def __init__(self, expr):
        f = expr.split()
        if len(f) != 5:
            raise ValueError(f"bad cron: {expr!r}")
        self.expr = expr
        self.mi, self.h = _field(f[0], 0, 59), _field(f[1], 0, 23)
        self.dom, self.mon = _field(f[2], 1, 31), _field(f[3], 1, 12)
        self.dow = {d % 7 for d in _field(f[4], 0, 7)}
        self.dom_star, self.dow_star = f[2] == "*", f[4] == "*"

    def match(self, t):
        if t.minute not in self.mi or t.hour not in self.h or t.month not in self.mon:
            return False
        dom_ok, dow_ok = t.day in self.dom, (t.isoweekday() % 7) in self.dow
        if self.dom_star or self.dow_star:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def last_slot(self, lo, hi):
        """Latest minute t with lo < t <= hi that matches, else None."""
        t = hi.replace(second=0, microsecond=0)
        while t > lo:
            if self.match(t):
                return t
            t -= dt.timedelta(minutes=1)
        return None


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    req.add_header("Authorization", "Bearer " + os.environ["GITHUB_TOKEN"])
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def recent_runs(repo, since):
    """Every run created since `since`, across all workflows (paginated; the per-page cap is 100)."""
    runs, page = [], 1
    q = urllib.parse.quote(">=" + since.strftime("%Y-%m-%dT%H:%M:%SZ"))
    while page <= 10:
        j = api("/repos/%s/actions/runs?per_page=100&page=%d&created=%s" % (repo, page, q))
        batch = j.get("workflow_runs") or []
        runs += batch
        if len(batch) < 100 or len(runs) >= (j.get("total_count") or 0):
            break
        page += 1
    return runs


def load_schedules(state="in"):
    """{workflow: [Cron]} — untagged slots always; `[in-season]` / `[off-season]` slots only in that state."""
    out = {}
    for f in sorted(glob.glob(".github/workflows/*.yml")):
        crons = [
            c
            for tag, c in CRON_RE.findall(open(f, encoding="utf-8").read())
            if not tag or tag == state + "-season"
        ]
        if crons:
            out[f] = [Cron(c) for c in crons]
    return out


def season(now):
    """('in'|'off', one-line summary) from scripts/season_state.py (runbook §222). If that fails, the dense in-season
    slots are the safe failure — a missed result costs more than an idle run."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import season_state

        st = season_state.evaluate(now)
        return st["state"], st["summary"]
    except Exception as e:
        print(f"::warning::season_state failed ({e}) — using the in-season slots")
        return "in", f"IN (fallback: season_state failed: {e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="pretend time (ISO UTC) for testing")
    ap.add_argument(
        "--list",
        action="store_true",
        help="print the season state and each workflow's active slots; no API calls",
    )
    a = ap.parse_args()
    now = (
        dt.datetime.fromisoformat(a.now.replace("Z", "+00:00"))
        if a.now
        else dt.datetime.now(dt.UTC)
    )
    repo = os.environ.get("GITHUB_REPOSITORY", "dhruvan246/stocks-dashboard")
    state, season_line = season(now)
    print("{} UTC: season {}".format(now.strftime("%Y-%m-%d %H:%M"), season_line))
    sched = load_schedules(state)
    if a.list:
        for f, crons in sched.items():
            print("  %-34s %s" % (os.path.basename(f)[:-4], " | ".join(c.expr for c in crons)))
        return
    lo, hi = now - dt.timedelta(minutes=WINDOW_MIN), now - dt.timedelta(minutes=GRACE_MIN)

    due = {}
    for f, crons in sched.items():
        best = None
        for c in crons:
            s = c.last_slot(lo, hi)
            if s and (best is None or s > best[0]):
                best = (s, c.expr)
        if best:
            due[f] = best
    print(
        "%d workflows carry dispatch-cron lines for this state, %d have a slot in the last %d min"
        % (len(sched), len(due), WINDOW_MIN)
    )
    if not due:
        return

    runs = recent_runs(repo, min(s for s, _ in due.values()) - dt.timedelta(minutes=1))
    sent = fails = 0
    for f, (slot, expr) in sorted(due.items()):
        cutoff = slot - dt.timedelta(minutes=1)
        mine = [
            r
            for r in runs
            if r.get("path") == f
            and dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= cutoff
        ]
        stem = os.path.basename(f)[:-4]
        if mine:
            print(
                "  ok    %-34s slot %s (%s) — already ran (%s, %s)"
                % (
                    stem,
                    slot.strftime("%H:%M"),
                    expr,
                    mine[-1]["event"],
                    mine[-1]["created_at"][11:16],
                )
            )
            continue
        print(
            "  START %-34s slot %s (%s)%s"
            % (stem, slot.strftime("%H:%M"), expr, " [dry-run]" if a.dry_run else "")
        )
        if a.dry_run:
            continue
        try:
            api(
                f"/repos/{repo}/dispatches",
                "POST",
                {
                    "event_type": "tick-" + stem,
                    "client_payload": {
                        "schedule": expr,
                        "slot": slot.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                },
            )
            sent += 1
        except Exception as e:
            fails += 1
            print(f"::warning::dispatch failed for {stem}: {e}")
    print("dispatched %d, failed %d" % (sent, fails))
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
