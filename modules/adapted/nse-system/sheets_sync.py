import sys
import datetime as dt
import gspread
import db

KEY = "data/gcp_key.json"
SID_FILE = "data/sheet_id.txt"

def get_sh():
    gc = gspread.service_account(filename=KEY)
    with open(SID_FILE) as f:
        sid = f.read().strip()
    return gc.open_by_key(sid)

def write_tab(sh, title, header, rows):
    ws = None
    for w in sh.worksheets():
        if w.title == title:
            ws = w
    if ws is None:
        ws = sh.add_worksheet(title=title,
                              rows=max(len(rows) + 5, 20),
                              cols=len(header))
    ws.clear()
    ws.append_rows([header] + rows)
    return ws

def sync():
    conn = db.get_conn()
    sh = get_sh()

    q = ("SELECT r.symbol, s.name, s.sector, f.current_price, f.pe, "
         "f.roce, f.debt_to_equity, f.profit_growth_3y, "
         "r.fundamental_score, m.final_ml_score, COALESCE(p.status,'') "
         "FROM scan_results r "
         "JOIN stocks s ON s.symbol=r.symbol "
         "LEFT JOIN fundamentals f ON f.symbol=r.symbol "
         "LEFT JOIN ml_predictions m ON m.symbol=r.symbol "
         "AND m.prediction_date=(SELECT MAX(prediction_date) "
         "FROM ml_predictions) "
         "LEFT JOIN pipeline p ON p.symbol=r.symbol "
         "WHERE r.scan_date=(SELECT MAX(scan_date) FROM scan_results) "
         "ORDER BY r.fundamental_score DESC")
    rows = [list(r) for r in conn.execute(q).fetchall()]
    header = ["Symbol", "Name", "Sector", "Price", "PE", "ROCE", "D/E",
              "Profit3Y", "FundScore", "MLScore", "Status"]
    write_tab(sh, "Scores", header, rows)

    rec = [r for r in rows if r[10] == "Recommended"]
    write_tab(sh, "Recommended", header, rec)

    prows = [list(r) for r in conn.execute(
        "SELECT symbol, status, added_date, reason, notes "
        "FROM pipeline ORDER BY status").fetchall()]
    write_tab(sh, "Pipeline",
              ["Symbol", "Status", "Added", "Reason", "Notes"], prows)

    wsq = None
    for w in sh.worksheets():
        if w.title == "ResearchQueue":
            wsq = w
    if wsq is None:
        wsq = sh.add_worksheet(title="ResearchQueue", rows=100, cols=3)
        wsq.append_rows([["Symbol", "Note", "Processed"]])
    qrows = wsq.get_all_values()
    body = qrows[1:] if len(qrows) > 1 else []

    import sentiment
    new_body = []
    reports = []
    for r in body:
        while len(r) < 3:
            r.append("")
        sym = (r[0] or "").strip().upper()
        if sym and not r[2]:
            try:
                sentiment.score_symbol(sym)
            except Exception as e:
                print(sym, "sentiment failed:", e)
            srow = conn.execute(
                "SELECT sentiment_score FROM sentiment_results "
                "WHERE symbol=? ORDER BY created_at DESC LIMIT 1",
                (sym,)).fetchone()
            sent = srow[0] if srow else None
            frow = conn.execute(
                "SELECT fundamental_score FROM scan_results "
                "WHERE symbol=? AND scan_date=(SELECT MAX(scan_date) "
                "FROM scan_results)", (sym,)).fetchone()
            fund = frow[0] if frow else None
            mrow = conn.execute(
                "SELECT final_ml_score FROM ml_predictions "
                "WHERE symbol=? AND prediction_date=(SELECT "
                "MAX(prediction_date) FROM ml_predictions)",
                (sym,)).fetchone()
            ml = mrow[0] if mrow else None
            overall = None
            if fund is not None and sent is not None:
                overall = round(0.8 * fund + 0.2 * sent, 1)
            r[2] = dt.date.today().isoformat()
            reports.append([sym, r[2], fund, ml, sent, overall])
        new_body.append(r)
    if body or new_body:
        wsq.clear()
        wsq.append_rows([["Symbol", "Note", "Processed"]] + new_body)

    if reports:
        wsrep = None
        for w in sh.worksheets():
            if w.title == "Reports":
                wsrep = w
        if wsrep is None:
            wsrep = sh.add_worksheet(title="Reports", rows=200, cols=6)
        old = wsrep.get_all_values()[1:] if wsrep else []
        if wsrep is None:
            wsrep = sh.add_worksheet(title="Reports", rows=200, cols=6)
            old = []
        wsrep.clear()
        wsrep.append_rows([["Symbol", "Date", "Fund", "ML",
                            "Sentiment", "Overall"]] + old + reports)

    write_tab(sh, "SyncLog", ["Time", "Scores", "Recommended"],
              [[dt.datetime.now().isoformat(), len(rows), len(rec)]])
    print("Sheets synced:", len(rows), "scores |",
          len(rec), "recommended |", len(reports), "queue reports")
    conn.close()

if len(sys.argv) > 1 and sys.argv[1] == "run":
    sync()