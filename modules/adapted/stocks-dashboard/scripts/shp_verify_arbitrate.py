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
"""PHASE 5 — settle contested cells against the EXCHANGE FILING, never by site majority.

Sites copy each other, so agreement between them is not evidence (SHP_VERIFY_CAMPAIGN rule 6).
The only thing that decides a disputed cell is the document the company actually filed. This walks
the runbook §57 ladder in order and stops at the first rung that yields a parsed answer:

  rung 1  NSE corporate-share-holdings-master for the quarter -> the symbol's row(s) -> XBRL.
          ALL submissions are listed first (trap T5): more than one means a revision exists, and
          the newest submission wins — decided by DATE, never by which value looks nicer.
  rung 2  BSE SHPQNewFormat for the scripcode, gated on a NON-EMPTY XbrlFile (`xbrlurl` is truthy
          even when no file exists — runbook §22f) -> XBRL.

Both rungs parse with the repo's own `parse_shp`, imported from THIS tree (checked out at
origin/main) — never from a working copy, which is how a stale checkout produced a phantom
parser bug earlier in this campaign.

Output verdicts:
  OURS_CONFIRMED   the filing reproduces our stored cell            -> our value stands
  OURS_WRONG       the filing disagrees with us                     -> P6 heal via shp_cell_fix.json
  FILLABLE         we hold nothing and the filing has the value     -> P6 fill
  REVISION         >1 submission exists; newest differs from ours   -> P6 targeted refetch
  NO_FILING        no document on either exchange for that cell
  UNPARSEABLE      a document exists but parse_shp will not anchor it (correct refusal, not a bug)

  python3 -X utf8 scripts/shp_verify_arbitrate.py --quorum p3/quorum_p3.jsonl --out p5/arbitration.jsonl
"""
import argparse
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # parse_shp + fetch_master from THIS tree
import contextlib

import fetch_shareholding as F  # noqa: E402

TOL = 0.06


def load_hist(pin):
    import subprocess

    r = subprocess.run(
        ["git", "show", f"{pin}:scripts/shp_history.json"], capture_output=True, cwd=os.path.dirname(HERE)
    )
    if r.returncode:
        sys.exit(f"cannot read shp_history.json at {pin}")
    return json.loads(r.stdout)


def scripcodes():
    base = "/Users/dhruvan/stocks-dashboard/scripts"
    out = {}
    with contextlib.suppress(Exception):
        out.update(dict(json.load(open(os.path.join(base, "bse_scrips.json")))["by_id"].items()))
    try:
        ov = json.load(open(os.path.join(base, "_shp_scripcode_override.json")))
        out.update({k: v for k, v in ov.items() if not k.startswith("_")})
    except Exception:
        pass
    return out


def bse_quarters(code, cache):
    """BSE's filing list for a scripcode; gate on a non-empty XbrlFile (§22f: xbrlurl lies)."""
    if code in cache:
        return cache[code]
    import urllib.request

    UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124 Safari/537.36"
    )
    url = f"https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode={code}&qtrid=0.00&QryType=0"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "application/json", "Referer": "https://www.bseindia.com/"}
        )
        rows = json.loads(urllib.request.urlopen(req, timeout=45).read()).get("Table", [])
    except Exception:
        rows = []
    MON = {"March": "03-31", "June": "06-30", "September": "09-30", "December": "12-31"}
    out = {}
    for r in rows:
        xf = (r.get("XbrlFile") or "").strip()
        if not xf:
            continue
        q = str(r.get("qtr") or "")
        for m, dd in MON.items():
            if q.startswith(m):
                with contextlib.suppress(Exception):
                    out[f"{q.rsplit(maxsplit=1)[-1]}-{dd}"] = r
    cache[code] = out
    time.sleep(2.0)
    return out


def bse_fetch(xf):
    import urllib.request

    UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124 Safari/537.36"
    )
    req = urllib.request.Request(
        "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + xf,
        headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.bseindia.com/"},
    )
    body = urllib.request.urlopen(req, timeout=60).read()
    time.sleep(2.0)
    if len(body) < 5000:  # BSE blocks with a tiny redirect body, not an error
        raise RuntimeError("blocked (%d bytes)" % len(body))
    return body.decode("utf-8", "ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quorum", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pin", default="93de247c")
    ap.add_argument("--limit", type=int, default=0, help="max cells to arbitrate (0 = all)")
    ap.add_argument(
        "--include-confirmed", action="store_true", help="also re-check cells the sites already confirmed (spot-audit)"
    )
    a = ap.parse_args()

    HIST = load_hist(a.pin)
    CODES = scripcodes()

    want = collections.defaultdict(list)  # quarter -> [rows]
    for line in open(a.quorum, encoding="utf-8"):
        r = json.loads(line)
        d = r.get("decision")
        if d in ("CONTRADICTED", "SITES_DISAGREE") or (a.include_confirmed and d == "CONFIRMED"):
            want[r["qe"]].append(r)
    cells = sum(len(v) for v in want.values())
    print("arbitration queue: %d cells across %d quarters" % (cells, len(want)))

    done, out, bse_cache = 0, [], {}
    jar = None
    for qe in sorted(want, reverse=True):
        rows = want[qe]
        syms = sorted({r["sym"] for r in rows})
        if jar is None:
            import build_fundamentals as B

            jar = B.nse_jar()
        try:
            master = F.fetch_master(jar, qe)
        except Exception as e:
            print(f"  ! NSE master {qe} failed: {e}")
            master = []
        by_sym = collections.defaultdict(list)
        for m in master:
            by_sym[str(m.get("symbol") or "").upper()].append(m)

        for sym in syms:
            if a.limit and done >= a.limit:
                break
            fields = [r for r in rows if r["sym"] == sym]
            HIST.get(sym, {}).get(qe)
            filed, rung, evid, subs = None, "", "", []

            hits = [h for h in by_sym.get(sym.upper(), []) if str(h.get("xbrl") or "").startswith("http")]
            if hits:
                subs = [str(h.get("submissionDate")) for h in hits]
                hits.sort(key=lambda h: str(h.get("submissionDate") or ""))  # newest submission wins
                try:
                    filed = F.parse_shp(F.fetch_xbrl(hits[-1]["xbrl"], jar), qe)
                    rung, evid = "nse", hits[-1]["xbrl"]
                except Exception as e:
                    print(f"     {sym} {qe} nse parse failed: {e}")
            if filed is None and sym in CODES:
                q = bse_quarters(CODES[sym], bse_cache).get(qe)
                if q:
                    try:
                        filed = F.parse_shp(bse_fetch(q["XbrlFile"].strip()), qe)
                        rung = "bse"
                        evid = "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + q["XbrlFile"].strip()
                    except Exception as e:
                        print(f"     {sym} {qe} bse failed: {e}")

            for r in fields:
                f = r["field"]
                rec = {
                    "sym": sym,
                    "qe": qe,
                    "field": f,
                    "ours": r.get("ours"),
                    "sites": r.get("sites"),
                    "rung": rung,
                    "evidence": evid,
                    "submissions": subs,
                }
                if filed is None:
                    rec["verdict"] = "NO_FILING" if not hits else "UNPARSEABLE"
                else:
                    fv = filed.get(f)
                    rec["filed"] = fv
                    if fv is None:
                        rec["verdict"] = "UNPARSEABLE"
                    elif r.get("ours") is None:
                        rec["verdict"] = "FILLABLE"
                    else:
                        band = TOL if f != "nsh" else max(1.0, 0.01 * abs(float(r["ours"])))
                        same = abs(float(fv) - float(r["ours"])) <= band
                        rec["verdict"] = "OURS_CONFIRMED" if same else ("REVISION" if len(subs) > 1 else "OURS_WRONG")
                out.append(rec)
            done += 1
        if a.limit and done >= a.limit:
            break

    with open(a.out, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")

    tally = collections.Counter(r["verdict"] for r in out)
    print("\n%d field-verdicts -> %s" % (len(out), a.out))
    for k, v in tally.most_common():
        print("  %-16s %5d" % (k, v))
    for k in ("OURS_WRONG", "REVISION"):
        bad = [r for r in out if r["verdict"] == k]
        if bad:
            print("\n%s (%d) — these are OUR defects, for P6:" % (k, len(bad)))
            for r in bad[:15]:
                print(
                    "   %-11s %s %-4s ours=%-9s filed=%-9s [%s]"
                    % (r["sym"], r["qe"], r["field"], r["ours"], r.get("filed"), r["rung"])
                )


if __name__ == "__main__":
    main()
