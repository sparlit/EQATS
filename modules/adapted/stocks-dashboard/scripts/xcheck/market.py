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


"""Market-level checks: index levels, FII/DII flows, market cap.

idx_levels   The same index close from independent feeds the site serves:
               Nifty 50   docs/nifty.json (NiftyTrader)        vs docs/index_monthly.json (niftyindices.com archive)
               Nifty 500  docs/nifty500.json (Yahoo ^CRSLDX)    vs index_monthly
               Nifty Bank docs/nifty_bank.json (Yahoo ^NSEBANK) vs index_monthly
             month-end closes over the whole overlap, plus the daily overlap with index_monthly's live top-up and
             docs/indices_hist.json (NSE allIndices / LiveIndicesWatch).
flows_month  docs/fii_dii.json daily net (NiftyTrader + NSE for the latest day) summed per complete month vs
             docs/fii_dii_monthly.json (NiftyTrader's monthly endpoint).
mcap_shares  The dashboard market cap (docs/stock_data.bin meta mcap: BSE ListofScripData Mktcap) vs our own
             shares outstanding (scripts/shares_outstanding.json, the SHP filing) x the latest NSE close (live bin
             meta raw). Current Nifty 500 members."""
import calendar
import os

from . import common as C


def _j(name):
    return C.jload(os.path.join(C.DOCS, name))


class IdxLevels(C.Check):
    id = "idx_levels"
    title = "Index closes: NiftyTrader / Yahoo feeds vs niftyindices archive vs NSE daily"
    domain = "Indices"
    reader_a = "nifty.json (NiftyTrader), nifty500.json / nifty_bank.json (Yahoo)"
    reader_b = (
        "index_monthly.json (niftyindices archive + daily), indices_hist.json (NSE allIndices)"
    )
    scope = "Nifty 50 2002+, Nifty 500 2012+, Nifty Bank 2012+: every month-end and every shared daily close"
    tolerance = "within 0.1 %"

    def run(self):
        im = _j("index_monthly.json")
        ih = _j("indices_hist.json").get("daily") or {}
        mon = {e["key"]: e.get("closes") or {} for e in im.get("indices") or []}
        imd = im.get("daily") or {}
        feeds = [
            ("NIFTY 50", "nifty.json"),
            ("NIFTY 500", "nifty500.json"),
            ("NIFTY BANK", "nifty_bank.json"),
        ]
        for key, fn in feeds:
            try:
                px = _j(fn).get("px") or {}
            except OSError:
                self.note(f"{fn} missing")
                continue
            last = {}
            for d, v in px.items():
                if v:
                    last[d[:7]] = max(last.get(d[:7], ("", 0)), (d, v))
            asof = im.get("asof") or ""
            for ym, (d, v) in sorted(last.items()):
                y, m = int(ym[:4]), int(ym[5:7])
                if (
                    d[:10] < "%s-%02d-%02d" % (y, m, calendar.monthrange(y, m)[1] - 6)
                    or ym >= asof[:7]
                ):
                    continue  # partial month
                row = (mon.get(key) or {}).get(str(y))
                b = row[m - 1] if row and len(row) >= m else None
                if not b:
                    continue
                self._cmp(key, "month-end " + ym, d, v, b, "index_monthly archive")
            for d, v in px.items():
                for src, tab in (("index_monthly daily", imd), ("indices_hist daily", ih)):
                    b = (tab.get(d) or {}).get(key)
                    if b and v:
                        self._cmp(key, "daily", d, v, b, src)

    def _cmp(self, key, what, d, a, b, src):
        self.compared += 1
        if abs(a / b - 1) <= 0.001:
            self.agree += 1
            return
        self.add(
            f"{key}|{what.split()[0]}|{d}|{src}",
            index=key,
            what=what,
            date=d,
            a=a,
            b=b,
            b_src=src,
            ratio=round(a / b, 5),
            weight=round(abs(a / b - 1) * 100, 3),
        )


class FlowsMonth(C.Check):
    id = "flows_month"
    title = "FII/DII cash flows: daily rows summed per month vs the monthly series"
    domain = "Flows"
    reader_a = "fii_dii.json daily net (NiftyTrader; NSE for the latest day)"
    reader_b = "fii_dii_monthly.json (NiftyTrader monthly endpoint)"
    scope = "complete months covered by the daily file"
    tolerance = "within 1 % or Rs 50 cr"

    def run(self):
        dl = _j("fii_dii.json").get("rows") or []
        ml = {r["ym"]: r for r in _j("fii_dii_monthly.json").get("rows") or []}
        by = {}
        for r in dl:
            by.setdefault(r["date"][:7], []).append(r)
        months = sorted(by)
        for ym in months[1:-1]:  # first and current month may be partial
            m = ml.get(ym)
            if not m:
                continue
            for fld in ("fiiNet", "diiNet"):
                a = round(sum((r.get(fld) or 0) for r in by[ym]), 2)
                b = m.get(fld)
                if b is None:
                    continue
                self.compared += 1
                if abs(a - b) <= max(50.0, 0.01 * abs(b)):
                    self.agree += 1
                    continue
                self.add(
                    f"{ym}|{fld}",
                    month=ym,
                    field=fld,
                    a=a,
                    b=b,
                    days=len(by[ym]),
                    weight=round(abs(a - b), 1),
                )


class McapShares(C.Check):
    id = "mcap_shares"
    title = "Market cap: BSE figure on the dashboard vs our shares x NSE close"
    domain = "Market cap & shares"
    reader_a = "stock_data.bin meta mcap (BSE ListofScripData)"
    reader_b = "shares_outstanding.json (SHP filing) x latest NSE close (live bin)"
    scope = "current Nifty 500 members"
    tolerance = "within 3 % (share count as of the last SHP filing)"

    def run(self):
        start, end, ymeta, _ = C.yahoo_bin()
        so = C.jload(os.path.join(C.HERE, "shares_outstanding.json"))
        cur = C.n500()[-1][1]
        meta = C.late_value(
            C.sf_path(), "meta"
        )  # the live bin's meta sits after 580 MB of price arrays
        for t, m in ymeta.items():
            sym = (m or {}).get("symbol")
            if not t.endswith(".NS") or sym not in cur:
                continue
            mc = m.get("mcap")
            sh = (so.get(sym) or [None])[0]
            px = (meta.get(sym) or {}).get("raw")
            if not mc or not sh or not px:
                continue
            b = sh * px / 1e7
            self.compared += 1
            if abs(mc / b - 1) <= 0.03:
                self.agree += 1
                continue
            self.add(
                sym,
                sym=sym,
                a=mc,
                b=round(b, 2),
                shares=sh,
                shares_asof=(so.get(sym) or [None, None])[1],
                close=px,
                ratio=round(mc / b, 4),
                weight=round(abs(mc - b), 1),
            )
