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


"""
PEAD Processor — Lambda function
Triggered by SQS (15-min delay after poller). Fetches current quarter
numbers from Screener.in, computes QoQ/YoY vs DB history, calls Claude
for LONG/SHORT signal, and sends the full analysis to Telegram.
"""


import json
import os
import re
from datetime import datetime, timedelta, timezone

import anthropic
import psycopg2
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

IST = timezone(timedelta(hours=5, minutes=30))


def clean_db_url(url: str) -> str:
    return re.sub(r'sslmode=["\']?(\w+)["\']?', r"sslmode=\1", url.strip())


# ── Screener.in ───────────────────────────────────────────────────────────────


def screener_login() -> requests.Session | None:
    username = os.environ.get("SCREENER_USERNAME")
    password = os.environ.get("SCREENER_PASSWORD")
    if not username or not password:
        return None

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    r = s.get("https://www.screener.in/login/", timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    csrf = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if not csrf:
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

    return None if "/login/" in r.url else s


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


def fetch_screener_quarter(session: requests.Session, symbol: str) -> dict | None:
    """Fetch the most recent quarter's data from Screener.in."""
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
    if not thead:
        return None

    headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    if len(headers) < 2:
        return None

    latest_label = headers[1]  # most recent quarter, e.g. "Mar 2026"
    data: dict = {"quarter_label": latest_label}

    for row in table.find("tbody").find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        metric = cells[0].get_text(strip=True).lower()
        val = _parse_number(cells[1].get_text(strip=True))
        if val is None:
            continue
        if "sales" in metric or "revenue" in metric:
            data["revenue"] = val
        elif "operating profit" in metric:
            data["operating_profit"] = val
        elif "net profit" in metric:
            data["net_profit"] = val
        elif metric.startswith("eps"):
            data["eps"] = val

    return data if len(data) > 1 else None


# ── DB history ────────────────────────────────────────────────────────────────


def fetch_history(conn, symbol: str) -> list[dict]:
    """Return the last 5 quarters for this stock from quarterly_results."""
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
    return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def fetch_stock_meta(conn, symbol: str) -> dict:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT name, sector, industry FROM stocks WHERE nse_symbol = %s
    """,
        (symbol,),
    )
    row = cur.fetchone()
    if not row:
        return {}
    return {"name": row[0], "sector": row[1], "industry": row[2]}


# ── Analysis ──────────────────────────────────────────────────────────────────


def pct_change(current: float | None, prev: float | None) -> str:
    if current is None or prev is None or prev == 0:
        return "N/A"
    return f"{((current - prev) / abs(prev)) * 100:+.1f}%"


def fmt_cr(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"₹{val:,.0f} Cr"


def build_claude_prompt(symbol: str, meta: dict, current: dict, qoq: dict | None, yoy: dict | None) -> str:
    sector = meta.get("sector") or meta.get("industry") or "Unknown"
    company = meta.get("name", symbol)

    lines = [
        "Analyze this quarterly result for PEAD (Post-Earnings Announcement Drift) strategy.\n",
        f"Company: {company} ({symbol}) | Sector: {sector}",
        f"Quarter: {current.get('quarter_label', 'Latest')}\n",
        "CURRENT QUARTER:",
        f"  Revenue:          {fmt_cr(current.get('revenue'))}",
        f"  Operating Profit: {fmt_cr(current.get('operating_profit'))}",
        f"  Net Profit:       {fmt_cr(current.get('net_profit'))}",
        f"  EPS:              ₹{current.get('eps', 0):.2f}\n",
        "QoQ CHANGE (vs previous quarter):",
        f"  Revenue:          {pct_change(current.get('revenue'), qoq.get('revenue') if qoq else None)}",
        f"  Operating Profit: {pct_change(current.get('operating_profit'), qoq.get('operating_profit') if qoq else None)}",
        f"  Net Profit:       {pct_change(current.get('net_profit'), qoq.get('net_profit') if qoq else None)}",
        f"  EPS:              {pct_change(current.get('eps'), qoq.get('eps') if qoq else None)}\n",
        "YoY CHANGE (vs same quarter last year):",
        f"  Revenue:          {pct_change(current.get('revenue'), yoy.get('revenue') if yoy else None)}",
        f"  Operating Profit: {pct_change(current.get('operating_profit'), yoy.get('operating_profit') if yoy else None)}",
        f"  Net Profit:       {pct_change(current.get('net_profit'), yoy.get('net_profit') if yoy else None)}",
        f"  EPS:              {pct_change(current.get('eps'), yoy.get('eps') if yoy else None)}\n",
        "Respond with JSON only — no extra text:",
        '{"signal":"LONG or SHORT","confidence":"HIGH/MEDIUM/LOW","reasoning":"2-3 sentences","holding_period":"X-Y days"}',
    ]
    return "\n".join(lines)


def call_claude(prompt: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    return json.loads(text)


# ── Telegram ──────────────────────────────────────────────────────────────────


def send_telegram(token: str, chat_id: str, text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=10,
    )


def phase2_message(
    symbol: str, meta: dict, current: dict, qoq: dict | None, yoy: dict | None, signal: dict, announced_at: str
) -> str:
    company = meta.get("name", symbol)
    quarter = current.get("quarter_label", "Latest")

    def row(label, val, q, y):
        return f"<b>{label}:</b> {fmt_cr(val)}  <i>({pct_change(val, q)} QoQ | {pct_change(val, y)} YoY)</i>"

    sig_emoji = "🟢" if signal.get("signal") == "LONG" else "🔴"
    conf = signal.get("confidence", "")
    conf_emoji = {"HIGH": "🔥", "MEDIUM": "⚡️", "LOW": "❄️"}.get(conf, "")

    lines = [
        f"📊 <b>{symbol} — {quarter} Results</b>",
        f"<i>{company}</i>\n",
        row(
            "Revenue", current.get("revenue"), qoq.get("revenue") if qoq else None, yoy.get("revenue") if yoy else None
        ),
        row(
            "Op. Profit",
            current.get("operating_profit"),
            qoq.get("operating_profit") if qoq else None,
            yoy.get("operating_profit") if yoy else None,
        ),
        row(
            "Net Profit",
            current.get("net_profit"),
            qoq.get("net_profit") if qoq else None,
            yoy.get("net_profit") if yoy else None,
        ),
        (
            f"<b>EPS:</b>          ₹{current.get('eps', 0):.2f}"
            f"  <i>({pct_change(current.get('eps'), qoq.get('eps') if qoq else None)} QoQ"
            f" | {pct_change(current.get('eps'), yoy.get('eps') if yoy else None)} YoY)</i>\n"
        ),
        "🤖 <b>Claude (PEAD Signal)</b>",
        signal.get("reasoning", ""),
        "",
        f"Signal: {sig_emoji} <b>{signal.get('signal', '—')}</b>",
        f"Confidence: {conf_emoji} {conf}",
        f"Hold: {signal.get('holding_period', '—')}",
    ]
    return "\n".join(lines)


# ── Lambda handler ────────────────────────────────────────────────────────────


def lambda_handler(event, context):
    db_url = clean_db_url(os.environ["DATABASE_URL"])
    tg_token = os.environ["TELEGRAM_BOT_TOKEN"]
    tg_chat = os.environ["TELEGRAM_CHAT_ID"]

    for record in event.get("Records", []):
        body = json.loads(record["body"])
        symbol = body["symbol"]
        seq_id = body["seq_id"]
        company_name = body.get("company_name", symbol)
        announced_at = body.get("announced_at", "")

        print(f"Processing {symbol} seq={seq_id}")

        conn = psycopg2.connect(db_url)
        try:
            meta = fetch_stock_meta(conn, symbol)
            history = fetch_history(conn, symbol)
        finally:
            conn.close()

        # QoQ = most recent quarter in DB, YoY = same quarter last year (index 3)
        qoq = history[0] if len(history) > 0 else None
        yoy = history[3] if len(history) > 3 else None

        # Fetch current quarter from Screener.in
        session = screener_login()
        current = None
        if session:
            current = fetch_screener_quarter(session, symbol)

        if not current:
            send_telegram(
                tg_token,
                tg_chat,
                f"⚠️ <b>{symbol}</b>: Could not fetch current quarter data from Screener.in yet.\n"
                f"DB has {len(history)} historical quarters.\nRetry manually later.",
            )
            print(f"No current quarter data for {symbol}")
            return

        if not meta:
            meta = {"name": company_name}

        # Claude analysis
        try:
            prompt = build_claude_prompt(symbol, meta, current, qoq, yoy)
            signal = call_claude(prompt)
        except Exception as e:
            print(f"Claude error: {e}")
            signal = {"signal": "N/A", "confidence": "N/A", "reasoning": f"Analysis failed: {e}", "holding_period": "—"}

        # Send Phase 2 Telegram
        msg = phase2_message(symbol, meta, current, qoq, yoy, signal, announced_at)
        send_telegram(tg_token, tg_chat, msg)

        # Update DB
        conn = psycopg2.connect(db_url)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE pead_announcements
                SET phase2_sent = TRUE, claude_signal = %s
                WHERE seq_id = %s
            """,
                (signal.get("signal"), seq_id),
            )
            conn.commit()
        finally:
            conn.close()

        print(f"Done {symbol} → {signal.get('signal')}")
