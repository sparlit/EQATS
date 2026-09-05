import sys
import statistics
import db

BANK_KEYS = ["BANK", "FINANC", "NBFC"]

def is_financial(sector):
    s = (sector or "").upper()
    for k in BANK_KEYS:
        if k in s:
            return True
    return False

def band_high(value, stops):
    if value is None:
        return None
    for minv, score in stops:
        if value >= minv:
            return score
    return 5

def band_low(value, stops):
    if value is None:
        return None
    for maxv, score in stops:
        if value <= maxv:
            return score
    return 5

ROCE_STOPS = [(30, 98), (25, 92), (22, 85), (19, 78), (16, 70),
              (13, 60), (10, 50), (7, 40), (4, 25), (0, 10)]
PROFIT_STOPS = [(30, 98), (22, 90), (17, 80), (12, 70), (8, 60),
                (4, 50), (0, 40), (-5, 30), (-15, 15)]
SALES_STOPS = [(25, 98), (18, 90), (13, 80), (9, 70), (5, 60),
               (2, 50), (0, 40), (-5, 25), (-10, 10)]
PE_RATIO_STOPS = [(0.7, 98), (0.85, 90), (1.0, 80), (1.15, 70),
                  (1.3, 60), (1.5, 50), (1.8, 40), (2.2, 30), (3.0, 15)]
PEG_STOPS = [(0.7, 98), (1.0, 90), (1.3, 80), (1.7, 70),
             (2.2, 60), (3.0, 50), (5.0, 30)]

def sector_pe_medians(conn):
    q = ("SELECT s.sector, f.pe FROM fundamentals f "
         "JOIN stocks s ON s.symbol=f.symbol "
         "WHERE f.pe IS NOT NULL AND f.pe>0 "
         "AND s.sector IS NOT NULL")
    rows = conn.execute(q).fetchall()
    by = {}
    for sec, pe in rows:
        by.setdefault(sec, []).append(pe)
    out = {}
    for sec, vals in by.items():
        out[sec] = statistics.median(vals)
    return out

def price_stats(conn, symbol):
    q1 = ("SELECT close FROM prices_daily "
          "WHERE symbol=? ORDER BY date DESC LIMIT 1")
    q2 = ("SELECT AVG(close) FROM (SELECT close FROM prices_daily "
          "WHERE symbol=? ORDER BY date DESC LIMIT 200)")
    q3 = ("SELECT AVG(close*volume) FROM (SELECT close,volume "
          "FROM prices_daily "
          "WHERE symbol=? ORDER BY date DESC LIMIT 20)")
    price = conn.execute(q1, (symbol,)).fetchone()[0]
    dma200 = conn.execute(q2, (symbol,)).fetchone()[0]
    liq = conn.execute(q3, (symbol,)).fetchone()[0]
    return price, dma200, liq

def score_stock(conn, symbol, medians):
    f = conn.execute(
        "SELECT * FROM fundamentals WHERE symbol=?", (symbol,)).fetchone()
    if f is None:
        return None
    cols = [c[1] for c in conn.execute("PRAGMA table_info(fundamentals)")]
    m = dict(zip(cols, f))
    srow = conn.execute(
        "SELECT sector FROM stocks WHERE symbol=?", (symbol,)).fetchone()
    sector = srow[0] if srow else None
    price, dma200, liq = price_stats(conn, symbol)

    gates = []

    de = m.get("debt_to_equity")
    if is_financial(sector):
        gates.append(("G1 Debt/Equity", True, de, "skipped (financial)",
                      "Pass: bank/NBFC, debt rule skipped"))
    elif de is None:
        gates.append(("G1 Debt/Equity", False, None, "<=1.5",
                      "FAIL: debt data missing"))
    else:
        ok = de <= 1.5
        msg = "Pass" if ok else "FAIL: D/E above 1.5"
        gates.append(("G1 Debt/Equity", ok, de, "<=1.5", msg))

    pl = m.get("pledge_pct")
    if pl is None:
        gates.append(("G2 Pledge", True, None, "<=5 (if data)",
                      "Pass: no pledge data yet"))
    else:
        ok = pl <= 5
        msg = "Pass" if ok else "FAIL: pledge above 5%"
        gates.append(("G2 Pledge", ok, pl, "<=5", msg))

    cfo = m.get("cfo_positive")
    if is_financial(sector):
        gates.append(("G3 CFO positive", True, cfo, "skipped (financial)",
                      "Pass: bank/NBFC, CFO rule skipped"))
    elif cfo is None:
        gates.append(("G3 CFO positive", False, None, "=1",
                      "FAIL: cash flow data missing"))
    else:
        ok = cfo == 1
        msg = "Pass" if ok else "FAIL: negative operating cash flow"
        gates.append(("G3 CFO positive", ok, cfo, "=1", msg))

    if liq is None:
        gates.append(("G4 Liquidity", False, None, ">=2cr",
                      "FAIL: no price data"))
    else:
        ok = liq >= 20000000
        msg = "Pass" if ok else "FAIL: low liquidity"
        gates.append(("G4 Liquidity", ok, liq, ">=2cr", msg))

    roce_s = band_high(m.get("roce"), ROCE_STOPS)
    pg = m.get("profit_growth_3y")
    sg = m.get("sales_growth_3y")
    pg_s = band_high(pg, PROFIT_STOPS)
    sg_s = band_high(sg, SALES_STOPS)
    growth_s = None
    if pg_s is not None and sg_s is not None:
        growth_s = round(0.7 * pg_s + 0.3 * sg_s, 1)
    elif pg_s is not None:
        growth_s = pg_s

    pe = m.get("pe")
    med = medians.get(sector)
    pe_ratio = None
    if pe is not None and pe > 0 and med:
        pe_ratio = pe / med
    pe_s = band_low(pe_ratio, PE_RATIO_STOPS)

    peg = None
    if pe is not None and pe > 0 and pg is not None and pg > 0:
        peg = pe / pg
    peg_s = None
    if peg is not None:
        peg_s = band_low(peg, PEG_STOPS)
    elif pg is not None and pg <= 0:
        peg_s = 5

    val_parts = []
    if pe_s is not None:
        val_parts.append(pe_s)
    if peg_s is not None:
        val_parts.append(peg_s)
    val_s = None
    if val_parts:
        val_s = round(sum(val_parts) / len(val_parts), 1)

    bands = [("ROCE", roce_s, 40),
             ("Growth", growth_s, 30),
             ("Valuation", val_s, 30)]
    total_w = 0
    total_s = 0
    for name, sc, w in bands:
        if sc is not None:
            total_w += w
            total_s += sc * w
    composite = None
    if total_w > 0:
        composite = round(total_s / total_w, 1)
    incomplete = False
    for name, sc, w in bands:
        if sc is None:
            incomplete = True

    above200 = None
    if price is not None and dma200 is not None:
        above200 = price > dma200

    return {"symbol": symbol, "sector": sector, "price": price,
            "dma200": dma200, "liquidity": liq, "gates": gates,
            "roce_s": roce_s, "growth_s": growth_s, "val_s": val_s,
            "composite": composite, "incomplete": incomplete,
            "above200": above200}

if len(sys.argv) > 1 and sys.argv[1] == "test":
    c = db.get_conn()
    r = score_stock(c, "RELIANCE", sector_pe_medians(c))
    print(r)