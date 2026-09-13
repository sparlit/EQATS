from __future__ import annotations

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
"""
Local end-to-end test for the PEAD system.
Fetches NSE announcements for a given date, runs the full pipeline
(QoQ/YoY metrics → Claude → Telegram) without any AWS infrastructure.

Usage:
    python scripts/test_pead_local.py --date 09-05-2026
    python scripts/test_pead_local.py --date 09-05-2026 --symbol HDFCBANK
    python scripts/test_pead_local.py --date 09-05-2026 --no-telegram   # skip sending
"""


import argparse
import contextlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import anthropic
import psycopg2
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load env
for _c in ["web/.env", ".env"]:
    if os.path.exists(_c):
        load_dotenv(_c)
        break

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

NSE_API = "https://www.nseindia.com/api/corporate-announcements"
IST = timezone(timedelta(hours=5, minutes=30))

RESULT_KEYWORDS = [
    "financial result",
    "quarterly result",
    "unaudited result",
    "audited result",
    "half yearly result",
    "annual result",
]

# These are secondary filings referencing already-announced results — skip them
EXCLUDE_CATEGORIES = [
    "copy of newspaper publication",
    "clarification - financial results",
    "reply to clarification",
    "analysts/institutional investor meet",
    "corporate insolvency",
    "general updates",
]

# Preference order when a company files multiple announcements on the same day
CATEGORY_PRIORITY = {
    "outcome of board meeting": 0,
    "press release": 1,
    "updates": 2,
}

MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


# ── helpers ───────────────────────────────────────────────────────────────────


def clean_db_url(url: str) -> str:
    return re.sub(r'sslmode=["\']?(\w+)["\']?', r"sslmode=\1", url.strip())


def is_result(ann: dict) -> bool:
    cat = ann.get("desc", "").lower()
    if any(excl in cat for excl in EXCLUDE_CATEGORIES):
        return False
    # Outcome of Board Meeting is always a result filing for calendar companies
    if "outcome of board meeting" in cat:
        return True
    text = (ann.get("desc", "") + " " + ann.get("attchmntText", "")).lower()
    return any(kw in text for kw in RESULT_KEYWORDS)


def deduplicate(results: list[dict]) -> list[dict]:
    """One alert per symbol — prefer Outcome of Board Meeting > Press Release > others."""
    best: dict[str, tuple[dict, int]] = {}
    for ann in results:
        sym = ann["symbol"]
        pri = CATEGORY_PRIORITY.get(ann.get("desc", "").lower(), 99)
        if sym not in best or pri < best[sym][1]:
            best[sym] = (ann, pri)
    return [v for v, _ in best.values()]


def parse_nse_dt(s: str) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    return None


def _parse_number(text: str) -> float | None:
    if not text:
        return None
    cleaned = text.strip().replace(",", "").replace("%", "").replace("\xa0", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


# ── Step 1: NSE announcements ─────────────────────────────────────────────────


def fetch_nse_announcements(date_str: str) -> list[dict]:
    """date_str in DD-MM-YYYY format."""
    print(f"\n{'=' * 60}")
    print(f"STEP 1 — Fetching NSE announcements for {date_str}")
    print("=" * 60)

    resp = requests.get(
        NSE_API,
        params={"index": "equities", "from_date": date_str, "to_date": date_str},
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        },
        timeout=20,
    )
    print(f"HTTP {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    all_anns = data if isinstance(data, list) else []
    results = deduplicate([a for a in all_anns if is_result(a)])

    print(f"Total announcements : {len(all_anns)}")
    print(f"Result announcements: {len(results)} (after dedup)")

    for r in results:
        ann_dt = parse_nse_dt(r.get("an_dt", ""))
        print(
            f"  [{r.get('seq_id')}] {r['symbol']:15s} | "
            f"{ann_dt.strftime('%H:%M:%S') if ann_dt else '?'} IST | "
            f"{r.get('desc', '')[:60]}"
        )

    return results


# ── Step 2: Screener.in — current quarter ─────────────────────────────────────


def screener_login() -> requests.Session | None:
    username = os.environ.get("SCREENER_USERNAME")
    password = os.environ.get("SCREENER_PASSWORD")
    if not username or not password:
        print("  ⚠ SCREENER_USERNAME/PASSWORD not set")
        return None

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    r = s.get("https://www.screener.in/login/", timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    csrf = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if not csrf:
        print("  ✗ Could not get CSRF token")
        return None

    r = s.post(
        "https://www.screener.in/login/",
        data={
            "csrfmiddlewaretoken": csrf["value"],
            "username": username,
            "password": password,
            "next": "/",
        },
        headers={"Referer": "https://www.screener.in/login/"},
        timeout=15,
        allow_redirects=True,
    )

    if "/login/" in r.url:
        print("  ✗ Screener login failed")
        return None

    print("  ✓ Screener login OK")
    return s


def fetch_screener_quarter(session: requests.Session, symbol: str) -> dict | None:
    for suffix in ("/consolidated/", "/"):
        r = session.get(f"https://www.screener.in/company/{symbol}{suffix}", timeout=20)
        if r.ok:
            break
    if not r.ok:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    section = soup.find("section", id="quarters")
    if not section:
        return None
    table = section.find("table")
    if not table:
        return None

    thead = table.find("thead")
    headers = [th.get_text(strip=True) for th in thead.find_all("th")] if thead else []
    if len(headers) < 2:
        return None

    data: dict = {"quarter_label": headers[1]}

    for row in table.find("tbody").find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        metric = cells[0].get_text(strip=True).lower()
        val = _parse_number(cells[1].get_text(strip=True))
        if val is None:
            continue
        if "sales" in metric or ("revenue" in metric and "other" not in metric):
            data["revenue"] = val
        elif "operating profit" in metric:
            data["operating_profit"] = val
        elif "net profit" in metric:
            data["net_profit"] = val
        elif metric.startswith("eps"):
            data["eps"] = val

    if len(data) <= 1:
        return None

    # Validate freshness: reject if quarter_label is more than 3 quarters old
    label = data.get("quarter_label", "")
    parts = label.split()  # e.g. ["Mar", "2026"]
    if len(parts) == 2:
        mon = MONTH_MAP.get(parts[0].lower())
        try:
            year = int(parts[1])
            if mon:
                quarter_date = datetime(year, mon, 1)
                now = datetime.now()
                months_old = (now.year - quarter_date.year) * 12 + (now.month - quarter_date.month)
                if months_old > 9:  # older than 3 quarters → Screener not updated yet
                    print(f"    [Screener] latest quarter: {label} ({months_old} months old — stale, skipping)")
                    return None
                print(f"    [Screener] latest quarter: {label} ({months_old} months old — fresh ✓)")
        except ValueError:
            pass

    return data


# ── Step 3: DB history ────────────────────────────────────────────────────────


def fetch_history(conn, symbol: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT qr.quarter, qr.year, qr.quarter_number,
               qr.revenue, qr.operating_profit, qr.net_profit, qr.eps
        FROM   quarterly_results qr
        JOIN   stocks s ON s.id = qr.stock_id
        WHERE  s.nse_symbol = %s
        ORDER  BY qr.year DESC, qr.quarter_number DESC
        LIMIT  5
    """,
        (symbol,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
    # Convert Decimal to float
    for row in rows:
        for k, v in row.items():
            with contextlib.suppress(TypeError, ValueError):
                row[k] = float(v) if v is not None else None
    return rows


def fetch_stock_meta(conn, symbol: str) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT name, sector, industry FROM stocks WHERE nse_symbol = %s", (symbol,))
    row = cur.fetchone()
    return {"name": row[0], "sector": row[1], "industry": row[2]} if row else {}


# ── Step 4: Metrics ───────────────────────────────────────────────────────────


def pct_change(current: float | None, prev: float | None) -> str:
    if current is None or prev is None or prev == 0:
        return "N/A"
    return f"{((current - prev) / abs(prev)) * 100:+.1f}%"


def fmt_cr(val: float | None) -> str:
    return f"₹{val:,.0f} Cr" if val is not None else "N/A"


def print_metrics(symbol: str, current: dict, qoq: dict | None, yoy: dict | None) -> None:
    print(f"\n  Current quarter : {current.get('quarter_label', '?')}")
    print(f"  {'Metric':<20} {'Current':>14}  {'QoQ':>8}  {'YoY':>8}")
    print(f"  {'-' * 56}")

    metrics = [
        ("Revenue", "revenue"),
        ("Operating Profit", "operating_profit"),
        ("Net Profit", "net_profit"),
        ("EPS (₹)", "eps"),
    ]
    for label, key in metrics:
        cur_v = current.get(key)
        qoq_v = qoq.get(key) if qoq else None
        yoy_v = yoy.get(key) if yoy else None
        cur_s = fmt_cr(cur_v) if key != "eps" else (f"₹{cur_v:.2f}" if cur_v else "N/A")
        print(f"  {label:<20} {cur_s:>14}  {pct_change(cur_v, qoq_v):>8}  {pct_change(cur_v, yoy_v):>8}")


# ── Step 5: Claude ────────────────────────────────────────────────────────────


def build_prompt(symbol: str, meta: dict, current: dict, qoq: dict | None, yoy: dict | None) -> str:
    sector = meta.get("sector") or meta.get("industry") or "Unknown"
    company = meta.get("name", symbol)
    lines = [
        "Analyze this quarterly result for PEAD (Post-Earnings Announcement Drift).\n",
        f"Company: {company} ({symbol}) | Sector: {sector}",
        f"Quarter: {current.get('quarter_label', 'Latest')}\n",
        "CURRENT QUARTER:",
        f"  Revenue:          {fmt_cr(current.get('revenue'))}",
        f"  Operating Profit: {fmt_cr(current.get('operating_profit'))}",
        f"  Net Profit:       {fmt_cr(current.get('net_profit'))}",
        f"  EPS:              ₹{current.get('eps') or 0:.2f}\n",
        "QoQ (vs previous quarter):",
        f"  Revenue:          {pct_change(current.get('revenue'), qoq.get('revenue') if qoq else None)}",
        f"  Operating Profit: {pct_change(current.get('operating_profit'), qoq.get('operating_profit') if qoq else None)}",
        f"  Net Profit:       {pct_change(current.get('net_profit'), qoq.get('net_profit') if qoq else None)}",
        f"  EPS:              {pct_change(current.get('eps'), qoq.get('eps') if qoq else None)}\n",
        "YoY (same quarter last year):",
        f"  Revenue:          {pct_change(current.get('revenue'), yoy.get('revenue') if yoy else None)}",
        f"  Operating Profit: {pct_change(current.get('operating_profit'), yoy.get('operating_profit') if yoy else None)}",
        f"  Net Profit:       {pct_change(current.get('net_profit'), yoy.get('net_profit') if yoy else None)}",
        f"  EPS:              {pct_change(current.get('eps'), yoy.get('eps') if yoy else None)}\n",
        "Respond with JSON only:",
        '{"signal":"LONG or SHORT","confidence":"HIGH/MEDIUM/LOW","reasoning":"2-3 sentences","holding_period":"X-Y days"}',
    ]
    return "\n".join(lines)


def call_claude(prompt: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    print(f"  Raw Claude response: {text}")
    return json.loads(text)


# ── Step 6: Telegram ──────────────────────────────────────────────────────────


def send_telegram(token: str, chat_id: str, text: str) -> None:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=10,
    )
    print(f"  Telegram HTTP {r.status_code}")
    if not r.ok:
        print(f"  Telegram error: {r.text[:200]}")


def phase1_message(ann: dict, announced_at: datetime) -> str:
    return (
        f"🔔 <b>NEW RESULT DETECTED</b> [LOCAL TEST]\n\n"
        f"<b>{ann['symbol']}</b> — {ann.get('sm_name', '')}\n"
        f"📅 Announced: {announced_at.strftime('%d-%b-%Y %H:%M:%S')} IST\n"
        f'<a href="{ann.get("attchmntFile", "")}">📎 View Filing</a>\n\n'
        f"⏳ Full analysis below..."
    )


def phase2_message(symbol: str, meta: dict, current: dict, qoq: dict | None, yoy: dict | None, signal: dict) -> str:
    company = meta.get("name", symbol)
    quarter = current.get("quarter_label", "Latest")

    def row(label, key):
        cur_v = current.get(key)
        q_v = qoq.get(key) if qoq else None
        y_v = yoy.get(key) if yoy else None
        val_s = fmt_cr(cur_v) if key != "eps" else (f"₹{cur_v:.2f}" if cur_v else "N/A")
        return f"<b>{label}:</b> {val_s}  <i>({pct_change(cur_v, q_v)} QoQ | {pct_change(cur_v, y_v)} YoY)</i>"

    sig_emoji = "🟢" if signal.get("signal") == "LONG" else "🔴"
    conf_emoji = {"HIGH": "🔥", "MEDIUM": "⚡️", "LOW": "❄️"}.get(signal.get("confidence", ""), "")

    return "\n".join(
        [
            f"📊 <b>{symbol} — {quarter} Results</b>",
            f"<i>{company}</i>\n",
            row("Revenue", "revenue"),
            row("Op. Profit", "operating_profit"),
            row("Net Profit", "net_profit"),
            row("EPS", "eps") + "\n",
            "🤖 <b>Claude PEAD Analysis</b>",
            signal.get("reasoning", "—"),
            "",
            f"Signal: {sig_emoji} <b>{signal.get('signal', '—')}</b>",
            f"Confidence: {conf_emoji} {signal.get('confidence', '—')}",
            f"Hold: {signal.get('holding_period', '—')}",
        ]
    )


# ── main ──────────────────────────────────────────────────────────────────────


def process_one(
    ann: dict, conn, screener_session: requests.Session | None, send_tg: bool, use_claude: bool = False
) -> None:
    symbol = ann["symbol"]
    seq_id = ann.get("seq_id", "?")
    ann_dt = parse_nse_dt(ann.get("an_dt", ""))

    print(f"\n{'─' * 60}")
    print(f"Processing: {symbol}  seq={seq_id}")
    print(f"Announced : {ann_dt.strftime('%d-%b-%Y %H:%M:%S IST') if ann_dt else 'unknown'}")
    print(f"Subject   : {ann.get('desc', '')}")
    print(f"PDF       : {ann.get('attchmntFile', '')}")

    # Phase 1 Telegram
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")

    if send_tg and tg_token and tg_chat and ann_dt:
        print("\n  Sending Phase 1 Telegram...")
        send_telegram(tg_token, tg_chat, phase1_message(ann, ann_dt))

    # DB history
    print("\n  Fetching DB history...")
    meta = fetch_stock_meta(conn, symbol)
    history = fetch_history(conn, symbol)
    print(f"  Company : {meta.get('name', 'not in DB')}")
    print(f"  Sector  : {meta.get('sector', '?')}")
    print(f"  History : {len(history)} quarters in DB")
    for h in history:
        print(
            f"    {h['quarter']} {h['year']}  "
            f"Rev={fmt_cr(h.get('revenue'))}  "
            f"NP={fmt_cr(h.get('net_profit'))}  "
            f"EPS={h.get('eps')}"
        )

    qoq = history[0] if len(history) > 0 else None
    yoy = history[3] if len(history) > 3 else None

    # Current quarter from Screener.in
    print("\n  Fetching current quarter from Screener.in...")
    current = None
    if screener_session:
        current = fetch_screener_quarter(screener_session, symbol)

    if current:
        print(f"  ✓ Got current quarter: {current.get('quarter_label')}")
        print_metrics(symbol, current, qoq, yoy)
    else:
        print("  ✗ Screener data not fresh yet (older than 3 quarters) — skipping Phase 2")
        return

    if not use_claude:
        print("\n  [Claude skipped — pass --claude to enable]")
        return

    # Claude
    print("\n  Calling Claude...")
    prompt = build_prompt(symbol, meta or {"name": ann.get("sm_name", symbol)}, current, qoq, yoy)
    print(f"\n  --- PROMPT ---\n{prompt}\n  --- END PROMPT ---")
    try:
        signal = call_claude(prompt)
        print(f"\n  Signal     : {signal.get('signal')}")
        print(f"  Confidence : {signal.get('confidence')}")
        print(f"  Reasoning  : {signal.get('reasoning')}")
        print(f"  Hold for   : {signal.get('holding_period')}")
    except Exception as e:
        print(f"  ✗ Claude error: {e}")
        signal = {"signal": "N/A", "confidence": "N/A", "reasoning": str(e), "holding_period": "—"}

    # Phase 2 Telegram
    if send_tg and tg_token and tg_chat:
        print("\n  Sending Phase 2 Telegram...")
        msg = phase2_message(symbol, meta or {"name": ann.get("sm_name", symbol)}, current, qoq, yoy, signal)
        send_telegram(tg_token, tg_chat, msg)
        print("\n  Phase 2 message:\n")
        clean = re.sub(r"<[^>]+>", "", msg)
        for line in clean.splitlines():
            print(f"    {line}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="09-05-2026", help="Date in DD-MM-YYYY format")
    parser.add_argument("--symbol", default=None, help="Test a specific symbol only")
    parser.add_argument("--no-telegram", action="store_true", help="Skip sending to Telegram")
    parser.add_argument("--skip-claude", action="store_true", default=True, help="Skip Claude API call (default: True)")
    parser.add_argument("--claude", action="store_true", help="Enable Claude API call (overrides --skip-claude)")
    parser.add_argument("--limit", type=int, default=5, help="Max companies to process (default: 5)")
    parser.add_argument(
        "--phase1-only", action="store_true", help="Only send Phase 1 alert (skip Screener, DB, Claude)"
    )
    args = parser.parse_args()

    send_tg = not args.no_telegram
    use_claude = args.claude
    phase1_only = args.phase1_only

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)
    db_url = clean_db_url(db_url)

    # Step 1: NSE announcements
    results = fetch_nse_announcements(args.date)
    if not results:
        print("\nNo result announcements found for this date.")
        sys.exit(0)

    if args.symbol:
        results = [r for r in results if r["symbol"].upper() == args.symbol.upper()]
        if not results:
            print(f"\nNo result found for symbol {args.symbol} on {args.date}")
            sys.exit(0)

    if not args.symbol and len(results) > args.limit:
        print(f"\nLimiting to first {args.limit} results (use --limit N to change)")
        results = results[: args.limit]

    # Filter by earnings calendar — only companies scheduled for this date in DB
    conn = psycopg2.connect(db_url)
    try:
        # Parse date arg (DD-MM-YYYY) → YYYY-MM-DD for DB
        d, m, y = args.date.split("-")
        cal_date = f"{y}-{m}-{d}"
        cur = conn.cursor()
        cur.execute("SELECT UPPER(symbol) FROM board_meetings WHERE meeting_date = %s", (cal_date,))
        calendar_symbols = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    print(f"\nEarnings calendar for {args.date}: {len(calendar_symbols)} companies scheduled")

    before = len(results)
    results = [r for r in results if r["symbol"].upper() in calendar_symbols]
    print(f"After calendar filter: {len(results)} (dropped {before - len(results)} not in calendar)")

    if not results:
        print("\nNo result announcements match today's earnings calendar.")
        sys.exit(0)

    if phase1_only:
        print(f"\n{'=' * 60}")
        print("PHASE 1 ONLY MODE — printing detection alerts")
        print("=" * 60)
        for ann in results:
            ann_dt = parse_nse_dt(ann.get("an_dt", ""))
            print(f"\n{'─' * 60}")
            print(f"Symbol    : {ann['symbol']}  ({ann.get('sm_name', '')})")
            print(f"Announced : {ann_dt.strftime('%d-%b-%Y %H:%M:%S IST') if ann_dt else 'unknown'}")
            print(f"Subject   : {ann.get('desc', '')}")
            print(f"PDF       : {ann.get('attchmntFile', '')}")

            tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
            if send_tg and tg_token and tg_chat and ann_dt:
                send_telegram(tg_token, tg_chat, phase1_message(ann, ann_dt))
        print(f"\n{'=' * 60}")
        print(f"Done. {len(results)} Phase 1 alert(s) sent.")
        print("=" * 60)
        return

    # Step 2: Screener login (once)
    print(f"\n{'=' * 60}")
    print("STEP 2 — Logging into Screener.in")
    print("=" * 60)
    screener_session = screener_login()

    # DB connection
    conn = psycopg2.connect(db_url)

    try:
        for ann in results:
            process_one(ann, conn, screener_session, send_tg, use_claude)
    finally:
        conn.close()

    print(f"\n{'=' * 60}")
    print(f"Done. Processed {len(results)} result announcement(s).")
    print("=" * 60)


if __name__ == "__main__":
    main()
