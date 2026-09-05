# -*- coding: utf-8 -*-
"""Extract the ORDER VALUE from each order-win announcement PDF and cache it, so the Discovery
"Order Wins" bucket can show "₹1,180 cr" instead of NSE's generic boilerplate caption
("X has informed the Exchange about Bagging/Receiving of orders/contracts").

  in : docs/announcements.json  (order/contract rows -> attachment PDF)
  out: docs/order_values.json   {updated, vals:{<file>: {"t":"<display>","cr":<₹ crore|null>}}}
                                 (a "" value means "checked, no value found" — avoids re-fetching)

The cache is keyed by the attachment `file` (unique per filing) and is INCREMENTAL + committed:
each run only downloads PDFs it hasn't seen, then prunes entries whose file left the window.
build_discovery.py reads this cache and overrides the caption for the Order Wins bucket.

Values are pulled with three text patterns (unit-suffixed "Rs 1,180 crore"; currency-prefixed
full-digit "Rs 205,20,29,635"; and the figure before a spelled-out "(Rupees … Crore …)" clause),
scored by proximity to order keywords. Scanned image-only PDFs and genuinely-undisclosed values
yield no entry (the page then falls back to the original caption).

Run: python -X utf8 scripts/enrich_order_values.py   (CI: refresh-announcements.yml, before build_discovery)
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / nse_jar / UA

HERE = os.path.dirname(os.path.abspath(__file__))
def dp(f): return os.path.join(HERE, "..", "docs", f)
ANN = dp("announcements.json")
OUT = dp("order_values.json")
PREF = "https://nsearchives.nseindia.com/corporate/"
HDR = {"User-Agent": B.UA, "Referer": "https://www.nseindia.com/"}
ORDER_RX = re.compile(r"orders?/contracts|order\(s\)\/contract", re.I)

# ---- value extraction ------------------------------------------------------
CCY  = r"(?:Rs\.?|INR|₹|US\$|USD|\$|AUD|EUR|€)"
UNIT = r"(?:cr(?:ore)?s?|lakhs?|lacs?|mn|million|bn|billion)"
AMT  = r"\d[\d,]*(?:\.\d+)?"
MONEY  = re.compile(r"(~?\s*%s\s*)?(%s)(\s*/-)?\s*(%s)\b" % (CCY, AMT, UNIT), re.I)
MONEY2 = re.compile(r"(~?\s*)(Rs\.?|INR|₹|US\$|USD|\$)\s*(\d[\d,]*(?:\.\d+)?)(?!\s*(?:%s))" % UNIT, re.I)
MONEY3 = re.compile(r"(~\s*)?(?:Rs\.?|INR|₹)?\s*(\d[\d, ]*\d)(?:\.\d+)?\s*(?:/-)?\s*"
                    r"(?:\([^)]{0,25}\)\s*)?\((?:[^)]{0,80}?(?:Rupees|INR|Crores?|Lakhs?))\b", re.I)
KEYS = re.compile(r"order|contract|value|worth|aggregat|awarded|bagg|LOA|letter of (?:award|acceptance|intent)"
                  r"|valued|total|receipt|received|secured|won|bag", re.I)
# a materiality/policy DEFINITION of "large order", not this order's value -> ignore that amount
NEG = re.compile(r"means an order|large order means|materialit|whichever is (?:lower|higher)|threshold|"
                 r"policy on|deems? material|exceed(?:s|ing) \d", re.I)
USD_TRAIL = re.compile(r"^\s*(?:USD|US ?Dollar|Dollar)", re.I)

def _cur_from(ccy):
    c = ccy.lower()
    if "$" in ccy or "usd" in c: return "US$"
    if "aud" in c: return "AUD"
    if "eur" in c or "€" in ccy: return "€"
    return "₹"

FX_USD = 86.0   # ₹/US$ — approximate; only used to size the "× annual sales" heuristic

def fmt_amt(v, approx, cur):
    """v is in the currency's base unit (rupees for ₹, dollars for US$)."""
    if cur != "₹":
        if v >= 1e9: return "%s%s %s bn" % (approx, cur, ("%.2f" % (v/1e9)).rstrip("0").rstrip("."))
        if v >= 1e6: return "%s%s %s mn" % (approx, cur, ("%.2f" % (v/1e6)).rstrip("0").rstrip("."))
        return "%s%s %s" % (approx, cur, "{:,.0f}".format(v))
    cr = v/1e7
    if cr >= 1: return "%s₹ %s cr" % (approx, ("%.2f" % cr).rstrip("0").rstrip("."))
    return "%s₹ %.2f lakh" % (approx, v/1e5)

def _inr_cr(v_base, cur):
    """Convert a base-unit amount to ₹ crore (None for currencies we don't convert)."""
    if cur == "₹":  return round(v_base / 1e7, 2)
    if cur == "US$": return round(v_base * FX_USD / 1e7, 2)
    return None

def extract(txt):
    """Return (display_string, inr_crore|None) for the best order value found, or None."""
    txt = re.sub(r"\s+", " ", txt or "")
    if len(txt) < 40: return None                      # scanned / empty PDF
    best, best_cr, best_score = None, None, 1.0         # require a minimum signal
    # 1) amount + unit word
    for m in MONEY.finditer(txt):
        ccy, amt, unit = (m.group(1) or "").strip(), m.group(2), m.group(4).lower()
        s, e = m.start(), m.end()
        ctx = txt[max(0, s-90):e+40]
        if NEG.search(ctx): continue
        cur = _cur_from(ccy)
        if cur == "₹" and USD_TRAIL.match(txt[e:e+12]): cur = "US$"   # "35.42 Million USD"
        try: v = float(amt.replace(",", ""))
        except: continue
        mult = {"cr":1e7,"crore":1e7,"crores":1e7,"lakh":1e5,"lakhs":1e5,"lac":1e5,"lacs":1e5,
                "mn":1e6,"million":1e6,"bn":1e9,"billion":1e9}.get(unit, 1e7)
        base = v * (mult if cur == "₹" else (1e6 if unit.startswith(("mn","mil")) else
               (1e9 if unit.startswith(("bn","bil")) else 1)))   # US$ base = dollars
        score = (3 if KEYS.search(ctx) else 0) + min(v*mult/1e7, 5)/5.0
        if score > best_score:
            best_score = score
            approx = "~" if ccy.startswith("~") else ""
            best = "%s%s %s %s" % (approx, cur, amt, "cr" if unit.startswith("cr") else
                   ("lakh" if unit.startswith(("lac","lakh")) else ("mn" if unit.startswith(("mn","mil")) else "bn")))
            best_cr = _inr_cr(base, cur)
    # 2) currency-prefixed full-digit amount (no unit word)
    for m in MONEY2.finditer(txt):
        ccy, amt = m.group(2), m.group(3)
        try: v = float(amt.replace(",", ""))
        except: continue
        if v < 100000: continue
        s, e = m.start(), m.end()
        # a bare "$" preceded by a letter is a FOREIGN dollar (GYD$, A$, S$, C$, HK$) — skip it,
        # so a parenthetical like "(35.42 Million USD)" wins instead of a huge GYD figure
        ds = m.start(2)
        if ccy == "$" and ds > 0 and txt[ds-1].isalpha() and txt[ds-2:ds].upper() != "US": continue
        ctx = txt[max(0, s-90):e+50]
        if NEG.search(ctx): continue
        score = 1.0 + (3 if KEYS.search(ctx) else 0)
        if re.search(r"\((?:Rupees|USD|US Dollars)\b", ctx, re.I): score += 1
        score += min(v/1e7, 5)/5.0
        if score > best_score:
            best_score = score
            cur = _cur_from(ccy)
            best = fmt_amt(v, "~" if m.group(1).strip() else "", cur)
            best_cr = _inr_cr(v, cur)
    # 3) numeric figure right before a spelled-out "(Rupees … )" / "(… Crore …)" clause
    for m in MONEY3.finditer(txt):
        try: v = float(m.group(2).replace(",", "").replace(" ", ""))
        except: continue
        if v < 100000: continue
        s, e = m.start(), m.end()
        if NEG.search(txt[max(0, s-90):e+10]): continue
        score = 4.0 + min(v/1e7, 5)/5.0
        if score > best_score:
            best_score = score
            best = fmt_amt(v, "~" if (m.group(1) or "").strip() else "", "₹")
            best_cr = round(v/1e7, 2)
    return (best, best_cr) if best else None

# ---- driver ----------------------------------------------------------------
def main():
    ann = json.load(open(ANN, encoding="utf-8"))
    order_files = {}                                    # file -> True (only order-win PDFs)
    for r in ann.get("rows", []):
        sym, co, dt, desc, cap, f = r
        if ORDER_RX.search(desc) and f and f.lower().endswith(".pdf"):
            order_files[f] = True

    cache = {}
    if os.path.exists(OUT):
        try: cache = json.load(open(OUT, encoding="utf-8")).get("vals", {})
        except Exception as ex: print("WARN cache unreadable:", ex)

    jar = None
    import fitz
    todo = [f for f in order_files if f not in cache]
    print("order PDFs: %d total, %d cached, %d to fetch" % (len(order_files), len(order_files) - len(todo), len(todo)))
    ok = miss = err = 0
    for i, f in enumerate(todo, 1):
        if jar is None: jar = B.nse_jar()
        try:
            raw = B._get(PREF + f, headers=HDR, jar=jar, timeout=60, binary=True)
            txt = "".join(p.get_text() for p in fitz.open(stream=raw, filetype="pdf"))
            val = extract(txt)
            if val:
                cache[f] = {"t": val[0], "cr": val[1]}; ok += 1   # display string + ₹ crore (or null)
                if i <= 60 or i % 10 == 0: print("  OK   %-55s %-14s %s" % (f[:55], val[0], val[1]))
            else:
                cache[f] = ""; miss += 1                 # remember "checked, no value" (avoids re-fetch)
        except Exception as ex:
            err += 1; print("  ERR  %-55s %s" % (f[:55], repr(ex)[:60]))
            # don't cache errors -> retried next run

    # prune entries whose file is no longer in the announcements window
    for f in [k for k in cache if k not in order_files]:
        del cache[f]

    import datetime
    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    json.dump({"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "vals": cache},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    have = sum(1 for v in cache.values() if v)
    print("WROTE %s: %d files, %d with a value (fetched OK %d / miss %d / err %d)" %
          (os.path.normpath(OUT), len(cache), have, ok, miss, err))

if __name__ == "__main__":
    main()
