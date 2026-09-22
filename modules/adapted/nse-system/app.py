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


import db
import pandas as pd
import streamlit as st

st.set_page_config(page_title="NSE Intelligence 2.0", layout="wide", page_icon="📈")

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
<style>
html, body, [class*="stApp"] {font-family: 'Inter', sans-serif;}
header, #MainMenu, footer {visibility: hidden;}
.stApp {
  background:
    radial-gradient(1200px 600px at 85% -10%, #14315433, transparent),
    radial-gradient(900px 500px at -10% 110%, #0f3d3322, transparent),
    #0a0f1c;}
.kcard {
  background: linear-gradient(160deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
  border: 1px solid rgba(255,255,255,0.08); border-radius: 18px;
  padding: 16px 20px; margin-bottom: 12px;
  backdrop-filter: blur(8px);
  transition: transform .15s ease, border-color .15s ease;}
.kcard:hover {transform: translateY(-2px); border-color: rgba(96,165,250,0.35);}
.ktitle {font-size: 11px; letter-spacing: 1.6px; color: #7f93b8;
  text-transform: uppercase; font-weight: 600;}
.kvalue {font-size: 26px; font-weight: 800; color: #f4f7fc; margin-top: 4px;
  letter-spacing: -0.5px;}
.ksub {font-size: 12px; color: #6d7fa3; margin-top: 3px;}
.hero {font-size: 32px; font-weight: 800; letter-spacing: -1px;
  background: linear-gradient(90deg,#60a5fa,#34d399);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;}
.pill {padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 700;}
.evrow {padding: 10px 14px; border-radius: 14px;
  background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.05);
  margin-bottom: 6px; font-size: 14px; color: #dbe4f3;}
.stButton>button {
  background: rgba(255,255,255,0.05); color: #e5ecf8;
  border: 1px solid rgba(255,255,255,0.1); border-radius: 12px;
  font-weight: 600; transition: all .15s ease;}
.stButton>button:hover {background: rgba(96,165,250,0.15);
  border-color: rgba(96,165,250,0.5); color: #fff;}
@media (max-width: 640px) {
  .kvalue {font-size: 20px;} .hero {font-size: 24px;}
  .evrow {font-size: 13px;}
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

COLORS = {
    "Recommended": "#22c55e",
    "Passed Scan": "#3b82f6",
    "Watchlisted": "#eab308",
    "Invested": "#a855f7",
    "Review": "#f97316",
    "Discarded": "#ef4444",
}
EV_ICON = {
    "CROSS_UP_200": "🟢",
    "CROSS_DOWN_200": "🔻",
    "VOL_SPIKE": "⚡",
    "NEW_52W_HIGH": "🏔️",
    "GOLDEN_CROSS": "✨",
    "DEATH_CROSS": "💀",
    "OVERBOUGHT": "🔥",
    "OVERSOLD": "🧊",
    "NEW_RECOMMENDED": "⭐",
}


def pill(status):
    c = COLORS.get(status, "#64748b")
    return f'<span class="pill" style="background:{c}22;color:{c};border:1px solid {c}55">{status}</span>'


def card(title, value, sub=""):
    st.markdown(
        f'<div class="kcard"><div class="ktitle">{title}</div>'
        f'<div class="kvalue">{value}</div>'
        f'<div class="ksub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def goto(sym):
    st.session_state["pending_nav"] = "🛩️ Cockpit"
    st.session_state["pending_sym"] = sym
    st.rerun()


def ml_explain(conn, sym):
    import numpy as np

    rows = conn.execute("SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 300", (sym,)).fetchall()
    rows = [r for r in rows if r[0] is not None]
    if len(rows) < 252:
        return None
    c = np.array([r[0] for r in reversed(rows)])
    vals = [
        c[-1] / c[-21] - 1,
        c[-1] / c[-63] - 1,
        c[-1] / c[-126] - 1,
        c[-1] / c[-252] - 1,
        float(np.std(np.diff(np.log(c))[-63:])),
        c[-1] / float(np.max(c[-252:])),
        c[-1] / float(np.min(c[-252:])),
        1 if c[-1] > np.mean(c[-50:]) else 0,
        1 if c[-1] > np.mean(c[-200:]) else 0,
    ]
    labels = [
        "1-month momentum",
        "3-month momentum",
        "6-month momentum",
        "12-month momentum",
        "3-month volatility",
        "vs 52-week high",
        "vs 52-week low",
        "Above 50-day average",
        "Above 200-day average",
    ]
    return list(zip(labels, vals, strict=False))


conn = db.get_conn()
conn.execute("CREATE TABLE IF NOT EXISTS events(date TEXT, symbol TEXT, kind TEXT, text TEXT)")
PAGES = ["📡 Radar", "🏄 Swing Desk", "🛩️ Cockpit", "💼 My Desk", "⚙️ System"]

with st.sidebar.expander("❓ How to use this system"):
    st.write("1. Daily: System → RUN DAILY UPDATE (or auto at 4:30)")
    st.write("2. Radar: click anything interesting → Cockpit opens")
    st.write("3. Cockpit: fetch news, read red flags, swing plan")
    st.write("4. ⭐ star stocks to build your desk")

if st.session_state.get("pending_nav"):
    st.session_state["nav"] = st.session_state.pop("pending_nav")
_ps = st.session_state.pop("pending_sym", None)
if _ps:
    st.session_state["cockpit_sym"] = _ps
choice = st.sidebar.radio("Navigation", PAGES, key="nav")

if choice == "📡 Radar":
    st.markdown('<div class="hero">RADAR — nothing moves unseen</div>', unsafe_allow_html=True)
    nb = conn.execute("SELECT COUNT(*) FROM universe_broad").fetchone()[0]
    nrec = conn.execute("SELECT COUNT(*) FROM pipeline WHERE status='Recommended'").fetchone()[0]
    nev = conn.execute("SELECT COUNT(*) FROM events WHERE date=(SELECT MAX(date) FROM events)").fetchone()[0]
    a, b, c = st.columns(3)
    with a:
        card("Stocks on radar", nb, "mcap ≥ ₹1,000 cr")
    with b:
        card("Recommended", nrec)
    with c:
        card("Events latest day", nev)

    import broad_scan

    rows = conn.execute("SELECT symbol, perf1m, perf3m, relvol, mcap_cr FROM universe_broad").fetchall()
    groups = {"TURN": [], "VOL": [], "MOM": []}
    for sym, p1, p3, rv, mc in rows:
        tag = broad_scan.classify(p1, p3, rv)
        if tag:
            groups[tag].append((sym, p1 or 0, rv, mc or 0))
    sections = [
        ("🌅 Waking up — reversals before inflation", "TURN"),
        ("⚡ Volume spikes", "VOL"),
        ("🏃 In motion — strong continuation", "MOM"),
    ]
    for title, tag in sections:
        lst = groups[tag]
        lst.sort(key=lambda x: -x[1])
        if not lst:
            continue
        st.subheader(f"{title} ({len(lst)})")
        cols = st.columns(2)
        for i, (sym, p1, rv, mc) in enumerate(lst[:20]):
            rvs = f" · {rv:.1f}x vol" if rv else ""
            with cols[i % 2]:
                if st.button(f"{sym}  1M {p1:+.1f}%{rvs}  ₹{mc:.0f}cr", key=tag + sym):
                    goto(sym)

    if st.button("🎯 Show top swing setups"):
        import swing

        with st.spinner("Scanning swings (≈10s)..."):
            st.session_state["swing_tops"] = swing.scan_top(15)
    for r in st.session_state.get("swing_tops", []):
        c1, c2 = st.columns([1, 5])
        with c1:
            if st.button(r["symbol"], key="sw" + r["symbol"]):
                goto(r["symbol"])
        with c2:
            st.markdown(
                f'<div class="evrow">score <b>{r["score"]}</b> · '
                f"entry {r['entry'][0]:.2f}–{r['entry'][1]:.2f} · "
                f"stop {r['stop']:.2f} · target {r['target']:.2f} · "
                f"R:R {r['rr']} · {' ; '.join(r['notes'])}</div>",
                unsafe_allow_html=True,
            )

    st.subheader("😴 Sleeping giants")
    q = (
        "SELECT r.symbol, r.fundamental_score FROM scan_results r "
        "JOIN technicals_daily t ON t.symbol=r.symbol AND "
        "t.date=(SELECT MAX(date) FROM technicals_daily) "
        "WHERE r.scan_date=(SELECT MAX(scan_date) FROM scan_results) "
        "AND t.above200=0 AND r.fundamental_score>=70 "
        "ORDER BY r.fundamental_score DESC LIMIT 12"
    )
    for r in conn.execute(q):
        if st.button(f"{r[0]}  fund {r[1]:.0f} (dormant)", key="sl" + r[0]):
            goto(r[0])

    st.subheader("⚡ Latest events")
    ev = conn.execute(
        "SELECT kind, symbol, text FROM events WHERE date=(SELECT MAX(date) FROM events) LIMIT 15"
    ).fetchall()
    for kind, sym, text in ev:
        c1, c2 = st.columns([1, 6])
        with c1:
            if st.button(sym, key="ev" + sym + kind):
                goto(sym)
        with c2:
            st.markdown(f'<div class="evrow">{EV_ICON.get(kind, "•")} {text}</div>', unsafe_allow_html=True)

elif choice == "🏄 Swing Desk":
    import time as _time

    import swing_live

    swing_live.ensure(conn)
    st.markdown('<div class="hero">SWING DESK — Gabani pullback, live</div>', unsafe_allow_html=True)
    rc = st.session_state.get("regime_cache")
    if rc is None or (_time.time() - rc[0]) > 3600:
        try:
            from regime import MarketRegime

            rg = MarketRegime.compute()
            rc = (_time.time(), rg.is_bullish, rg.index_close, rg.ema10, rg.symbol)
        except Exception:
            rc = (0, None, 0, 0, "")
        st.session_state["regime_cache"] = rc
    if rc[1] is True:
        st.markdown(
            f'<div class="evrow">🟢 REGIME BULLISH — {rc[4]} '
            f"close {rc[2]:,.0f} > EMA10 {rc[3]:,.0f} — new "
            f"entries ALLOWED</div>",
            unsafe_allow_html=True,
        )
    elif rc[1] is False:
        st.markdown(
            f'<div class="evrow">🛑 REGIME DEFENSIVE — {rc[4]} '
            f"close {rc[2]:,.0f} < EMA10 {rc[3]:,.0f} — NO new "
            f"entries, manage open only</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="evrow">⚠️ regime unavailable (offline)</div>', unsafe_allow_html=True)
    if st.button("🔁 Run EOD swing scan now"):
        with st.spinner("Grading + scanning..."):
            swing_live.update_outcomes()
            swing_live.scan()
        st.rerun()
    sc = pd.read_sql("SELECT outcome, COUNT(*) AS n FROM swing_signals GROUP BY outcome", conn)
    counts = dict(zip(sc["outcome"], sc["n"], strict=False))
    total = int(sum(counts.values()))
    wins = int(counts.get("WIN", 0))
    losses = int(counts.get("LOSS", 0))
    graded = wins + losses
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Signals", total)
    with c2:
        card("Wins", wins)
    with c3:
        card("Losses", losses)
    with c4:
        card("Win rate", f"{100 * wins / graded:.0f}%" if graded else "—")
    hist = pd.read_sql(
        "SELECT signal_date, symbol, entry_trigger, stop, target, "
        "risk_pct, outcome FROM swing_signals "
        "ORDER BY signal_date DESC LIMIT 60",
        conn,
    )
    if len(hist):
        st.subheader("Signal log (forward validation)")
        st.dataframe(hist, width="stretch")
        st.subheader("Jump to a stock")
        for _, r in hist.head(10).iterrows():
            if st.button(
                f"{r['symbol']} · {r['signal_date']} · {r['outcome']}",
                key="sg" + str(r["symbol"]) + str(r["signal_date"]),
            ):
                goto(r["symbol"])
    else:
        st.info("No signals yet — run the EOD scan; bullish days produce setups here.")
elif choice == "🛩️ Cockpit":
    st.markdown('<div class="hero">COCKPIT</div>', unsafe_allow_html=True)
    sym = st.text_input("Symbol", value=st.session_state.get("cockpit_sym", "RELIANCE")).upper()
    st.session_state["cockpit_sym"] = sym
    import deepdive

    havep = conn.execute("SELECT COUNT(*) FROM prices_daily WHERE symbol=?", (sym,)).fetchone()[0]
    havef = conn.execute("SELECT COUNT(*) FROM fundamentals WHERE symbol=?", (sym,)).fetchone()[0]
    if (havep < 100 or havef == 0) and st.session_state.get("dive_fail") != sym:
        with st.spinner(f"First-time deep dive for {sym}..."):
            ok = deepdive.ensure_symbol(sym)
        if not ok:
            st.session_state["dive_fail"] = sym
            st.warning(f"No data found for {sym} on Yahoo.")
    prow = conn.execute("SELECT status FROM pipeline WHERE symbol=?", (sym,)).fetchone()
    sec = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (sym,)).fetchone()
    mcr = conn.execute("SELECT mcap_cr FROM universe_broad WHERE symbol=?", (sym,)).fetchone()
    if mcr is None:
        mcr = conn.execute("SELECT market_cap_cr FROM fundamentals WHERE symbol=?", (sym,)).fetchone()
    head = sym
    if sec and sec[0]:
        head += f" · {sec[0]}"
    if mcr and mcr[0]:
        head += f" · ₹{mcr[0]:,.0f} cr"
    st.markdown(f"<h3>{head} &nbsp; {pill(prow[0]) if prow else ''}</h3>", unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🔄 Fetch news + corporate data", type="primary"):
            import corporate
            import sentiment

            with st.spinner("Reading news & filings..."):
                sentiment.score_symbol(sym)
                corporate.fetch_calendar(sym)
            st.rerun()
    with b2:
        if st.button("⭐ Add to Watchlist"):
            import datetime as dt

            now = dt.datetime.now().isoformat()
            conn.execute(
                "INSERT INTO pipeline(symbol,status,added_date,"
                "updated_date,reason) VALUES(?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET "
                "status='Watchlisted', "
                "updated_date=excluded.updated_date",
                (sym, "Watchlisted", now, now, "Manual star"),
            )
            conn.commit()
            st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Positional (fundamentals)")
        fr = conn.execute(
            "SELECT fundamental_score FROM scan_results "
            "WHERE symbol=? AND scan_date=(SELECT MAX(scan_date) "
            "FROM scan_results)",
            (sym,),
        ).fetchone()
        card("Fund score", f"{fr[0]:.0f}" if fr else "—", "40% ROCE + 30% growth + 30% valuation vs sector")
        with st.expander("Why this score?"):
            rs = pd.read_sql(
                "SELECT rule_name, passed, reason_text "
                "FROM scan_reasons WHERE symbol=? AND scan_date="
                "(SELECT MAX(scan_date) FROM scan_reasons)",
                conn,
                params=[sym],
            )
            st.dataframe(rs, width="stretch")
    with c2:
        st.subheader("Swing setup (2d–3w)")
        import swing

        sw = swing.swing(sym)
        if sw:
            card("Swing score", sw["score"], " ; ".join(sw["notes"]))
            st.markdown(
                f'<div class="evrow">Entry ₹{sw["entry"][0]:.2f}–'
                f"{sw['entry'][1]:.2f} · Stop ₹{sw['stop']:.2f} · "
                f"Target ₹{sw['target']:.2f} · R:R {sw['rr']} · "
                f"ATR {sw['atr_pct']}%</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("Not enough history.")
    with c3:
        st.subheader("Machine learning")
        mr = conn.execute(
            "SELECT final_ml_score, ml_score_6m, ml_score_12m "
            "FROM ml_predictions WHERE symbol=? ORDER BY "
            "prediction_date DESC LIMIT 1",
            (sym,),
        ).fetchone()
        if mr:
            card("ML score", f"{mr[0]:.0f}", f"6M {mr[1]:.0f}% · 12M {mr[2]:.0f}% outperform")
            with st.expander("What the model saw"):
                fx = ml_explain(conn, sym)
                if fx:
                    for label, v in fx:
                        if "Above" in label:
                            txt = "Yes" if v else "No"
                        elif "volatility" in label or "momentum" in label:
                            txt = f"{v * 100:.2f}%"
                        else:
                            txt = f"{v * 100:.2f}% of price"
                        st.markdown(f'<div class="evrow">{label}: <b>{txt}</b></div>', unsafe_allow_html=True)
                else:
                    st.info("Not enough history.")
        else:
            st.info("No ML prediction.")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Price + EMA21 + 200DMA")
        ph = pd.read_sql("SELECT date, close FROM prices_daily WHERE symbol=? ORDER BY date", conn, params=[sym])
        if len(ph) > 0:
            import plotly.graph_objects as go

            ph["e21"] = ph["close"].ewm(span=21).mean()
            ph["d200"] = ph["close"].rolling(200).mean()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ph.date, y=ph.close, name="Close", line={"color": "#60a5fa"}))
            fig.add_trace(go.Scatter(x=ph.date, y=ph.e21, name="EMA21", line={"color": "#34d399"}))
            fig.add_trace(go.Scatter(x=ph.date, y=ph.d200, name="200DMA", line={"color": "#f59e0b", "dash": "dot"}))
            fig.update_layout(template="plotly_dark", height=400, margin={"l": 10, "r": 10, "t": 20, "b": 10})
            st.plotly_chart(fig, width="stretch")
        st.subheader("📰 News feed (FinBERT)")
        hl = conn.execute(
            "SELECT title, age_days, label FROM sentiment_headlines WHERE symbol=? ORDER BY age_days LIMIT 12", (sym,)
        ).fetchall()
        if hl:
            icon = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}
            for title, age, label in hl:
                st.markdown(
                    f'<div class="evrow">{icon.get(label, "⚪")} [{age}d] {title}</div>', unsafe_allow_html=True
                )
        else:
            st.info("Press the fetch button above.")
    with right:
        st.subheader("🚩 Red flags")
        import corporate

        fl = corporate.red_flags(conn, sym)
        if fl:
            for f in fl:
                st.markdown(f'<div class="evrow">🚩 {f}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="evrow">✅ no red flags</div>', unsafe_allow_html=True)
        st.subheader("📅 Corporate calendar")
        ce = conn.execute(
            "SELECT event_date, kind, detail FROM corp_calendar "
            "WHERE symbol=? AND event_date>=date('now') "
            "ORDER BY event_date LIMIT 6",
            (sym,),
        ).fetchall()
        if ce:
            for d, k, det in ce:
                st.markdown(f'<div class="evrow">📅 {d} — {k} {det}</div>', unsafe_allow_html=True)
        else:
            st.info("No upcoming events stored.")
        st.subheader("Fundamentals")
        import guide
        import scoring

        cols = [c[1] for c in conn.execute("PRAGMA table_info(fundamentals)")]
        row = conn.execute("SELECT * FROM fundamentals WHERE symbol=?", (sym,)).fetchone()
        if row:
            m = dict(zip(cols, row, strict=False))
            srow2 = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (sym,)).fetchone()
            sector = srow2[0] if srow2 else None
            med = scoring.sector_pe_medians(conn).get(sector)
            for label, val, ideal, ok in guide.fund_rows(m, sector, med):
                icon = "✅" if ok else ("➖" if val is None else "⚠️")
                unit = "%" if any(k in label for k in ["growth", "ROE", "ROCE", "Pledge", "Promoter"]) else ""
                vals = f"{val}{unit}" if val is not None else "—"
                note = ""
                if val is None and ("Pledge" in label or "Promoter" in label):
                    note = ' <span style="color:#7c8db0">(add via CSV in System)</span>'
                st.markdown(
                    f'<div class="evrow">{icon} <b>{label}</b>: '
                    f'{vals} <span style="color:#7c8db0">| ideal: '
                    f"{ideal}</span>{note}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("No fundamentals stored.")

elif choice == "💼 My Desk":
    st.markdown('<div class="hero">MY DESK</div>', unsafe_allow_html=True)
    q = (
        "SELECT p.symbol, p.status, p.reason, p.notes, "
        "(SELECT r.fundamental_score FROM scan_results r "
        "WHERE r.symbol=p.symbol ORDER BY r.scan_date DESC LIMIT 1) "
        "FROM pipeline p ORDER BY 5 DESC"
    )
    df = pd.read_sql(q, conn)
    for status in COLORS:
        part = df[df["status"] == status]
        if len(part) == 0:
            continue
        st.markdown(f"{pill(status)} &nbsp; <b>{len(part)}</b>", unsafe_allow_html=True)
        for _, r in part.head(20).iterrows():
            if st.button(f"{r['symbol']}  fund {r[4] or 0:.0f}", key="dk" + r["symbol"] + status):
                goto(r["symbol"])
    st.subheader("Add / change")
    nsym = st.text_input("Symbol", "").upper()
    nstat = st.selectbox("Status", list(COLORS.keys()))
    nnotes = st.text_area("Notes")
    if st.button("Save", type="primary") and nsym:
        import datetime as dt

        now = dt.datetime.now().isoformat()
        conn.execute(
            "INSERT INTO pipeline(symbol,status,added_date,"
            "updated_date,notes) VALUES(?,?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET status=excluded.status,"
            "updated_date=excluded.updated_date,notes=excluded.notes",
            (nsym, nstat, now, now, nnotes),
        )
        conn.commit()
        st.rerun()

else:
    st.markdown('<div class="hero">SYSTEM</div>', unsafe_allow_html=True)
    if st.button("🚀 RUN DAILY UPDATE", type="primary"):
        import daily_update

        with st.spinner("Full pipeline (3–6 min)..."):
            daily_update.run()
        st.success("Done")
        st.rerun()
    if st.button("🌙 Weekly refresh (retrain + scan + Telegram)"):
        import ml_train
        import scan
        import telegram_alerts

        with st.spinner("Retraining + scanning..."):
            ml_train.train()
            scan.run()
            telegram_alerts.report()
        st.success("Weekly refresh done")
        st.rerun()
    a, b = st.columns(2)
    with a:
        if st.button("Broad radar refresh"):
            import broad_scan

            with st.spinner("Scanning whole market..."):
                broad_scan.run()
            st.success("Radar refreshed")
            st.rerun()
    with b:
        up = st.file_uploader("Fundamentals CSV", type=["csv"])
        if up is not None:
            with open("data/uploaded_fundamentals.csv", "wb") as f:
                f.write(up.getbuffer())
            if st.button("Load CSV"):
                import ingest_fundamentals

                ingest_fundamentals.load("data/uploaded_fundamentals.csv")
                st.rerun()
    st.subheader("Benchmarks (v2)")
    x, y, z = st.columns(3)
    with x:
        card("Gates", "4 rules", "D/E≤1.5 · Pledge≤5 · CFO+ · Liq≥2cr")
    with y:
        card("Bands", "40/30/30", "ROCE · Growth · Valuation")
    with z:
        card("Recommend", "top-25", "fund≥65 + ML≥55 + above 200DMA")
    st.subheader("Alerts")
    if st.button("Telegram test"):
        import telegram_alerts

        telegram_alerts.send("✅ test")
    if st.button("Telegram report now"):
        import telegram_alerts

        telegram_alerts.report()
        st.success("Sent")
