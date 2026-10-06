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
"""§164c/§164d — D1 remainder rule + the row-level re-read of FORMER Nifty 500 members (user 2026-09-25: "adopt all three
recommendations, do it"). Reuses scripts/_shp_dii_rowfix.py (R1/R2/R3, §158a) and scripts/_shp_fii_rowfix.py (R2-FII) read-only.
D1: in the SEBI form used Dec-2015..Jun-2022, the UNNAMED, UNLABELLED part of the institutional "Any Other" block counts as FII
(Quantmac's rule, adopted): the R1-unresolved part the store holds in dii, the uncovered remainder, and the rest of a label-less
row beside named domestic or mixed holders all move dii -> fii. Labelled rows and named holders keep their R1 placement.
Ex-members (never re-read before): the full §158 evaluation (R1/R2/R3) + §159 R2-FII are applied, then D1.
Stages: classify SYMS|current|ex -> <work>/d1_proposals.json ; verify ; write (merges into shp_cell_fix.json with
`superseded`; evidence into scripts/_shp_d1_rowfix_audit.json, merged, never replaced)."""
import collections
import copy
import json
import os
import re
import sys
import time

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
# No browser impersonation, ever (feedback-no-browser-impersonation-to-pass-bse-filter). The imported modules carry
# curl_cffi impersonate="chrome" cache-miss fallbacks; this shim answers them with a PLAIN, honestly identified request
# (fixed User-Agent, www.bseindia.com only — it serves such clients). api.bseindia.com refuses plain clients: refused here.
import time as _tm
import types as _t
import urllib.error as _ue
import urllib.request as _ur

_UA = "stocks-dashboard-data-fetch/1.0 (+personal research; contact via github dhruvan246)"


class _Resp:
    def __init__(s, code, body):
        s.status_code = code
        s.content = body
        s.text = body.decode("utf-8", "ignore")

    def json(s):
        import json as _j

        return _j.loads(s.text)


def _plain_get(url, headers=None, impersonate=None, timeout=60, **k):
    if "api.bseindia.com" in url or "bseindia.com" not in url:
        return _Resp(403, b"")
    for a in range(3):
        try:
            r = _ur.urlopen(
                _ur.Request(
                    url, headers={"User-Agent": _UA, "Referer": "https://www.bseindia.com/"}
                ),
                timeout=timeout,
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
import _shp_dii_rowfix as D
import _shp_fii_rowfix as X

F = D.F
WORK = os.environ.get("D1_ROWFIX_WORK") or X.WORK
MARK = "§164 row-level remainder rule"
D1_FROM = "2015-12-31"
# §164j (user 2026-09-26): current members whose §164 cells the DII runner skips (chain_has §164) may take the corrected R1
# result here — the rule itself was fixed (foreign labels, documentary proof), not re-judged. Comma list in D1_ACCEPT_R1.
ACCEPT_R1 = {x for x in os.environ.get("D1_ACCEPT_R1", "").split(",") if x}
AUDIT_PATH = os.path.join(SCRIPTS, "_shp_d1_rowfix_audit.json")
NAMED = re.compile(r"(.{2,90}?) (\d+\.\d+) (?:foreign|domestic|\?)->")


def named_sum(desc):
    return sum(float(m.group(2)) for m in NAMED.finditer(str(desc)))


def d1_delta(r, bd, res, cur, ext_fii, add_prev):
    """dii -> fii amount D1 adds on top of the R1 result r (0 when nothing unnamed sits in dii).
    Unnamed = not a named >=1% holder: named holders of unknown class stay where the store has them. When every named holder
    of the block is DOMESTIC the unnamed rest follows them (stays dii) — measured: HDFCBANK / APOLLOTYRE Jun-2022, whose
    Sep-2022 2022-form filings keep the same shares in Institutions (Domestic); a foreign-only block's rest already went to fii
    under §158a/§158b. No named holder, or a mixed block -> the rest is FII (Quantmac's rule)."""
    oth = bd.get("OtherInstitutionsMember") or 0.0
    if oth < 0.005 or r.get("overflow"):
        return 0.0, []
    evs = [str(e) for e in r["ev"] if str(e[0]).startswith("R1")]
    f_named = any(re.search(r"foreign->(fii|public)", e) for e in evs)
    d_named = any(
        e.startswith("['R1-domestic") or e.startswith("('R1-domestic") or "domestic->" in e
        for e in evs
    )
    if d_named and not f_named:
        return 0.0, [("D1-not-applied", "every named holder domestic: the rest follows them")]
    left = min(oth, max(0.0, res["dii"] + add_prev - (cur[2] or 0)))
    unres = r["unres"]
    u_out = min(unres, max(0.0, left - (r["mv_fii"] + r["mv_pub"])))
    u_dii = max(0.0, unres - u_out)
    named_unres = sum(named_sum(e[3]) for e in r["ev"] if e[0] == "R1-unresolved" and len(e) > 3)
    mov = max(0.0, u_dii - named_unres)
    ev = []
    rests = 0.0
    if mov > 0.004:
        ev.append(
            ("D1-unnamed-remainder-in-dii", round(mov, 4))
            + (
                (("named holders of unknown class left as stored", round(named_unres, 4)),)
                if named_unres > 0.004
                else ()
            )
        )
    for e in r["ev"]:
        if e[0] == "R1-mixed":
            pct = float(e[2])
            ns = named_sum(e[4])
            if ns <= pct + 0.02 and pct - ns > 0.004:
                rests += pct - ns
                ev.append(("D1-rest-beside-mixed-holders", e[1], round(pct - ns, 4)))
        elif (
            e[0] == "R1-domestic-holders"
        ):  # a domestic-only ROW inside a block that also names foreign holders
            pct = float(e[2])
            ns = named_sum(e[3])
            if ns <= pct + 0.02 and pct - ns > 0.004:
                rests += pct - ns
                ev.append(("D1-rest-beside-domestic-row-in-mixed-block", e[1], round(pct - ns, 4)))
    return round(mov + rests, 4), ev


# D1 corroboration gate (user 2026-09-28, "Option A ... do this"; runbook §164r batch 5): an unnamed remainder of >= 1 pp moves
# dii -> fii only when the company's OWN neighbouring filing shows a foreign holding that size — the quarter-end filing before
# or after (for a mid-quarter event, the quarters around it) holds FII at least halfway to the moved level. Measured: of 130
# recorded moves >= 1 pp, 13 had no such support (CENTRALBK Jun-2018: an unnamed 9.12 % Other-Institutions block went to FII
# 0.27 -> 9.39 while Mar / Sep-2018 print 0.21 / 0.35 and Quantmac serves 0.29; PVRINOX Jun-2017 39.68 -> 56.80 between 40.85
# and 42.31). Without a neighbour on one side the move is not tested. Neighbours come from the REAL store (the §164q runner
# swaps REPO for its event store).
D1_GATE_MIN = 1.0
_REAL_HIST = None


def d1_corroborated(sym, qe, fii_after, dd):
    global _REAL_HIST
    if _REAL_HIST is None:
        _REAL_HIST = json.load(open(os.path.join(SCRIPTS, "shp_history.json")))
    qs = sorted(
        k
        for k in (_REAL_HIST.get(sym) or {})
        if not k.startswith("_") and k[5:] in ("03-31", "06-30", "09-30", "12-31")
    )
    prv = [k for k in qs if k < qe]
    nxt = [k for k in qs if k > qe]
    if not prv or not nxt:
        return True, "no neighbour on one side (not tested)"
    p, n = prv[-1], nxt[0]
    pv = _REAL_HIST[sym][p][1]
    nv = _REAL_HIST[sym][n][1]
    if pv is None or nv is None:
        return True, "neighbour without FII (not tested)"
    need = fii_after - 0.5 * dd
    ok = pv >= need or nv >= need
    return (
        ok,
        f"{p} FII {pv:.2f}, {n} FII {nv:.2f} vs {need:.2f} needed (moved level {fii_after:.2f})",
    )


# §164r batch 7 (user 2026-09-29 'Follow the later label', 37 cells measured and approved): the UNNAMED institutional Any-Other
# block follows the label the company itself gives a block of the same size (within D1_LABEL_TOL) in a neighbouring filing —
# walking quarter by quarter (up to 6 hops each way) through filings where the block stays unnamed and the same size. PVRINOX
# Jun/Sep-2016: 19.07 / 18.32 unnamed, then Dec-2016 'FOREIGN CORPORATE BODIES' 17.89 (Plenty 8.81, Multiples 6.22 ...) -> public,
# not FII (the 19-point spike and drop was the default rule, not a trade). A company-type / DR / foreign-national label -> public;
# a domestic-institution label -> DII; a foreign-institution label (or none found) -> FII as before.
D1_LABEL_TOL = 0.12
_D1Q = []
_y, _m = 2015, 12
while (_y, _m) <= (2022, 6):
    _D1Q.append("%d-%02d-%02d" % (_y, _m, {3: 31, 6: 30, 9: 30, 12: 31}[_m]))
    _m += 3
    if _m > 12:
        _m = 3
        _y += 1
_FORW = re.compile(r"foreign|forign|foriegn|global|overseas|\bfii|\bfpi|\bqfi|sovereign", re.I)
_DRW = re.compile(r"\bdr\b|depositor|\bgdr|\badr", re.I)


def d1_lab_class(L):
    if _DRW.search(L) or D.LAB_PUB.search(L) or D.noninst_label(L):
        return "pub"  # §164r batch 11: Bodies Corporate / Government / IEPF ... rows are not FII
    if D.LAB_FII.search(L) or (_FORW.search(L) and D.DOMLAB.search(L)):
        return "fii"
    if D.DOMLAB.search(L):
        return "dii"
    return None


_D1BLK = {}


def _d1_block(sym, qe, byq, ctx):
    if (sym, qe) in _D1BLK:
        return _D1BLK[(sym, qe)]
    out = None
    for _fd, f in sorted(byq.get(qe) or []):
        p = D.find_file(f)
        if not p:
            continue
        try:
            txt = open(p, "rb").read()
            rows = D.rows_of(txt)
        except Exception:
            continue
        gs = D.groups(rows, "OtherInstitutionsMember") or D.groups(rows, "OtherInstitutions")
        lab = []
        unnamed = 0.0
        if not gs:  # a block filed with no typed rows (PVRINOX Sep-2016): its size is the filing's own block total
            try:
                unnamed = D.breakdown(txt).get("OtherInstitutionsMember") or 0.0
            except Exception:
                unnamed = 0.0
        for g in gs:
            cls = d1_lab_class(g["label"])
            hs = [(hn, hp) + tuple(ctx.hclass(hn, hp)[:2]) for hp, hn in g["holders"]]
            if cls is None and not hs:
                unnamed += g["pct"]
            lab.append((g["label"], g["pct"], cls, hs))
        out = (lab, unnamed, f)
        break
    _D1BLK[(sym, qe)] = out
    return out


def d1_follow_label(sym, qe, dd, byq, ctx, _depth=0):
    """-> (class 'pub'|'dii'|'fii', evidence) of the unnamed block from the nearest same-size labelled block, or (None, reason)."""
    if qe not in _D1Q:
        return None, "outside the Dec-2015..Jun-2022 form"
    for step in (1, -1):
        i = _D1Q.index(qe)
        hops = 0
        while 0 <= i + step < len(_D1Q) and hops < 6:
            i += step
            hops += 1
            b = _d1_block(sym, _D1Q[i], byq, ctx)
            if not b:
                break
            lab, unnamed, f = b
            cand = [x for x in lab if (x[2] or x[3]) and abs(x[1] - dd) <= D1_LABEL_TOL * dd]
            if not cand and unnamed and abs(unnamed - dd) <= D1_LABEL_TOL * dd:
                continue  # the same block, still unnamed
            if cand:
                x = cand[0]
                cls = x[2]
                if not cls:
                    dests = collections.Counter(
                        "fii" if h[3] == "fii" else "dii" if h[2] == "domestic" else "pub"
                        for h in x[3]
                    )
                    cls = dests.most_common(1)[0][0]
                return cls, "{} filing {} labels a {:.2f} block '{}'{}".format(
                    _D1Q[i],
                    f,
                    x[1],
                    x[0],
                    (" (" + "; ".join(f"{h[0]} {h[1]:.2f}" for h in x[3][:3]) + ")")
                    if x[3]
                    else "",
                )
            break
    return None, "no same-size labelled block within 6 filings either way"


def prior_inputs(led, sym, qe, cur, audit158, audit164=None):
    prior = (led.get(sym) or {}).get(qe)
    ext_fii = 0.0
    add_prev = 0.0
    mv159_prev = 0.0
    chain = prior
    depth = 0
    seen164 = False
    add14 = 0.0
    seen14 = False
    while chain and depth < 8:
        w = chain.get("why") or ""
        if "§159 row-level FII heal" in w and chain.get("was") and chain.get("cell"):
            ext_fii += round(float(chain["cell"][1]) - float(chain["was"][1]), 4)
        if "§158 row-level DII heal" in w and not add_prev:
            add_prev = float((audit158.get(f"{sym}|{qe}") or {}).get("add_dii") or 0.0)
        # §164j: a former member's own §164 entry carries its R2-FII (§159-rule) move and R2 dii adds in the §164 audit, not in a
        # separate §159/§158 entry — count them, or the stored split looks inexplicable and the cell is skipped (split_unknown)
        if "§164 row-level remainder rule" in w and not seen164 and audit164 is not None:
            a = audit164.get(f"{sym}|{qe}") or {}
            seen164 = True
            mv159_prev = float(a.get("mv159") or 0.0)
            ext_fii += mv159_prev
            if not add_prev:
                add_prev = float(a.get("add_dii") or 0.0)
        # §164r batch 14 (FDI-line holders, user 2026-10-04 'yes go with A'): its §164 audit entry carries the non-institution
        # (R2-FII-type) part of its move as mv159_add - count it, or the cell reads as an inexplicable split (split_unknown)
        if "§164r batch 14" in w and not seen14 and audit164 is not None:
            add14 = float((audit164.get(f"{sym}|{qe}") or {}).get("mv159_add") or 0.0)
            seen14 = True
        chain = chain.get("superseded") if isinstance(chain.get("superseded"), dict) else None
        depth += 1
    ext_fii += add14
    mv159_prev += add14
    healed = False
    chain = prior
    depth = 0
    while chain and depth < 8:
        if F.VALUE_HEAL_MARK.search(str(chain.get("why") or "")):
            healed = True
            break
        chain = chain.get("superseded") if isinstance(chain.get("superseded"), dict) else None
        depth += 1
    return prior, ext_fii, add_prev, healed, mv159_prev


def classify(syms, tag, ex_set):
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    led = json.load(open(os.path.join(REPO, "scripts", "shp_cell_fix.json"))).get("fix", {})
    audit158 = (
        json.load(open(os.path.join(SCRIPTS, "_shp_dii_rowfix_audit.json"))).get("cells") or {}
    )
    try:
        audit164 = (
            json.load(open(os.path.join(SCRIPTS, "_shp_164_audit.json"), encoding="utf-8")).get(
                "cells"
            )
            or {}
        )
    except (OSError, ValueError):
        audit164 = {}
    verdicts = D.load_verdicts()
    P = {}
    st = collections.Counter()
    t0 = time.time()
    for si, sym in enumerate(syms):
        lp = os.path.join(D.LISTS, sym + ".json")
        if not os.path.exists(lp):
            st["no_bse_list"] += 1
            continue
        d = json.load(open(lp))
        bse_rows = d.get("Table") if isinstance(d, dict) else d
        byq = D.quarter_files(bse_rows)
        ctx = D.SymCtx(sym, bse_rows, verdicts)
        fctx = X.FiiCtx(sym, bse_rows, verdicts)
        is_ex = sym in ex_set
        order = [(q, f, False) for q, f in sorted(byq.items(), reverse=True)] + [
            (q, f, True) for q, f in sorted(byq.items())
        ]
        for qe, fl, final in order:
            cur = (hist.get(sym) or {}).get(qe)
            if final:
                st["rows"] += 1
            if not cur:
                if final:
                    st["no_store_row"] += 1
                continue
            prior, ext_fii, add_prev, healed, mv159_prev = prior_inputs(
                led, sym, qe, cur, audit158, audit164
            )
            chosen = D.match_filing(fl, qe, cur, None, ext_fii, healed)
            if not chosen:
                pk = X.pick_filing(
                    sym, qe, cur, fl, led
                )  # §158's own recorded file, else a parse matching a `was` in the chain
                if pk:
                    chosen = pk[:4]
                    if final:
                        st["matched_via_" + pk[4].split("@")[0]] += 1
            if not chosen:
                if final:
                    st[
                        "not_cached"
                        if not any(D.find_file(f) for fd, f in fl)
                        else "no_matching_filing"
                    ] += 1
                continue
            f, txt, bd, res = chosen
            r = D.eval_filing(ctx, qe, txt, bd, res, cur, final, None, ext_fii, add_prev)
            if is_ex:
                X.eval_fii(
                    fctx, qe, txt, bd, res, cur
                )  # warm the §159 holder memory on both passes
            if not final:
                continue
            st["matched"] += 1
            if r is None:
                st["split_unknown"] += 1
                continue
            t_fii, t_dii = r["t_fii"], r["t_dii"]
            ev = list(r["ev"])
            parts = []
            base_moved = abs(t_fii - (cur[1] or 0)) >= 0.05 or abs(t_dii - (cur[2] or 0)) >= 0.05
            if base_moved and not is_ex and sym not in ACCEPT_R1:
                # a current member's only R1 difference may be §158a rest-follows the DII session did not write (its 48 extras):
                # that is a D1 case (unnamed rest -> fii); any other R1 difference is the DII session's, left untouched
                rf = sum(float(e[1]) for e in r["ev"] if e[0] == "R1-rest-follows-foreign-holders")
                dfi = t_fii - (cur[1] or 0)
                ddi = t_dii - (cur[2] or 0)
                if rf >= 0.05 and abs(dfi - rf) <= 0.06 and abs(ddi + rf) <= 0.06:
                    parts.append("D1 (rest beside foreign holders, §158a semantics)")
                    st["current_rest_follows_extra"] += 1
                else:
                    st["current_member_R1_moves_(left_to_the_DII_session)"] += 1
                    t_fii, t_dii = cur[1] or 0, cur[2] or 0
            elif base_moved and not is_ex:
                parts.append(
                    "R1-R3 re-read (§164j: foreign-labelled rows are never a domestic label; name-only holders need a document)"
                )
            elif base_moved:
                parts.append("R1-R3 (§158 rules, first read)")
            mv159 = 0.0
            if is_ex:
                rf = X.eval_fii(fctx, qe, txt, bd, res, cur)
                mv159 = rf["mv"] if not any(e[0] == "R2FII-overflow" for e in rf["ev"]) else 0.0
                # eval_filing's t_fii already carries the R2-FII move recorded in this cell's own §164 entry (mv159_prev, via
                # ext_fii): REPLACE it with today's reading, never add a second one (§164j; RAJESHEXPO 2017-21 double-counted)
                new159 = mv159 if mv159 >= 0.05 else 0.0
                if abs(new159 - mv159_prev) >= 0.005 or new159 >= 0.05:
                    t_fii = round(t_fii - mv159_prev + new159, 4)
                    if new159 >= 0.05:
                        ev += rf["ev"]
                        parts.append("R2-FII (§159 rules)")
            dd = 0.0
            if qe >= D1_FROM:
                dd, dev = d1_delta(r, bd, res, cur, ext_fii, add_prev)
                dd = min(dd, t_dii)
                if dd >= D1_GATE_MIN:
                    ok_g, why_g = d1_corroborated(sym, qe, t_fii + dd, dd)
                    if not ok_g:
                        ev.append(("D1-held-uncorroborated", round(dd, 4), why_g))
                        st["d1_held_uncorroborated"] += 1
                        dd = 0.0
                lc = None
                if dd >= 0.005:
                    lc, lwhy = d1_follow_label(sym, qe, dd, byq, ctx)
                    if lc in ("pub", "dii"):
                        ev.append(("D1-follows-label", round(dd, 4), lc, lwhy))
                        st["d1_follows_label_" + lc] += 1
                if dd >= 0.005 and lc == "pub":
                    t_dii = round(t_dii - dd, 4)
                    ev += dev
                    parts.append(
                        "D1 unnamed remainder follows the company's own neighbouring label -> public"
                    )
                elif dd >= 0.005 and lc == "dii":
                    parts.append(
                        "D1 unnamed remainder follows the company's own neighbouring label -> DII (stays)"
                    )
                elif dd >= 0.005:
                    t_fii = round(t_fii + dd, 4)
                    t_dii = round(t_dii - dd, 4)
                    ev += dev
                    parts.append("D1 unnamed remainder -> FII")
            if abs(t_fii - (cur[1] or 0)) < 0.05 and abs(t_dii - (cur[2] or 0)) < 0.05:
                st["unchanged"] += 1
                continue
            new = list(cur)
            new[1] = round(t_fii, 4)
            new[2] = round(t_dii, 4)
            if is_ex and cur[4] is not None and r["add_ins"] > 0:
                new[4] = round(r["ins_base"] + r["add_ins"], 4)
            P[f"{sym}|{qe}"] = {
                "file": f,
                "was": cur,
                "cell": new,
                "ex_member": is_ex,
                "d1": dd,
                "mv159": mv159,
                "parts": parts,
                "d_fii": round(new[1] - (cur[1] or 0), 4),
                "d_dii": round(new[2] - (cur[2] or 0), 4),
                "ev": ev,
                "add_dii": r["add_dii"],
                "prior_entry": bool(prior),
                "newmap_file": ctx.newfile,
            }
            st["proposed"] += 1
            st["proposed_ex" if is_ex else "proposed_current"] += 1
        if si % 50 == 0:
            print(
                "  %d/%d %s %s %.0fs" % (si, len(syms), sym, dict(st), time.time() - t0),
                file=sys.stderr,
                flush=True,
            )
    json.dump(P, open(os.path.join(WORK, f"d1_proposals_{tag}.json"), "w"), indent=0)
    print(f"classify {tag} done", dict(st))
    return P


def verify(tags):
    P = {}
    for t in tags:
        P.update(json.load(open(os.path.join(WORK, f"d1_proposals_{t}.json"))))
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    H = copy.deepcopy(hist)
    n = bad = 0
    sane = 0
    for k, v in P.items():
        s, q = k.split("|")
        cur = H[s][q]
        if not F._cell_eq(cur, v["was"]):
            bad += 1
            continue
        H[s][q] = list(v["cell"])
        n += 1
        c = v["cell"]
        if c[1] < 0 or c[2] < 0 or (c[0] or 0) + c[1] + c[2] > 100.5:
            sane += 1
            print("SANITY", k, c[:5])
    print("applied %d, was-mismatch %d, sanity flags %d" % (n, bad, sane))
    syms = sorted({k.split("|")[0] for k in P})

    def seam(h, qa, qb, slot):
        ds = []
        for s in syms:
            a = (h.get(s) or {}).get(qa)
            b = (h.get(s) or {}).get(qb)
            if a and b and a[slot] is not None and b[slot] is not None:
                ds.append(b[slot] - a[slot])
        return len(ds), sum(1 for x in ds if abs(x) >= 3)

    for qa, qb in (
        ("2016-03-31", "2016-06-30"),
        ("2016-06-30", "2016-09-30"),
        ("2022-06-30", "2022-09-30"),
    ):
        for sl, nm in ((1, "fii"), (2, "dii")):
            print(
                f"  {nm} {qa}->{qb} |jump|>=3pp: before {seam(hist, qa, qb, sl)} after {seam(H, qa, qb, sl)}"
            )
    json.dump(H, open(os.path.join(WORK, "shp_history_d1.json"), "w"), separators=(",", ":"))


def export(tag, out, section="", only164=False):
    """d1_proposals_<tag>.json -> a proposal file for scripts/_shp_164_write.py (was/cell/src/why + audit fields). With only164,
    keep only cells whose current ledger entry is already a §164 cell or a former member's (current members' other cells
    belong to the DII session's writer)."""
    P = json.load(open(os.path.join(WORK, f"d1_proposals_{tag}.json")))
    led = json.load(open(os.path.join(SCRIPTS, "shp_cell_fix.json"))).get("fix", {})
    stamp = time.strftime("%Y-%m-%d")
    O = {}
    for k, v in sorted(P.items()):
        s_, q = k.split("|")
        top = ((led.get(s_) or {}).get(q) or {}).get("why", "")
        if only164 and not (v.get("ex_member") or "\u00a7164" in top):
            continue
        cur, new = v["was"], v["cell"]
        why = (
            "{} ({}{}; {}): fii {:.2f} -> {:.2f}, dii {:.2f} -> {:.2f}. {}. §158 rules (R1 institutional Any-Other holders placed as the "
            "filer's own 2022 form places them, R2 domestic institutions parked under non-institutions, R3 NBFC row) + §159 rule "
            "(non-institutional foreign holders the filer's 2022 form lists under Institutions (Foreign)) + D1 (unnamed rest of the "
            "institutional block = FII in the 2015-22 form unless every named holder is domestic). | {}"
        ).format(
            MARK,
            stamp,
            (" " + section) if section else "",
            "FORMER Nifty 500 member" if v.get("ex_member") else "current member",
            cur[1],
            new[1],
            cur[2],
            new[2],
            ", ".join(v.get("parts") or []),
            "; ".join(" ".join(str(x) for x in e) for e in v.get("ev") or [])[:700],
        )
        O[k] = {
            "was": cur,
            "cell": new,
            "src": "bsexbrl:{}".format(v["file"]),
            "why": why,
            "parts": v.get("parts"),
            "ev": v.get("ev"),
            "d1": v.get("d1"),
            "mv159": v.get("mv159"),
            "ex_member": v.get("ex_member"),
            "newmap_file": v.get("newmap_file"),
            "add_dii": v.get("add_dii"),
        }
    json.dump(O, open(out, "w"), indent=0)
    print("export %s: %d proposals -> %s" % (tag, len(O), out))


if __name__ == "__main__":
    st = sys.argv[1]
    if st == "classify":
        which = sys.argv[2]
        sc = json.load(open(os.path.join(WORK, "exmember_scope.json")))
        ex = set(sc["ex"])
        syms = (
            sc["current"] if which == "current" else sc["ex"] if which == "ex" else which.split(",")
        )
        classify(syms, which if which in ("current", "ex") else "one", ex)
    elif st == "verify":
        verify(sys.argv[2].split(","))
    elif st == "export":
        export(
            sys.argv[2],
            sys.argv[3],
            section=(sys.argv[4] if len(sys.argv) > 4 else ""),
            only164=("--only164" in sys.argv),
        )
