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
PEAD Poller — Lambda function
Runs every minute via EventBridge. Detects new quarterly result
announcements on NSE and triggers downstream processing via SQS.
"""


import json
import os
import re
from datetime import UTC, datetime, timedelta, timezone

import boto3
import psycopg2
import requests

NSE_API = "https://www.nseindia.com/api/corporate-announcements"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

RESULT_KEYWORDS = [
    "financial result",
    "quarterly result",
    "unaudited result",
    "audited result",
    "half yearly result",
    "annual result",
]

# Most genuine results outcomes use NSE's generic boilerplate ("X Limited has
# informed the Exchange regarding Outcome of [the] Board Meeting held on
# <date>.") because the actual financial figures live in the XBRL/PDF, not
# this text field. Only treat a board-meeting filing as NOT a result if it
# names something else specific instead of (or in addition to) that phrase.
GENERIC_OUTCOME_RE = re.compile(
    r"^.*\boutcome of (the )?board meeting\b(\s+held on [^.]+)?\.?\s*$",
    re.IGNORECASE,
)

PRESENTATION_KEYWORDS = [
    "investor presentation",
    "investors presentation",
    "investor update",
    "investor meet",
    "investor/analyst",
    "analyst meet",
    "investorpresentation",
    "investorupdate",
]
PRESS_RELEASE_KEYWORDS = ["press release"]
CONCALL_KEYWORDS = ["concall", "con call", "conference call", "earnings call"]
TRANSCRIPT_KEYWORDS = ["transcript"]

EXCLUDE_CATEGORIES = [
    "copy of newspaper publication",
    "clarification - financial results",
    "reply to clarification",
    "analysts/institutional investor meet",
    "corporate insolvency",
    "general updates",
]

IST = timezone(timedelta(hours=5, minutes=30))

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pead_announcements (
    id             SERIAL PRIMARY KEY,
    seq_id         VARCHAR(50) UNIQUE NOT NULL,
    symbol         VARCHAR(20) NOT NULL,
    company_name   VARCHAR(500),
    announced_at   TIMESTAMPTZ NOT NULL,
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    latency_sec    INT,
    subject        TEXT,
    attachment_url VARCHAR(1000),
    has_xbrl       BOOLEAN DEFAULT FALSE,
    phase1_sent    BOOLEAN DEFAULT FALSE,
    phase2_sent    BOOLEAN DEFAULT FALSE,
    claude_signal  VARCHAR(10),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_pead_seq     ON pead_announcements (seq_id);
CREATE INDEX IF NOT EXISTS ix_pead_symbol  ON pead_announcements (symbol);
CREATE INDEX IF NOT EXISTS ix_pead_ann_at  ON pead_announcements (announced_at DESC);
"""


def clean_db_url(url: str) -> str:
    return re.sub(r'sslmode=["\']?(\w+)["\']?', r"sslmode=\1", url.strip())


def is_result(ann: dict) -> bool:
    cat = ann.get("desc", "").lower()
    if any(excl in cat for excl in EXCLUDE_CATEGORIES):
        return False
    text = (ann.get("desc", "") + " " + ann.get("attchmntText", "")).lower()
    if "outcome of board meeting" in cat:
        # Board meetings cover many agendas (auditor appointment, NCDs, etc.).
        # Trust the generic NSE boilerplate (real results are usually filed
        # this way, with figures in the XBRL/PDF, not this text field); only
        # reject if it names something else specific instead.
        attchmnt_text = (ann.get("attchmntText") or "").strip()
        if "result" in text:
            return True
        return attchmnt_text == "" or bool(GENERIC_OUTCOME_RE.match(attchmnt_text))
    return any(kw in text for kw in RESULT_KEYWORDS)


def classify_doc_type(ann: dict) -> str:
    category = (ann.get("desc") or "").lower()
    # Categories excluded from result detection are also not real presentations
    if any(excl in category for excl in EXCLUDE_CATEGORIES):
        return "general"
    text = (ann.get("attchmntText") or "").lower()
    url = (ann.get("attchmntFile") or "").lower().replace("_", " ").replace("-", " ")
    combined = f"{category} {text} {url}"
    if "outcome of board meeting" in category or any(k in combined for k in RESULT_KEYWORDS):
        return "result"
    if any(k in combined for k in PRESENTATION_KEYWORDS):
        return "presentation"
    if any(k in combined for k in TRANSCRIPT_KEYWORDS):
        return "transcript"
    if any(k in combined for k in CONCALL_KEYWORDS):
        return "concall"
    if any(k in combined for k in PRESS_RELEASE_KEYWORDS):
        return "press_release"
    return "general"


CREATE_NSE_DOCS_SQL = """
CREATE TABLE IF NOT EXISTS nse_documents (
    id                SERIAL PRIMARY KEY,
    seq_id            TEXT UNIQUE NOT NULL,
    symbol            TEXT NOT NULL,
    company_name      TEXT,
    category          TEXT,
    description       TEXT,
    attachment_url    TEXT,
    doc_type          TEXT NOT NULL DEFAULT 'general',
    nse_filed_at      TIMESTAMPTZ,
    fetched_at        TIMESTAMPTZ DEFAULT NOW(),
    kw_dispatched_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_nse_docs_symbol   ON nse_documents (symbol);
CREATE INDEX IF NOT EXISTS ix_nse_docs_doc_type ON nse_documents (doc_type);
CREATE INDEX IF NOT EXISTS ix_nse_docs_filed_at ON nse_documents (nse_filed_at);
ALTER TABLE nse_documents ADD COLUMN IF NOT EXISTS kw_dispatched_at TIMESTAMPTZ;
"""


def upsert_nse_documents(cur, announcements: list[dict], now_ist: datetime) -> int:
    """Upsert all today's NSE announcements into nse_documents. Returns insert count."""
    inserted = 0
    for ann in announcements:
        seq_id = str(ann.get("seq_id") or "").strip()
        if not seq_id:
            continue
        symbol = (ann.get("symbol") or "").strip().upper()
        doc_type = classify_doc_type(ann)
        nse_filed_at = parse_nse_dt(ann.get("an_dt", "")) or now_ist.replace(hour=12, minute=0, second=0, microsecond=0)
        cur.execute(
            """
            INSERT INTO nse_documents
                (seq_id, symbol, company_name, category, description,
                 attachment_url, doc_type, nse_filed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (seq_id) DO UPDATE
                SET company_name   = EXCLUDED.company_name,
                    category       = EXCLUDED.category,
                    description    = EXCLUDED.description,
                    attachment_url = EXCLUDED.attachment_url,
                    doc_type       = EXCLUDED.doc_type
            RETURNING (xmax = 0) AS was_inserted
        """,
            (
                seq_id,
                symbol,
                (ann.get("sm_name") or "").strip(),
                (ann.get("desc") or "").strip(),
                (ann.get("attchmntText") or "").strip(),
                (ann.get("attchmntFile") or "").strip(),
                doc_type,
                nse_filed_at,
            ),
        )
        row = cur.fetchone()
        if row and row[0]:
            inserted += 1
    return inserted


def dispatch_pending_presentations(cur, gh_pat: str) -> None:
    """
    Dispatch keyword analysis for presentations filed today whose symbol
    announced results today. At most one dispatch per symbol per day.
    """
    cur.execute("""
        SELECT DISTINCT ON (nd.symbol) nd.seq_id, nd.symbol, nd.attachment_url
        FROM nse_documents nd
        JOIN pead_announcements pa ON UPPER(pa.symbol) = nd.symbol
        WHERE nd.doc_type = 'presentation'
          AND nd.attachment_url != ''
          AND nd.kw_dispatched_at IS NULL
          AND DATE(nd.nse_filed_at  AT TIME ZONE 'Asia/Kolkata') = CURRENT_DATE
          AND DATE(pa.announced_at  AT TIME ZONE 'Asia/Kolkata') = CURRENT_DATE
        ORDER BY nd.symbol, nd.nse_filed_at ASC
        LIMIT 20
    """)
    rows = cur.fetchall()
    if not rows:
        return

    print(f"Pending keyword analysis dispatches: {len(rows)}")
    for seq_id, symbol, attachment_url in rows:
        # Mark BEFORE dispatching so a Lambda timeout/crash after the
        # GitHub API call never causes a duplicate dispatch on the next poll.
        cur.execute(
            """
            UPDATE nse_documents SET kw_dispatched_at = NOW() WHERE seq_id = %s
        """,
            (seq_id,),
        )
        cur.connection.commit()
        dispatch_keyword_analysis(symbol, attachment_url, gh_pat)


def parse_nse_dt(s: str) -> datetime | None:
    """Parse '10-May-2026 14:32:07' → aware datetime in IST."""
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    return None


def fetch_nse_announcements(today: str) -> list[dict]:
    resp = requests.get(
        NSE_API,
        params={"index": "equities", "from_date": today, "to_date": today},
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


GH_OWNER = "gurudayal37"
GH_REPO = "nse-data-syncer"
GH_WORKFLOW = "keyword_analysis_single.yml"
GH_ANALYSE_WORKFLOW = "auto_analyse_result.yml"


def _gh_dispatch(workflow: str, inputs: dict, gh_pat: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/actions/workflows/{workflow}/dispatches",
            headers={
                "Authorization": f"token {gh_pat}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": "main", "inputs": inputs},
            timeout=10,
        )
        return resp.status_code == 204
    except Exception as e:
        print(f"GH dispatch error ({workflow}): {e}")
        return False


def dispatch_keyword_analysis(symbol: str, pdf_url: str, gh_pat: str) -> None:
    """Trigger keyword_analysis_single.yml with the exact PDF URL — no re-search."""
    ok = _gh_dispatch(GH_WORKFLOW, {"symbol": symbol, "pdf_url": pdf_url}, gh_pat)
    if ok:
        print(f"Keyword analysis triggered for {symbol}")
    else:
        print(f"Keyword analysis dispatch failed for {symbol}")


VERCEL_URL = "https://nse-data-syncer.vercel.app"


def dispatch_result_analysis(symbol: str, pdf_url: str, seq_id: str, result_date: str) -> None:
    """Call Vercel API directly to trigger Claude analysis of result PDF."""
    try:
        resp = requests.post(
            f"{VERCEL_URL}/api/earnings-timeline/analyse",
            json={
                "symbol": symbol,
                "pdf_url": pdf_url,
                "seq_id": seq_id,
                "result_date": result_date,
            },
            timeout=60,  # Claude can take up to 30s for PDF analysis
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"Result analysis complete for {symbol}: signal={data.get('data', {}).get('signal')}")
        else:
            print(f"Result analysis failed for {symbol}: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"Result analysis error for {symbol}: {e}")


def send_telegram(token: str, chat_id: str, text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=10,
    )


def phase1_message(ann: dict, announced_at: datetime, latency_sec: int) -> str:
    pdf = ann.get("attchmntFile", "")
    return (
        f"🔔 <b>NEW RESULT DETECTED</b>\n\n"
        f"<b>{ann['symbol']}</b> — {ann.get('sm_name', '')}\n"
        f"📅 Announced: {announced_at.strftime('%d-%b-%Y %H:%M:%S')} IST\n"
        f"⚡️ Detected in ~{latency_sec} sec\n"
        f'<a href="{pdf}">📎 View Filing</a>\n\n'
        f"⏳ Full QoQ/YoY analysis + PEAD signal in ~15 min..."
    )


def lambda_handler(event, context):
    db_url = clean_db_url(os.environ["DATABASE_URL"])
    tg_token = os.environ["TELEGRAM_BOT_TOKEN"]
    tg_chat = os.environ["TELEGRAM_CHAT_ID"]
    sqs_url = os.environ["SQS_QUEUE_URL"]

    now_ist = datetime.now(IST)

    # Only skip outside 8 AM – 9 PM IST
    if not (8 <= now_ist.hour < 21):
        return {"message": "Outside polling window"}

    today = now_ist.strftime("%d-%m-%Y")

    try:
        announcements = fetch_nse_announcements(today)
    except Exception as e:
        print(f"NSE fetch error: {e}")
        return {"error": str(e)}

    result_anns = [a for a in announcements if is_result(a)]
    print(f"Announcements today: {len(announcements)}, results: {len(result_anns)}")

    # Upsert ALL announcements into nse_documents.
    # Keyword analysis runs nightly via keyword_analysis_daily.yml instead of
    # being dispatched per-presentation here.
    conn_docs = psycopg2.connect(db_url)
    try:
        cur_docs = conn_docs.cursor()
        cur_docs.execute(CREATE_NSE_DOCS_SQL)
        n_inserted = upsert_nse_documents(cur_docs, announcements, now_ist)
        conn_docs.commit()
        print(f"nse_documents: {n_inserted} new of {len(announcements)}")
    except Exception as e:
        print(f"nse_documents error: {e}")
    finally:
        conn_docs.close()

    # Filter to companies scheduled in today's earnings calendar
    conn_check = psycopg2.connect(db_url)
    try:
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT UPPER(symbol) FROM board_meetings WHERE meeting_date = %s", (now_ist.date(),))
        calendar_symbols = {row[0] for row in cur_check.fetchall()}
    finally:
        conn_check.close()

    result_anns = [a for a in result_anns if a.get("symbol", "").upper() in calendar_symbols]
    print(f"After calendar filter: {len(result_anns)}")

    if not result_anns:
        return {"processed": 0, "message": "No new results"}

    conn = psycopg2.connect(db_url)
    sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-south-1"))

    try:
        cur = conn.cursor()
        cur.execute(CREATE_TABLE_SQL)

        processed = 0
        for ann in result_anns:
            seq_id = str(ann.get("seq_id", ""))
            if not seq_id:
                continue

            # Skip already-seen announcements
            cur.execute("SELECT 1 FROM pead_announcements WHERE seq_id = %s", (seq_id,))
            if cur.fetchone():
                continue

            announced_at = parse_nse_dt(ann.get("an_dt", ""))
            if not announced_at:
                continue

            now_utc = datetime.now(UTC)
            latency_sec = int((now_utc - announced_at.astimezone(UTC)).total_seconds())
            latency_sec = max(0, latency_sec)

            # Store in DB
            cur.execute(
                """
                INSERT INTO pead_announcements
                    (seq_id, symbol, company_name, announced_at, latency_sec,
                     subject, attachment_url, has_xbrl, phase1_sent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (seq_id) DO NOTHING
            """,
                (
                    seq_id,
                    ann.get("symbol", ""),
                    ann.get("sm_name", ""),
                    announced_at,
                    latency_sec,
                    ann.get("desc", ""),
                    ann.get("attchmntFile", ""),
                    bool(ann.get("hasXbrl")),
                ),
            )

            # Phase 1 Telegram
            send_telegram(tg_token, tg_chat, phase1_message(ann, announced_at, latency_sec))

            # Put on SQS with 15-min delay for processor
            sqs.send_message(
                QueueUrl=sqs_url,
                MessageBody=json.dumps(
                    {
                        "seq_id": seq_id,
                        "symbol": ann.get("symbol", ""),
                        "company_name": ann.get("sm_name", ""),
                        "announced_at": announced_at.isoformat(),
                        "attachment_url": ann.get("attchmntFile", ""),
                    }
                ),
                DelaySeconds=900,  # 15 minutes
            )

            print(f"Processed new result: {ann.get('symbol')} seq={seq_id}")
            processed += 1

        conn.commit()
        return {"processed": processed}

    finally:
        conn.close()
