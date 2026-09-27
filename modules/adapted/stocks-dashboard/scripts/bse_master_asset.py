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


#!/usr/bin/env python3
"""BSE scrip-master fallback on the `data` release (DATA_RUNBOOK §150).

api.bseindia.com answered HTTP 403 "Access Denied" (an Akamai block, not the 302 rate-limit stub)
to EVERY client from ~20:00 IST on 2026-09-23 — this Mac and GitHub's runners alike — and the daily
refresh died on its first step six attempts in a row (three scheduled runs + their auto-retries, all
red, no close prices shipped that evening). The scrip master is the ONE source of every market cap
on the site and the join key for BSE-only rows, so it has to survive an outage of its source.

  push SRC   after a LIVE fetch succeeded: gzip SRC and upload it as bse_scrip_master.json.gz
             (+ bse_scrip_master.meta.json: when, rows, source) to the `data` release. The repo is
             9 GB; a ~1.7 MB list up to four times a day does NOT go into git.
  pull DEST  when the live fetch failed: download the last-good list, validate it (gunzips, is a
             list, >= 3000 Active/Equity rows carrying SCRIP_CD/scrip_id/ISIN_NUMBER/Mktcap) and
             write DEST atomically. Prints the meta so the run log says how old the fallback is.
             Exit 1 when no valid copy exists — the caller then fails the run, exactly as before.

Routes follow scripts/fetch_release_bin.py (§146): the public download URL first, then the asset id
from the RELEASE-id listing (the tag listing lags a re-upload by >1 h). `gh` provides auth in CI
(GH_TOKEN); the repo is public, so `pull` works without it too.
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import bse_headers as BH  # §181 BSE headers
import argparse
import datetime
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextlib

import fetch_release_bin as R  # api_json / download_public / download_by_id + REPO / TAG

ASSET = "bse_scrip_master.json.gz"
META = "bse_scrip_master.meta.json"
MIN_ROWS = 3000  # the live list carries ~4,900-5,050 Active/Equity rows
NEED = ("SCRIP_CD", "scrip_id", "ISIN_NUMBER", "Mktcap", "Status", "Segment")
PUBLIC = f"https://github.com/{R.REPO}/releases/download/{R.TAG}/%s"


def log(msg):
    print(msg, flush=True)


def active_rows(rows):
    return [r for r in rows if isinstance(r, dict) and r.get("Status") == "Active" and r.get("Segment") == "Equity"]


def check(rows):
    """None when `rows` is a usable master, else the complaint."""
    if not isinstance(rows, list):
        return "not a JSON list"
    act = active_rows(rows)
    if len(act) < MIN_ROWS:
        return "only %d Active/Equity rows (need >= %d)" % (len(act), MIN_ROWS)
    missing = [k for k in NEED if not any(k in r for r in act[:50])]
    if missing:
        return f"rows lack {missing}"
    return None


def fresh_asset(name):
    """The asset as listed by RELEASE id (the listing that stays fresh after a --clobber), or None."""
    try:
        rel_id = R.api_json(f"repos/{R.REPO}/releases/tags/{R.TAG}")["id"]
        assets = R.api_json("repos/%s/releases/%d/assets?per_page=100" % (R.REPO, rel_id))
        hit = [a for a in assets if a.get("name") == name and a.get("state") == "uploaded"]
        return hit[0] if hit else None
    except Exception as e:
        log(f"  could not list assets by release id: {str(e)[:200]}")
        return None


def push(src, source):
    rows = json.load(open(src, encoding="utf-8"))
    bad = check(rows)
    if bad:
        sys.exit(f"push refused: {src} {bad}")
    act = len(active_rows(rows))
    tmp = tempfile.mkdtemp()
    gz, mp = os.path.join(tmp, ASSET), os.path.join(tmp, META)
    with gzip.open(gz, "wb", compresslevel=6) as fh:
        fh.write(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    meta = {
        "fetched_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": len(rows),
        "active_equity_rows": act,
        "source": source,
    }
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    for f in (gz, mp):
        subprocess.run(["gh", "release", "upload", R.TAG, f, "--clobber", "-R", R.REPO], check=True, timeout=300)
    log(
        "pushed %s (%s bytes, %d Active/Equity rows) + %s %s"
        % (ASSET, format(os.path.getsize(gz), ","), act, META, meta)
    )
    shutil.rmtree(tmp, ignore_errors=True)


def pull(dest, tries):
    dest = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    for attempt in range(1, tries + 1):
        log("attempt %d/%d" % (attempt, tries))
        asset = fresh_asset(ASSET)
        routes = [("public URL", lambda: R.download_public(PUBLIC % ASSET, part))]
        if asset:
            routes.append(("asset id {}".format(asset["id"]), lambda: R.download_by_id(asset["id"], part)))
        for name, fetch in routes:
            try:
                fetch()
                with open(part, "rb") as fh:
                    raw = fh.read()
                if asset and len(raw) != asset["size"]:
                    msg = "{} bytes but the release lists {} (stale copy)".format(
                        format(len(raw), ","), format(asset["size"], ",")
                    )
                    raise ValueError(msg)
                body = gzip.decompress(raw)
                bad = check(json.loads(body))
                if bad:
                    raise ValueError(bad)
            except Exception as e:
                log(f"  {name}: rejected, {(str(e).splitlines() or [repr(e)])[0][:200]}")
                with contextlib.suppress(FileNotFoundError):
                    os.remove(part)
                continue
            with open(part, "wb") as fh:
                fh.write(body)  # the list exactly as it was fetched, no re-serialisation
            os.replace(part, dest)
            meta = {}
            try:
                mp = part + ".meta"
                R.download_public(PUBLIC % META, mp)
                with open(mp, encoding="utf-8") as fh:
                    meta = json.load(fh)
                os.remove(mp)
            except Exception as e:
                log(f"  (meta unavailable: {str(e)[:120]})")
            age = ""
            try:
                dt = datetime.datetime.strptime(meta["fetched_utc"], "%Y-%m-%dT%H:%M:%SZ")
                age = ", %.1f h old" % ((datetime.datetime.utcnow() - dt).total_seconds() / 3600)
            except Exception:
                pass
            log("  %s: OK, %d Active/Equity rows -> %s" % (name, len(active_rows(json.loads(body))), dest))
            log(
                "FALLBACK BSE MASTER in use: fetched {}{}, source: {} — every market cap on the site is as old as this copy".format(
                    meta.get("fetched_utc", "unknown"), age, meta.get("source", "unknown")
                )
            )
            return 0
        if attempt < tries:
            time.sleep(attempt * 15)
    log("FAILED: no route produced a valid %s after %d attempts" % (ASSET, tries))
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push", help="upload SRC (a live /tmp/bse.json) as the fallback asset")
    p.add_argument("src")
    p.add_argument(
        "--source", default="live api.bseindia.com ListofScripData", help="provenance written to the meta asset"
    )
    q = sub.add_parser("pull", help="download the fallback asset to DEST")
    q.add_argument("dest")
    q.add_argument("--tries", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "push":
        push(a.src, a.source)
        return 0
    return pull(a.dest, a.tries)


if __name__ == "__main__":
    sys.exit(main())
