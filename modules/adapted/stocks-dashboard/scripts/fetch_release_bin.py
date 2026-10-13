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
"""Download the `data` release's sf_stock_data.bin, robust to a STALE tag listing (DATA_RUNBOOK §146).

Why not `gh release download data`: gh resolves the asset through GET /releases/tags/data, and
that listing can lag a re-upload. Measured 2026-09-23: the asset was re-uploaded 08:45:46Z (new
id 583362351), but the tag endpoint kept listing the deleted id 582103099 for >70 min, so gh got
"HTTP 404 ... releases/assets/582103099" and refresh-market-mood failed. Over the same window
GET /releases/{release_id}/assets and the public browser_download_url both served the new file.

Routes, tried in order on every attempt:
  1. the public URL (curl -L), the same URL every other script here downloads from
  2. the fresh asset id from GET /releases/{release_id}/assets, fetched as application/octet-stream
Every download is validated before it is accepted: >= 50 MB, gzip magic, gunzips + parses as JSON,
has an 'end' field shaped YYYY-MM-DD, and (when the by-id listing was readable) its size equals the
size that listing reports, which catches a stale copy served from either route. A rejected file is
deleted, and DEST is only written by an atomic rename of a validated file, so a failed run never
leaves a broken bin behind.

Usage:  python3 scripts/fetch_release_bin.py DEST [--tries N] [--url URL]
Prints  "data end = YYYY-MM-DD" on success. Exits 1 when no route produced a valid file.
Needs curl. Uses `gh api` for the listing (auth from GH_TOKEN in CI); without gh it falls back to
unauthenticated urllib (the repo is public).
"""
import argparse
import contextlib
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

REPO = "dhruvan246/stocks-dashboard"
TAG = "data"
ASSET = "sf_stock_data.bin"
PUBLIC_URL = f"https://github.com/{REPO}/releases/download/{TAG}/{ASSET}"
MIN_BYTES = 50_000_000  # the live asset is ~200 MB; anything this small is an error page
DL_TIMEOUT = 900  # seconds per download


def log(msg):
    print(msg, flush=True)


def api_json(path):
    """GET https://api.github.com/<path> as JSON: gh first (authenticated), then plain urllib."""
    if shutil.which("gh"):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return json.loads(r.stdout)
        log(f"  gh api {path} failed: {(r.stderr or r.stdout).strip()[:200]}")
    req = urllib.request.Request(
        "https://api.github.com/" + path,
        headers={"User-Agent": "fetch_release_bin", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fresh_asset():
    """The asset as listed by RELEASE ID (the listing that stayed fresh), or None if unreadable.
    Only the release's `id` is taken from the tag endpoint; its `assets` array is the part that lags."""
    try:
        rel_id = api_json(f"repos/{REPO}/releases/tags/{TAG}")["id"]
        assets = api_json(f"repos/{REPO}/releases/{rel_id}/assets?per_page=100")
        hit = [a for a in assets if a.get("name") == ASSET and a.get("state") == "uploaded"]
        if not hit:
            log(f"  release {rel_id} lists no uploaded {ASSET} right now")
            return None
        a = hit[0]
        log(
            f"  release {rel_id} lists {ASSET}: asset id {a['id']}, {a['size']:,} bytes, updated {a['updated_at']}"
        )
        return a
    except (
        Exception
    ) as e:  # listing is a cross-check + second route; the public URL still works without it
        log(f"  could not list assets by release id: {str(e)[:200]}")
        return None


def download_public(url, dest):
    subprocess.run(
        [
            "curl",
            "-fsSL",
            "--connect-timeout",
            "20",
            "--max-time",
            str(DL_TIMEOUT),
            "-o",
            dest,
            url,
        ],
        check=True,
        timeout=DL_TIMEOUT + 60,
    )


def download_by_id(asset_id, dest):
    path = f"repos/{REPO}/releases/assets/{asset_id}"
    if shutil.which("gh"):  # gh follows the redirect to the storage host and drops its token there
        with open(dest, "wb") as fh:
            subprocess.run(
                ["gh", "api", "-H", "Accept: application/octet-stream", path],
                stdout=fh,
                check=True,
                timeout=DL_TIMEOUT,
            )
    else:
        subprocess.run(
            [
                "curl",
                "-fsSL",
                "--connect-timeout",
                "20",
                "--max-time",
                str(DL_TIMEOUT),
                "-H",
                "Accept: application/octet-stream",
                "-o",
                dest,
                "https://api.github.com/" + path,
            ],
            check=True,
            timeout=DL_TIMEOUT + 60,
        )


def validate(path, want_size):
    """(None, end) when the file is a good bin, else (complaint, None)."""
    if not os.path.exists(path):
        return "no file was written", None
    size = os.path.getsize(path)
    if size < MIN_BYTES:
        with open(path, "rb") as fh:
            head = fh.read(200).decode("utf-8", "replace")
        return (
            f"only {size:,} bytes (expected >{MIN_BYTES // 1_000_000} MB), body starts: {' '.join(head.split()) or '(empty)'}",
            None,
        )
    if want_size is not None and size != want_size:
        return f"{size:,} bytes but the release lists {want_size:,} (stale or truncated copy)", None
    with open(path, "rb") as fh:
        magic = fh.read(2)
    if magic != b"\x1f\x8b":
        return f"{size:,} bytes but not gzip (magic 0x{magic.hex()})", None
    try:
        with open(path, "rb") as fh:
            end = json.loads(gzip.decompress(fh.read())).get("end")
    except Exception as e:
        return f"does not gunzip + parse: {str(e)[:200]}", None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(end or "")):
        return f"parsed, but its 'end' field is {end!r}", None
    return None, end


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dest", help="where to write the validated bin")
    ap.add_argument(
        "--tries",
        type=int,
        default=4,
        help="attempt rounds (default 4; sleeps 15s, 30s, 45s between)",
    )
    ap.add_argument(
        "--url", default=PUBLIC_URL, help="public download URL (override only to test the fallback)"
    )
    args = ap.parse_args()

    dest = os.path.abspath(args.dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    for attempt in range(1, args.tries + 1):
        log(f"attempt {attempt}/{args.tries}")
        asset = fresh_asset()
        want = asset["size"] if asset else None
        routes = [("public URL", lambda: download_public(args.url, part))]
        if asset:
            routes.append((f"asset id {asset['id']}", lambda: download_by_id(asset["id"], part)))
        for name, fetch in routes:
            try:
                fetch()
                complaint, end = validate(part, want)
            except (
                subprocess.CalledProcessError
            ) as e:  # curl/gh already printed the reason to stderr
                complaint, end = f"download failed: {e.cmd[0]} exited {e.returncode}", None
            except Exception as e:
                complaint, end = (
                    f"download failed: {(str(e).splitlines() or [repr(e)])[0][:200]}",
                    None,
                )
            if complaint is None:
                os.replace(part, dest)
                log(f"  {name}: OK, {os.path.getsize(dest):,} bytes -> {dest}")
                log(f"data end = {end}")
                return 0
            log(f"  {name}: rejected, {complaint}")
            with contextlib.suppress(FileNotFoundError):
                os.remove(part)
        if attempt < args.tries:
            time.sleep(attempt * 15)
    log(f"FAILED: no route produced a valid {ASSET} after {args.tries} attempts")
    return 1


if __name__ == "__main__":
    sys.exit(main())
