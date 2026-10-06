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


"""px_nse_yahoo — the two price stores the site serves, read against each other.

Reader A: the backtest/stock-page bin (sf_stock_data.bin, release asset): NSE bhavcopy closes, adjusted by OUR
corporate-action ledgers (splits/bonus corp_actions.json, demergers demerger_adj/demerger_catchup, rights rights_adj).
Reader B: the dashboard bin (docs/stock_data.bin): Yahoo chart-API closes for <SYM>.NS — split/bonus-adjusted by
Yahoo, NOT for demergers or rights. Rows fetch_all filled FROM the bhavcopy (meta src == "nse-bhavcopy") are
not an independent reading and are skipped.

SINCE §214a F1 (2026-09-28) the dashboard serves the STORE for every ever-member (meta srcFrom "yahoo-replaced"), so for
those the dashboard bin is no second reading. Their reader B is Yahoo itself, fetched directly and DAILY for the whole
span (xcheck/yahoo_px.py) — independent of the refresh pipeline, and daily so a disagreement's edges are one session
apart. Each finding carries `served`: "store" (the dashboard serves A) or "yahoo" (it serves B: the members kept by
scripts/dash_px_keep_yahoo.json, or a run where the seam gate kept Yahoo). Where the dashboard serves the store, a
disagreement whose edge shows YAHOO's close jumping while NSE's is continuous (wrong B), or a single session where Yahoo
repeated the previous close while NSE moved, is Yahoo's own error and not served: EXPLAINED. A wrong-A (the store jumps
where Yahoo is continuous: a missing/misapplied corporate action) stays open — the store is served on the dashboard, the
stock page and every backtest.

Both files are served, so every disagreement is a defect in one of them (or a by-design adjustment difference).
The ratio r = A/B is compared per session (2020+, both daily) and per ISO week before that (Yahoo is weekly
2002-2019: its weekly close vs A's last session of that week). Runs of consecutive disagreeing points become one
finding, classified by shape:
  step    — r is flat inside the run and returns to 1 at a date E: an adjustment only one side applied at E.
            Explained (by design) when OUR ledger holds a demerger or rights event at E (Yahoo never adjusts those).
            Open when the event is a split/bonus (both should adjust) or neither ledger names E.
  spike   — a single disagreeing point: a bad print in one source.
  drift   — r wanders inside the run: not an adjustment; open.
  to-end  — the run reaches the latest session: a live disagreement (wrong series / pending adjustment); open."""
import bisect
import datetime
import math
import statistics

from . import common as C
from . import yahoo_px

TOL = 0.01  # |A/B - 1| > 1 % disagrees (2-dp rounding of an adjusted 7.23 is 0.14 %)
SESSION_MIN = 25  # >= this many members off on one date = one session-wide finding
LEVEL_TOL = 0.03  # a disagreeing level continues while A/B stays within 3 % of its recent median


def _events():
    """{sym: {ymd: [(kind, factor)]}} from every ledger that moves A's adjustment."""
    ev = {}

    def put(
        s, d, k, f
    ):  # the same event in two ledgers (corp_actions + corp_actions_hist, demerger_adj + catchup) once
        lst = ev.setdefault(s, {}).setdefault(int(d), [])
        if not any(
            k == k2 and (f == f2 or (f and f2 and abs(float(f) / float(f2) - 1) < 1e-3))
            for k2, f2 in lst
        ):
            lst.append((k, f))

    ca = C.jload(C.os.path.join(C.HERE, "corp_actions.json"))
    for s, rows in (ca.get("factors") or {}).items():
        for d, f in rows:
            put(s, d, "split/bonus", f)
    try:
        h = C.jload(C.os.path.join(C.HERE, "corp_actions_hist.json"))
        for s, rows in (h.get("factors") or {}).items():
            for d, f in rows:
                put(s, d, "split/bonus", f)
    except OSError:
        pass
    for r in C.jload(C.os.path.join(C.HERE, "demerger_adj.json")):
        put(r[0], r[1], "demerger", r[2])
    for e in C.jload(C.os.path.join(C.HERE, "demerger_catchup.json")).get("events") or []:
        if e.get("sym") and e.get("ex"):
            put(e["sym"], e["ex"], "demerger", e.get("factor"))
    for r in C.jload(C.os.path.join(C.HERE, "rights_adj.json")).get("rows") or []:
        put(r[0], r[1], "rights", r[2])
    return ev


def _near(evs, lo, hi):
    """ledger events with lo < ymd <= hi (the step falls between the last disagreeing and the first agreeing point)."""
    return [(d, k, f) for d, lst in sorted(evs.items()) if lo < d <= hi for k, f in lst]


class PxNseYahoo(C.Check):
    id = "px_nse_yahoo"
    title = "Closing prices: NSE bhavcopy store vs Yahoo"
    domain = "Prices & corporate actions"
    reader_a = (
        "sf_stock_data.bin (NSE bhavcopy, our CA ledgers) — the stock page, backtests and, since §214a F1, the "
        "dashboard for every Nifty 500 member"
    )
    reader_b = (
        "Yahoo .NS closes (Yahoo's split adjustment): fetched directly, daily, where the dashboard serves the store; "
        "the dashboard bin where it still serves Yahoo"
    )
    scope = (
        "Nifty 500 members on each date, 2002-01 → latest (daily; weekly before 2020 for members whose dashboard "
        "series is still Yahoo's)"
    )
    tolerance = "|A/B − 1| ≤ 1 %"

    def run(self):
        start, last_d, ymeta, yser = C.yahoo_bin()
        ev = _events()
        ever = C.ever_members()
        want, repl, skipped_bhav = {}, {}, 0
        for t, m in ymeta.items():
            sym = (m or {}).get("symbol") or t.rsplit(".", 1)[0]
            if not (t.endswith(".NS") and sym in ever):
                continue
            m = m or {}
            if m.get("src") == "nse-bhavcopy":
                if m.get("srcFrom") == "yahoo-replaced":
                    repl[t] = sym  # dashboard serves the store: read Yahoo directly
                else:
                    skipped_bhav += 1  # Yahoo had no series for it at all
                continue
            want[t] = sym  # dashboard still serves Yahoo: read its bin
        sf = C.sf_closes(set(want.values()) | set(repl.values()))
        ydaily, failed = yahoo_px.fetch(sorted(repl))
        unmapped = 0
        self._served = "yahoo"
        for t, ser in yser:
            sym = want.get(t)
            if not sym:
                continue
            a = sf.get(sym)
            if not a:
                unmapped += 1
                continue
            self._one(sym, self._points(sym, a, ser, start), ev.get(sym, {}), last_d)
        self._served = "store"
        for t, sym in sorted(repl.items()):
            a, y = sf.get(sym), ydaily.get(t)
            if not a:
                unmapped += 1
                continue
            if y:
                self._one(sym, self._points_daily(sym, a, y), ev.get(sym, {}), last_d)
        self.note(
            "%d members whose dashboard serves the NSE store (§214a F1) read against Yahoo fetched directly, daily "
            "(%d of them Yahoo gave nothing: %s); %d members read against the dashboard's Yahoo series; %d Yahoo-less "
            "series skipped; %d member tickers with no series in the NSE bin"
            % (
                len(repl),
                len(failed),
                ", ".join("{} ({})".format(*kv) for kv in sorted(failed.items())[:12]) or "-",
                len(want),
                skipped_bhav,
                unmapped,
            )
        )
        if repl and len(failed) > 0.2 * len(repl):
            raise RuntimeError(
                "Yahoo gave nothing for %d of %d store-served members — the second reader is missing"
                % (len(failed), len(repl))
            )
        # A session where one file is off for MANY members at once is one defect (Yahoo repeated the previous close for
        # 373 members on 18-Mar-2025), not hundreds: fold same-date spikes into a single session finding.
        by = {}
        for f in self.findings:
            if f["shape"] == "spike" and not f.get("explained"):
                by.setdefault(f["date_from"], []).append(f)
        fold = {d for d, lst in by.items() if len(lst) >= SESSION_MIN}
        if fold:
            keep = [
                f
                for f in self.findings
                if not (f["shape"] == "spike" and f["date_from"] in fold and not f.get("explained"))
            ]
            for d in sorted(fold):
                lst = by[d]
                sides = {}
                for f in lst:
                    sides[f["wrong"]] = sides.get(f["wrong"], 0) + 1
                stale = sum(1 for f in lst if f.get("left") and f["left"]["b_jump"] == 1.0)
                keep.append(
                    {
                        "key": "*|{}".format(d.replace("-", "")),
                        "sym": "*",
                        "shape": "session",
                        "date_from": d,
                        "date_to": d,
                        "n": len(lst),
                        "wrong": max(sides, key=sides.get),
                        "sides": sides,
                        "b_unchanged": stale,
                        "examples": [[f["sym"], f["ratio"]] for f in lst[:12]],
                        "weight": round(sum(f["weight"] for f in lst), 3),
                    }
                )
            self.findings = keep

    @staticmethod
    def _points_daily(sym, a, y):
        """Store vs Yahoo's own daily closes, every shared session 2002+ while a member. Sessions only one side has are
        not compared here (a store gap is another check's business; Yahoo's phantom holiday bars are not ours)."""
        spans = C.member_spans(sym)

        def inm(d):
            return any(f <= d and (to is None or d < to) for f, to in spans)

        amap = dict(zip(*a, strict=False))
        pts = []
        for d, b in zip(*y, strict=False):
            if d < 20020101 or not inm(d):
                continue
            x = amap.get(d)
            if x and b:
                pts.append((d, x, b))
        return pts

    @staticmethod
    def _points(sym, a, ser, start):
        spans = C.member_spans(sym)

        def inm(d):
            return any(f <= d and (to is None or d < to) for f, to in spans)

        ad, ac = a
        pts = []
        for dd, p in zip(ser["d"], ser["p"], strict=False):
            if p <= 0:
                continue
            dt = start + datetime.timedelta(days=dd)
            b = p / 100.0
            d = C.ymd(dt)
            if d >= 20200101:
                if not inm(d):
                    continue
                i = bisect.bisect_left(ad, d)
                if i >= len(ad) or ad[i] != d or not ac[i]:
                    continue  # a Yahoo-only session: another check
                pts.append((d, ac[i], b))
            else:
                mon = dt + datetime.timedelta(days=1)
                mon = mon - datetime.timedelta(days=mon.weekday())
                lo, hi = C.ymd(mon), C.ymd(mon + datetime.timedelta(days=6))
                if lo < 20020101 or hi >= 20200101:
                    continue  # the last weekly bar is cut at Yahoo's daily start (partial)
                j = bisect.bisect_right(ad, hi) - 1
                while j >= 0 and ad[j] >= lo and C.day(ad[j]).weekday() >= 5:
                    j -= 1  # Yahoo's week has no weekend
                if j < 0 or ad[j] < lo or not ac[j] or not inm(ad[j]):
                    continue  # special session (Budget Sat)
                pts.append((ad[j], ac[j], b))
        return pts

    def _one(self, sym, pts, evs, last_d):
        """pts = [(ymd, A close, B close)]. Disagreeing runs are cut wherever A/B changes level (a run can straddle two
        adjustments: KANSAINER x20 then x10); each level is one finding. At each edge of a level the two points either
        side are compared WITHIN each file: a correctly adjusted series is continuous across a split, so the file whose
        own close jumps by the level change is the one that failed to adjust there (or adjusted where nothing happened)."""
        self.compared += len(pts)
        r = [a / b for _, a, b in pts]
        bad = [abs(x - 1) > TOL for x in r]
        self.agree += bad.count(False)
        # 1-2 "agreeing" points inside a disagreeing level (a stale Yahoo print that happens to sit near ours:
        # HINDUNILVR 18-Mar-2025) do not end the level: bridge them when the level resumes at the same ratio.
        n0 = len(pts)
        q = 1
        while q < n0 - 1:
            if bad[q - 1] and not bad[q]:
                e = q
                while e < n0 and not bad[e] and e - q < 2:
                    e += 1
                if e < n0 and bad[e] and abs(r[e] / r[q - 1] - 1) <= LEVEL_TOL:
                    for z in range(q, e):
                        bad[z] = True
                    q = e
                    continue
            q += 1
        n = len(pts)
        i = 0
        while i < n:
            if not bad[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and bad[j + 1]:
                j += 1
            k = i  # cut the run into constant-ratio levels
            while k <= j:
                lv = [r[k]]
                m = k
                blips = []
                while m + 1 <= j:
                    ref = statistics.median(lv[-5:])
                    if abs(r[m + 1] / ref - 1) <= LEVEL_TOL:
                        m += 1
                        lv.append(r[m])
                        continue
                    # a 1-2 point excursion that comes back to the level is a bad print inside it, not a new level
                    back = next(
                        (q for q in (m + 2, m + 3) if q <= j and abs(r[q] / ref - 1) <= LEVEL_TOL),
                        None,
                    )
                    if back is None:
                        break
                    blips.extend(range(m + 1, back))
                    m = back
                    lv.append(r[m])
                self._level(sym, pts, r, k, m, evs, last_d, blips)
                k = m + 1
            i = j + 1

    @staticmethod
    def _edge(pts, x, y, evs):
        """What happens between points x and y (x < y): which file's own close jumps by the change in A/B."""
        if x < 0 or y >= len(pts):
            return None
        (d1, a1, b1), (d2, a2, b2) = pts[x], pts[y]
        gap = (C.day(d2) - C.day(d1)).days
        e = {
            "from": C.iso(d1),
            "to": C.iso(d2),
            "a_jump": round(a2 / a1, 4),
            "b_jump": round(b2 / b1, 4),
            "ledger": [[C.iso(d), k, f] for d, k, f in _near(evs, d1, d2)],
        }
        la, lb = abs(math.log(a2 / a1)), abs(math.log(b2 / b1))
        own = any(k in ("demerger", "rights") for _, k, _ in _near(evs, d1, d2))
        if gap > 12:
            e["side"] = "?"
            e["why"] = "points %d days apart" % gap
        # Yahoo's close EXACTLY unchanged while NSE's official close moved: Yahoo's frozen/stale print (J&KBANK sat at
        # 157.96 for 2014-2017, HCL-INSYS at 64.52 for 663 sessions, 18-Mar-2025 for 492 members) — never a store step
        elif b2 == b1 and la > 0.01:
            e["side"] = "B"
            e["why"] = "Yahoo's close unchanged while NSE's moved"
        elif la < 0.18 and lb > 0.4:
            e["side"] = "B"
        elif lb < 0.18 and la > 0.4:
            e["side"] = "A"
        # consecutive DAILY sessions (<= 5 calendar days, a long weekend): one session's market move stays under
        # ~12 %, so the file whose own close moves >= 10 points more than the other's is the one that stepped
        # (CONCOR's missed 1:4 bonus steps Yahoo x0.8 at 1-Jan-2025 while NSE moves 1 %; the weekly rule needed x1.5).
        # NOT across one of OUR demerger/rights ex-dates: the store's factor is ex-OPEN / prev close, so it keeps the
        # ex-day's own intraday move (SIEMENS 07-Apr-2025: open 2,450 -> close 2,812.45, +14.8 %) while Yahoo folds it
        # into its factor — two conventions, not a step in either; the level logic below explains those.
        elif gap <= 5 and not own and la < 0.12 and lb - la > 0.1:
            e["side"] = "B"
        elif gap <= 5 and not own and lb < 0.12 and la - lb > 0.1:
            e["side"] = "A"
        else:
            e["side"] = "?"
        return e

    def _level(self, sym, pts, r, k, m, evs, last_d, blips=()):
        rs = [r[q] for q in range(k, m + 1) if q not in blips]
        med = statistics.median(rs)
        left = self._edge(pts, k - 1, k, evs)
        right = self._edge(pts, m, m + 1, evs)
        end_live = m + 1 >= len(pts) and pts[m][0] >= C.ymd(
            C.day(last_d) - datetime.timedelta(days=7)
        )
        if m == k:
            shape = "spike"
        elif end_live:
            shape = "to-end"
        else:
            shape = "level"
        sides = {e["side"] for e in (left, right) if e and e["side"] != "?"}
        side = sides.pop() if len(sides) == 1 else ("?" if not sides else "both")
        # Which of OUR ledger factors does the level equal? Before an event with factor f that A applies and B does not,
        # A/B = f; so a level equal to the product of our demerger/rights factors up to the next agreeing point is
        # Yahoo's by-design gap (it adjusts splits/bonus only), and one equal to our split/bonus product is a split
        # Yahoo is missing. The window runs to the next AGREEING point, across any membership gap.
        nxt = next(
            (
                q
                for q in range(m + 1, len(pts) - 2)
                if all(abs(r[z] - 1) <= TOL for z in (q, q + 1, q + 2))
            ),
            None,
        )
        win = _near(evs, pts[m][0], pts[nxt][0] if nxt is not None else 99999999)

        def prod(kinds):
            return math.prod(float(f) for _, k, f in win if k in kinds and f)

        dr, sp = prod(("demerger", "rights")), prod(("split/bonus",))
        match = None
        if win:
            if any(k in ("demerger", "rights") for _, k, _ in win) and abs(med / dr - 1) <= 0.015:
                match = "demerger/rights"
            elif any(k == "split/bonus" for _, k, _ in win) and abs(med / sp - 1) <= 0.015:
                match = "split/bonus"
            elif abs(med / (dr * sp) - 1) <= 0.015:
                match = "all"
            elif any(k == "split/bonus" for _, k, _ in win) and abs(med * sp - 1) <= 0.015:
                match = "split/bonus inverse"
        why = None
        dem = [(d, k, f) for d, k, f in win if k != "split/bonus"]
        if dem and not any(k == "split/bonus" for _, k, _ in win) and side in ("B", "?"):
            what = "/".join(sorted({k for _, k, _ in dem}))
            when = ", ".join(C.iso(d) for d, _, _ in dem)
            if match == "demerger/rights":
                why = f"level = our {what} factor {dr:.4f} ({when}); Yahoo does not adjust it"
            else:
                why = f"level ends at our {what} adjustment ({when}, factor {dr:.4f}); Yahoo applies its own factor ({dr / med:.4f} implied)"
        served = getattr(self, "_served", "yahoo")
        if why is None and served == "store":
            # the dashboard serves A here; a disagreement Yahoo alone causes is Yahoo's error, not a served one
            if side == "B":
                why = (
                    "Yahoo's own error: its close steps at the edge while NSE's official close is continuous; the "
                    "dashboard serves the NSE store for this member (§214a F1)"
                )
            elif shape == "spike" and left and left["b_jump"] == 1.0 and left["a_jump"] != 1.0:
                why = (
                    "Yahoo repeated the previous session's close while NSE's close moved; the dashboard serves the NSE "
                    "store for this member (§214a F1)"
                )
        self.add(
            f"{sym}|{pts[k][0]}",
            sym=sym,
            shape=shape,
            date_from=C.iso(pts[k][0]),
            served=served,
            date_to=C.iso(pts[m][0]),
            n=m - k + 1,
            ratio=round(med, 4),
            a_over_b=[round(min(rs), 4), round(max(rs), 4)],
            wrong=side,
            left=left,
            right=right,
            explained=why,
            ledger_match=match,
            ledger_window=[[C.iso(d), k, f] for d, k, f in win][:6],
            blips=[
                [C.iso(pts[q][0]), round(pts[q][1], 2), round(pts[q][2], 2)]
                for q in list(blips)[:6]
            ],
            weight=round((m - k + 1) * abs(math.log(med)), 3),
        )
