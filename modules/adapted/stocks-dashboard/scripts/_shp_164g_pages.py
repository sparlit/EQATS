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
"""§164g — page-era (Jun-2006..Mar-2016) re-read of FORMER Nifty 500 members with the §160 rules (user 2026-09-25: "adopt all
three recommendations, do it" — D3: re-read every former member row by row). Runs scripts/_shp_aspx_rowfix.py (§160, DII session)
read-only against a work dir holding the former members' BSE ShareholdingPattern.aspx pages; its §160-marked writer is NOT used:
`export` turns the proposals into a §164 proposal file for scripts/_shp_164_write.py.
Env: DII_ROWFIX_WORK (work dir: aspx_pages/, shpperent/, aspx_codes.json, n500_syms.json = the former members),
DII_ROWFIX_LISTS, DII_ROWFIX_CACHES (as for §158).
Stages: run (classify + seam + verify) ; export <out.json>."""
import json
import os
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
# No browser impersonation, ever (feedback-no-browser-impersonation-to-pass-bse-filter). §160's shpperent cache-miss fallback
# calls curl_cffi impersonate="chrome"; this shim answers it with a PLAIN, honestly identified request (www.bseindia.com only).
import time as _tm
import types as _t
import urllib.error as _ue
import urllib.request as _ur

import bse_headers  # §181: the repo's honest header set (own UA, Accept-Language, Referer) on every *.bseindia.com urllib request

_UA = "stocks-dashboard-data-fetch/1.0 (+personal research; contact via github dhruvan246)"


class _Resp:
    def __init__(self, code, body):
        self.status_code = code
        self.content = body
        self.text = body.decode("utf-8", "ignore")

    def json(self):
        import json as _j

        return _j.loads(self.text)


def _plain_get(url, headers=None, impersonate=None, timeout=60, **k):
    if "api.bseindia.com" in url or "bseindia.com" not in url:
        return _Resp(403, b"")
    for a in range(3):
        try:
            r = _ur.urlopen(
                _ur.Request(url, headers={"User-Agent": _UA, "Referer": "https://www.bseindia.com/"}), timeout=timeout
            )
            body = r.read()
            _tm.sleep(0.8)
            return _Resp(r.status, body)
        except _ue.HTTPError as e:
            if e.code in (403, 404, 406, 410):
                return _Resp(e.code, b"")
        except Exception:
            pass
        _tm.sleep(3 + 3 * a)
    return _Resp(0, b"")


_shim = _t.ModuleType("curl_cffi")
_shim.requests = _t.SimpleNamespace(get=_plain_get)
sys.modules["curl_cffi"] = _shim
sys.modules["curl_cffi.requests"] = _shim.requests
if not os.environ.get("DII_ROWFIX_WORK"):
    sys.exit("set DII_ROWFIX_WORK to the former members' page work dir")
import _shp_aspx_rowfix as A


def seam():
    """§160's seam pass reads <LISTS>/<sym>.json for every dip symbol; 224 former members have no BSE list (classify already runs
    them with no filer map). Give the seam pass the same: an overlay dir = every real list + an empty list for the rest, so
    SymCtx falls back to curated verdicts / name markers / the sibling-table prefix (newmap_for([]) -> {})."""
    ov = os.path.join(os.getcwd(), "lists_overlay")
    os.makedirs(ov, exist_ok=True)
    for s in json.load(open("n500_syms.json")):
        dst = os.path.join(ov, s + ".json")
        src = os.path.join(A.D.LISTS, s + ".json")
        if os.path.lexists(dst):
            continue
        if os.path.exists(src):
            os.symlink(src, dst)
        else:
            json.dump([], open(dst, "w"))
    real = A.D.LISTS
    A.D.LISTS = ov
    try:
        A.seam_pass()
    finally:
        A.D.LISTS = real


def export(out):
    P = json.load(open("proposals_aspx.json"))
    S = (
        {k: v for k, v in json.load(open("proposals_seam.json")).items() if v.get("cell")}
        if os.path.exists("proposals_seam.json")
        else {}
    )
    P.update(S)
    stamp = _tm.strftime("%Y-%m-%d")
    O = {}
    for k, v in sorted(P.items()):
        cur = v["was"]
        new = v["cell"]
        src = "bseaspx:{}".format(v["file"].replace(".html.gz", "")) + (" shpperent" if v.get("shpperent") else "")
        why = (
            "§164g page-era re-read of a former Nifty 500 member ({}; §160 rules — DII = Institutions(Domestic), FII = "
            "Institutions(Foreign) in every format): fii {:.2f} -> {:.2f}, dii {:.2f} -> {:.2f}{}. ".format(
                stamp,
                cur[1],
                new[1],
                cur[2],
                new[2],
                (f", prom {cur[0]:.2f} -> {new[0]:.2f}" if abs(new[0] - cur[0]) > 0.005 else ""),
            )
            + "; ".join(" ".join(str(x) for x in e) for e in v["ev"])[:900]
            + ". Evidence: _shp_164_audit.json"
        )
        O[k] = {
            "was": cur,
            "cell": new,
            "src": src,
            "why": why,
            "file": v["file"],
            "d_fii": v.get("d_fii"),
            "d_dii": v.get("d_dii"),
            "add_ins": v.get("add_ins"),
            "ev": v.get("ev"),
            "shpperent": v.get("shpperent", False),
        }
    json.dump(O, open(out, "w"), indent=0)
    print("export: %d proposals -> %s" % (len(O), out))


if __name__ == "__main__":
    st = sys.argv[1] if len(sys.argv) > 1 else "run"
    if st == "run":
        A.classify()
        seam()
        A.verify()
    elif st == "seam":
        seam()
        A.verify()
    elif st == "export":
        export(os.path.abspath(sys.argv[2]) if os.path.isabs(sys.argv[2]) else sys.argv[2])
