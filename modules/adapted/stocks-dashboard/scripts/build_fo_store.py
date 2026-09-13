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
"""Build docs/fo/ store from the raw bhavcopy cache + spot files.

Inputs:
  ~/stocks-wt/fo_raw_cache/YYYY/MMDD.json.gz   (fetch_fo_bhavcopy.py)
  scripts/fo_spot_nse.json                     (fetch_fo_spot_nse.py, official NSE)
  scripts/fo_spot.json                         (fetch_fo_spot.py, Yahoo cross-check/fill)

Outputs:
  docs/fo/{SYM}_{YYYY}.bin.gz  per index-year slice (gzipped) (see layout below)
  docs/fo/manifest.json      {indices:{SYM:{years, first, last}}, updated}

Slice layout (little-endian):
  "FOB1" | uint32 headerLen | header JSON (utf8) | Int32Array body
  header: {sym, year, dates:[iso...], spot:[paise close or 0], spotO/spotH/spotL:[paise or 0],
           days:[[ [expIso, futArr|0, nStrikes], ...] per day]}
  body: for each day, for each expiry, nStrikes rows of 13 int32:
        k, ceH, ceL, ceC, ceS, ceV, ceOI, peH, peL, peC, peS, peV, peOI
        (prices in paise; missing side = -1 in the four price fields)
  futArr: [h,l,c,s,v,oi] near futures for that expiry that day (paise), or 0 if none.

Spot close precedence: NSE ind_close_all OHLC > bhavcopy UndrlygPric > Yahoo close.
Spot O/H/L come only from NSE ind_close_all (0 = unavailable that day).
Trim: strikes within ±12% of spot (always) or traded within ±25%; expiries <= 45d out (weekly/next-weekly/monthly all fit; quarterlies dropped).
"""
import datetime as dt
import glob
import gzip
import json
import os
import struct
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.environ.get("FO_CACHE", os.path.expanduser("~/stocks-wt/fo_raw_cache"))
OUTDIR = os.path.join(ROOT, "docs", "fo")
INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]


def load_spot():
    nse = {}
    p = os.path.join(HERE, "fo_spot_nse.json")
    if os.path.exists(p):
        nse = json.load(open(p))
    yah = {}
    p = os.path.join(HERE, "fo_spot.json")
    if os.path.exists(p):
        yah = json.load(open(p))
    return nse, yah


def paise(x):
    return round(x * 100) if x is not None else -1


def read_slice(fp):
    """Parse an existing .bin back into per-day dicts (inverse of the writer)."""
    import struct as st

    blob = open(fp, "rb").read()
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    assert blob[:4] == b"FOB1"
    hlen = st.unpack("<I", blob[4:8])[0]
    hdr = json.loads(blob[8 : 8 + hlen].decode())
    body = memoryview(blob[8 + hlen :])
    out = {}
    pos = 0
    for di, date in enumerate(hdr["dates"]):
        day_hdr = hdr["days"][di]
        nints = sum(e[2] for e in day_hdr) * 13
        vals = st.unpack("<%di" % nints, body[pos * 4 : (pos + nints) * 4])
        out[date] = {
            "spot": hdr["spot"][di],
            "spotO": (hdr.get("spotO") or [0] * len(hdr["dates"]))[di],
            "spotH": (hdr.get("spotH") or [0] * len(hdr["dates"]))[di],
            "spotL": (hdr.get("spotL") or [0] * len(hdr["dates"]))[di],
            "days": day_hdr,
            "body": list(vals),
        }
        pos += nints
    return out


def main():
    args = [a for a in sys.argv[1:] if a != "--append"]
    append = "--append" in sys.argv
    only_years = {int(y) for y in args} if args else None
    nse_spot, yah_spot = load_spot()
    files = sorted(glob.glob(os.path.join(CACHE, "*", "*.json.gz")))
    if not files:
        sys.exit("no cache files")
    # gather per (sym, year)
    slices = defaultdict(
        lambda: {"dates": [], "spot": [], "spotO": [], "spotH": [], "spotL": [], "days": [], "body": []}
    )
    n_days = 0
    for fp in files:
        year = int(os.path.basename(os.path.dirname(fp)))
        if only_years and year not in only_years:
            continue
        d = json.load(gzip.open(fp, "rt"))
        date = d["date"]
        rows = d["rows"]
        n_days += 1
        by_sym = defaultdict(list)
        for r in rows:
            by_sym[r["sym"]].append(r)
        for sym in INDICES:
            rs = by_sym.get(sym)
            if not rs:
                continue
            # spot close: NSE official OHLC > UndrlygPric > Yahoo; O/H/L NSE-only
            nse_row = nse_spot.get(sym, {}).get(date)
            if isinstance(nse_row, (int, float)):  # legacy close-only format
                nse_row = [0, 0, 0, nse_row]
            spot = nse_row[3] if nse_row else None
            if spot is None:
                spot = next((r["u"] for r in rs if r.get("u")), None)
            if spot is None:
                spot = yah_spot.get(sym, {}).get(date)
            so, sh, sl_ = (nse_row[0], nse_row[1], nse_row[2]) if nse_row else (0, 0, 0)
            dmax = (dt.date.fromisoformat(date) + dt.timedelta(days=45)).isoformat()
            exps = defaultdict(lambda: {"fut": 0, "ce": {}, "pe": {}})
            for r in rs:
                if r["exp"] < date or r["exp"] > dmax:
                    continue
                e = exps[r["exp"]]
                if r["ins"] == "FUT":
                    e["fut"] = [paise(r["h"]), paise(r["l"]), paise(r["c"]), paise(r["s"]), r["v"], r["oi"]]
                elif r["t"] in ("CE", "PE"):
                    e[r["t"].lower()][r["k"]] = r
            day_hdr = []
            day_body = []
            for exp in sorted(exps):
                e = exps[exp]
                ks = sorted(set(e["ce"]) | set(e["pe"]))
                kept = []
                for k in ks:
                    ce, pe = e["ce"].get(k), e["pe"].get(k)
                    traded = (ce and ce["v"]) or (pe and pe["v"])
                    dist = abs(k - spot) / spot if spot else 0
                    # keep the practical band: ±12% of spot always; traded strikes to ±25%.
                    # beyond that = dead wings with stale closes (unusable for fills anyway)
                    if spot is not None and not (dist <= 0.12 or (traded and dist <= 0.25)):
                        continue
                    if spot is None and not (traded or (ce and ce["oi"]) or (pe and pe["oi"])):
                        continue
                    row = [round(k * 100)]
                    for side in (ce, pe):
                        if side:
                            row += [
                                paise(side["h"]),
                                paise(side["l"]),
                                paise(side["c"]),
                                paise(side["s"]),
                                side["v"],
                                side["oi"],
                            ]
                        else:
                            row += [-1, -1, -1, -1, 0, 0]
                    kept.append(row)
                if not kept and e["fut"] == 0:
                    continue
                day_hdr.append([exp, e["fut"], len(kept)])
                for row in kept:
                    day_body.extend(row)
            sl = slices[(sym, year)]
            sl["dates"].append(date)
            sl["spot"].append(paise(spot) if spot is not None else 0)
            sl["spotO"].append(paise(so) if so else 0)
            sl["spotH"].append(paise(sh) if sh else 0)
            sl["spotL"].append(paise(sl_) if sl_ else 0)
            sl["days"].append(day_hdr)
            sl["body"].extend(day_body)
    if append:
        # merge existing slice days under the fresh cache days (cache wins)
        for sym, year in list(slices.keys()):
            fp = os.path.join(OUTDIR, f"{sym}_{year}.bin.gz")
            if not os.path.exists(fp):
                continue
            existing = read_slice(fp)
            sl = slices[(sym, year)]
            have = set(sl["dates"])
            nd = {"dates": [], "spot": [], "spotO": [], "spotH": [], "spotL": [], "days": [], "body": []}
            # index fresh day bodies
            fresh_off = []
            off = 0
            for di in range(len(sl["dates"])):
                span = sum(e[2] for e in sl["days"][di]) * 13
                fresh_off.append((off, span))
                off += span
            allDays = sorted(set(list(existing.keys()) + sl["dates"]))
            for date in allDays:
                if date in have:
                    di = sl["dates"].index(date)
                    o, span = fresh_off[di]
                    nd["dates"].append(date)
                    nd["spot"].append(sl["spot"][di])
                    nd["spotO"].append(sl["spotO"][di])
                    nd["spotH"].append(sl["spotH"][di])
                    nd["spotL"].append(sl["spotL"][di])
                    nd["days"].append(sl["days"][di])
                    nd["body"].extend(sl["body"][o : o + span])
                else:
                    row = existing[date]
                    nd["dates"].append(date)
                    nd["spot"].append(row["spot"])
                    nd["spotO"].append(row["spotO"])
                    nd["spotH"].append(row["spotH"])
                    nd["spotL"].append(row["spotL"])
                    nd["days"].append(row["days"])
                    nd["body"].extend(row["body"])
            slices[(sym, year)] = nd
    os.makedirs(OUTDIR, exist_ok=True)
    man_p = os.path.join(OUTDIR, "manifest.json")
    manifest = json.load(open(man_p)) if os.path.exists(man_p) else {"indices": {}}
    total = 0
    for (sym, year), sl in sorted(slices.items()):
        hdr = json.dumps(
            {
                "sym": sym,
                "year": year,
                "dates": sl["dates"],
                "spot": sl["spot"],
                "spotO": sl["spotO"],
                "spotH": sl["spotH"],
                "spotL": sl["spotL"],
                "days": sl["days"],
            },
            separators=(",", ":"),
        ).encode()
        body = struct.pack("<%di" % len(sl["body"]), *sl["body"])
        blob = b"FOB1" + struct.pack("<I", len(hdr)) + hdr + body
        # gzip at rest: GitHub Pages does NOT compress .bin on the wire; browsers
        # decompress .bin.gz natively via DecompressionStream (fo-engine.js).
        # mtime=0 keeps output deterministic — unchanged years stay byte-identical
        # across rebuilds so CI doesn't churn git history re-committing them.
        blob = gzip.compress(blob, 9, mtime=0)
        fp = os.path.join(OUTDIR, f"{sym}_{year}.bin.gz")
        with open(fp, "wb") as f:
            f.write(blob)
        total += len(blob)
        m = manifest["indices"].setdefault(sym, {"years": [], "first": None, "last": None})
        if year not in m["years"]:
            m["years"].append(year)
            m["years"].sort()
        firsts = [sl["dates"][0]] + ([m["first"]] if m["first"] else [])
        lasts = [sl["dates"][-1]] + ([m["last"]] if m["last"] else [])
        m["first"], m["last"] = min(firsts), max(lasts)
        print(f"{sym}_{year}.bin.gz  days={len(sl['dates'])}  {len(blob) // 1024}KB")
    manifest["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M IST")
    json.dump(manifest, open(man_p, "w"), indent=1)
    print(f"TOTAL {total / 1e6:.1f}MB across {len(slices)} slices, {n_days} cache days")


if __name__ == "__main__":
    main()
