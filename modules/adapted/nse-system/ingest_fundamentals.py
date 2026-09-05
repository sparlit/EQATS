import sys
import datetime as dt
import pandas as pd
import db

NUMERIC = ["current_price", "market_cap_cr", "pe", "pb", "roe", "roce",
           "debt_to_equity", "interest_coverage", "operating_margin",
           "net_profit_margin", "sales_growth_3y", "profit_growth_3y",
           "promoter_holding", "pledge_pct", "fii_holding", "dividend_yield"]

def load(path):
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "symbol" not in df.columns:
        print("CSV must have a 'symbol' column")
        return
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    conn = db.get_conn()
    now = "csv:" + dt.datetime.now().isoformat()
    n = 0
    for _, r in df.iterrows():
        sym = str(r["symbol"]).strip().upper()
        if not sym:
            continue
        conn.execute("DELETE FROM fundamentals WHERE symbol=?", (sym,))
        conn.execute(
            "INSERT INTO fundamentals VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sym, r.get("name"), r.get("sector"), r.get("current_price"),
             r.get("market_cap_cr"), r.get("pe"), r.get("pb"), r.get("roe"),
             r.get("roce"), r.get("debt_to_equity"),
             r.get("interest_coverage"), r.get("operating_margin"),
             r.get("net_profit_margin"), r.get("sales_growth_3y"),
             r.get("profit_growth_3y"), r.get("promoter_holding"),
             r.get("pledge_pct"), r.get("fii_holding"),
             r.get("dividend_yield"), r.get("cfo_positive"), now))
        n += 1
    conn.commit()
    print(f"Fundamentals CSV loaded: {n} stocks (overrides computed)")
    conn.close()

if len(sys.argv) > 1:
    load(sys.argv[1])