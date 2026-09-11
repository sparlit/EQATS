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


import io
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pdfplumber
import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────
#  CONFIG  (edit these if needed)
# ─────────────────────────────────────────
OUTPUT_DIR = "transcripts"
YEARS_BACK = 5
DELAY_BETWEEN = 3  # seconds between PDF downloads
PAGE_TIMEOUT = 60_000  # ms – how long to wait for BSE page
RESUME_FILE = os.path.join(OUTPUT_DIR, "resume.txt")
LOG_FILE = os.path.join(OUTPUT_DIR, "run.log")
HEADLESS = True  # False = see the browser (local debug only)

# Keywords that identify a concall/transcript announcement
TRANSCRIPT_KEYWORDS = [
    "transcript",
    "concall",
    "conference call",
    "earnings call",
    "investor meet",
    "analyst meet",
    "con call",
    "con-call",
]
# ─────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
#  DATE RANGE
# ─────────────────────────────────────────
today = datetime.now()
start_date = today - timedelta(days=365 * YEARS_BACK)

# Allow resume
if os.path.exists(RESUME_FILE):
    try:
        saved = datetime.strptime(Path(RESUME_FILE).read_text().strip(), "%Y-%m-%d")
        if start_date < saved < today:
            log.info(f"▶ Resuming from {saved.date()}")
            start_date = saved
    except Exception:
        pass

log.info("=" * 80)
log.info("🔄  BSE Concall Transcript Downloader  (Playwright)")
log.info(f"📅  Range : {start_date.date()} → {today.date()}")
log.info("=" * 80)


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def is_transcript(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in TRANSCRIPT_KEYWORDS)


def safe_filename(s: str, maxlen: int = 80) -> str:
    return re.sub(r"[^\w\s\-]", "_", s).strip()[:maxlen]


def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n\n".join(pages) if pages else "[No text extracted from PDF]"
    except Exception as e:
        return f"[PDF extraction failed: {e}]"


def save_transcript(company: str, date_str: str, headline: str, pdf_bytes: bytes) -> bool:
    try:
        company_dir = os.path.join(OUTPUT_DIR, safe_filename(company, 60))
        os.makedirs(company_dir, exist_ok=True)

        text = extract_pdf_text(pdf_bytes)
        fname = f"{date_str}_{safe_filename(headline)}.txt"
        fpath = os.path.join(company_dir, fname)

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"Company  : {company}\n")
            f.write(f"Date     : {date_str}\n")
            f.write(f"Headline : {headline}\n")
            f.write(f"Saved    : {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n\n")
            f.write(text)

        log.info(f"  ✅  Saved → {fpath}  ({len(text):,} chars)")
        return True
    except Exception as e:
        log.exception(f"  ❌  Save failed: {e}")
        return False


def download_pdf(url: str, session: requests.Session) -> bytes | None:
    """Download a PDF using requests (cookies/headers already set by Playwright)."""
    for attempt in range(3):
        try:
            r = session.get(url, timeout=45)
            if r.status_code == 200 and r.content:
                return r.content
            log.warning(f"  ⚠  HTTP {r.status_code} for PDF (attempt {attempt + 1})")
        except Exception as e:
            log.warning(f"  ⚠  PDF download error: {e} (attempt {attempt + 1})")
        time.sleep(4)
    return None


# ─────────────────────────────────────────
#  MAIN SCRAPER
# ─────────────────────────────────────────
total_saved = 0
total_seen = 0

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=HEADLESS)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
        locale="en-IN",
    )
    page = context.new_page()

    # ── Step 1: Open BSE and let it load cookies / JS ──────────────────────
    log.info("🌐  Opening BSE India …")
    try:
        page.goto("https://www.bseindia.com/corporates/ann.html", wait_until="networkidle", timeout=PAGE_TIMEOUT)
        page.wait_for_timeout(3000)
    except PlaywrightTimeout:
        log.warning("Page load timed-out – trying anyway")

    # ── Step 2: Grab cookies for requests session ───────────────────────────
    req_session = requests.Session()
    req_session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.bseindia.com/",
            "Accept": "application/json, text/plain, */*",
        }
    )
    for c in context.cookies():
        req_session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

    # ── Step 3: Walk date range in 10-day batches ───────────────────────────
    cursor = start_date
    while cursor <= today:
        batch_end = min(cursor + timedelta(days=9), today)
        from_str = cursor.strftime("%Y%m%d")
        to_str = batch_end.strftime("%Y%m%d")
        from_disp = cursor.strftime("%d/%m/%Y")
        to_disp = batch_end.strftime("%d/%m/%Y")

        log.info(f"\n{'─' * 70}")
        log.info(f"📍  Batch {from_disp} → {to_disp}")

        # Call BSE announcements API (now with real browser cookies)
        try:
            api_url = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
            params = {
                "pageno": 1,
                "strCat": "-1",
                "strPrevDate": from_str,
                "strToDate": to_str,
                "strScrip": "",
                "strSearch": "P",
            }
            resp = req_session.get(api_url, params=params, timeout=30)
            log.info(f"  API status: {resp.status_code}  |  body len: {len(resp.text)}")

            if resp.status_code != 200 or not resp.text.strip():
                log.warning("  ⚠  Empty/blocked response – skipping batch")
                cursor = batch_end + timedelta(days=1)
                continue

            data = resp.json()

            # ── Figure out where the rows live ──────────────────────────────
            # BSE API can return Table, Table1, or a top-level list
            rows = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                for key in ("Table", "Table1", "data", "announcements"):
                    if key in data and isinstance(data[key], list):
                        rows = data[key]
                        break
                if not rows:
                    # dump keys so we can debug
                    log.warning(f"  ⚠  Unknown API shape. Keys: {list(data.keys())}")
                    # save raw response for inspection
                    debug_path = os.path.join(OUTPUT_DIR, f"debug_{from_str}.json")
                    Path(debug_path).write_text(json.dumps(data, indent=2))
                    log.info(f"  💾  Raw response saved to {debug_path}")
                    cursor = batch_end + timedelta(days=1)
                    continue

            log.info(f"  📄  {len(rows)} announcements in batch")

            for row in rows:
                # ── Detect headline / subject field ─────────────────────────
                headline = (
                    row.get("HEADLINE")
                    or row.get("headline")
                    or row.get("NEWSSUB")
                    or row.get("Subject")
                    or row.get("subject")
                    or ""
                )
                if not is_transcript(headline):
                    continue

                total_seen += 1

                # ── Company name ────────────────────────────────────────────
                company = (
                    row.get("SLONGNAME")
                    or row.get("company_name")
                    or row.get("CompanyName")
                    or row.get("COMPANYNAME")
                    or row.get("scrip_cd")
                    or "Unknown"
                )

                # ── Date ────────────────────────────────────────────────────
                date_raw = row.get("NEWS_DT") or row.get("dt") or row.get("DATE") or row.get("ANN_DATE") or ""
                date_str = date_raw[:10].replace("/", "-")

                # ── PDF attachment URL ───────────────────────────────────────
                attach = (
                    row.get("ATTACHMENTNAME")
                    or row.get("attachment")
                    or row.get("FILENAME")
                    or row.get("pdf_link")
                    or row.get("atchmt_fname")
                    or ""
                )

                if not attach:
                    log.debug(f"  – No attachment for: {headline[:60]}")
                    continue

                # Build full URL
                if attach.startswith("http"):
                    pdf_url = attach
                else:
                    # BSE stores PDFs at this path
                    pdf_url = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attach}"

                log.info(f"  ⬇  {company} | {date_str} | {headline[:50]}")
                pdf_bytes = download_pdf(pdf_url, req_session)

                if pdf_bytes:
                    if save_transcript(company, date_str, headline, pdf_bytes):
                        total_saved += 1
                    time.sleep(DELAY_BETWEEN)

        except json.JSONDecodeError:
            # Save raw text so we can see what BSE actually returned
            debug_path = os.path.join(OUTPUT_DIR, f"debug_raw_{from_str}.txt")
            try:
                Path(debug_path).write_text(resp.text[:5000])
                log.warning(f"  ⚠  JSON decode failed. Raw saved to {debug_path}")
            except Exception:
                pass
        except Exception as e:
            log.exception(f"  ❌  Batch error: {e}")

        # ── Save resume point ─────────────────────────────────────────────
        Path(RESUME_FILE).write_text(batch_end.strftime("%Y-%m-%d"))
        cursor = batch_end + timedelta(days=1)
        time.sleep(3)

    browser.close()

# ─────────────────────────────────────────
#  SUMMARY
# ─────────────────────────────────────────
log.info("\n" + "=" * 80)
log.info("🎉  DONE")
log.info(f"   Transcripts found : {total_seen}")
log.info(f"   Transcripts saved : {total_saved}")
log.info(f"   Output folder     : {OUTPUT_DIR}/")
log.info("=" * 80)
