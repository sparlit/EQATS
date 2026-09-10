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


# Free NSE/BSE Announcement Scanner with Telegram Alerts
# Fetches today's BSE corporate announcements, filters by keyword categories,
# and sends new (not-yet-seen) relevant ones to Telegram.
#
# Designed to run on a schedule (e.g. via GitHub Actions) - each run:
#  1. Fetches today's announcements from BSE
#  2. Filters for relevant ones using categorized keywords
#  3. Compares against a "seen" list stored in a local file (sent_alerts.json)
#  4. Sends only NEW relevant announcements to Telegram
#  5. Updates the seen list and saves it back to the file
#
# Requires: pip install bse requests

import json
import os
from datetime import datetime

import requests
from bse import BSE
from nse import NSE

# ---- CONFIG: token and chat ID are read from environment variables.
# In GitHub Actions, these are securely injected from repository Secrets.
# For local/Colab testing, set them with os.environ before running this script. ----
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables must be set.")
    raise SystemExit(1)

SEEN_FILE = "sent_alerts.json"

# ---- Categorized keyword sets ----
KEYWORDS = {
    "Order/MoU/Contract": [
        "order win",
        "bags order",
        "secures order",
        "wins order",
        "receives order",
        "order received",
        "new order",
        "award of order",
        "receipt of order",
        "work awarded",
        "order awarded",
        "contract awarded",
        "export order",
        "bags rs",
        "bags inr",
        "bags usd",
        "secures rs",
        "secures inr",
        "secures usd",
        "wins rs",
        "mou",
        "memorandum of understanding",
        "letter of award",
        "loa",
        "letter of acceptance",
        "letter of intent",
        "loi",
        "contract win",
        "awarded contract",
        "purchase order",
        "work order",
        "supply agreement",
        "definitive agreement",
    ],
    "Regulatory/Drug Approval": [
        "usfda",
        "us fda",
        "fda approval",
        "anda approval",
        "cdsco approval",
        "drug approval",
        "clinical trial",
        "phase iii",
        "phase 3",
        "phase ii",
        "marketing authorization",
        "import license",
        "manufacturing license",
        "who-gmp",
        "eu-gmp",
        "form 483",
        "warning letter",
        "import alert",
    ],
    "M&A/Corporate Action": [
        "definitive acquisition",
        "completes acquisition",
        "announces acquisition",
        "merger",
        "amalgamation",
        "stake sale",
        "divestment",
        "joint venture agreement",
        "strategic investment",
        "delisting",
        "buyback",
    ],
    "Partnership/Certification": [
        "partner program",
        "partnership agreement",
        "strategic partnership",
        "authorized distributor",
        "authorized partner",
        "distributor designation",
        "certification",
        "certified partner",
        "alliance agreement",
        "preferred partner",
        "platinum partner",
        "gold partner",
        "distributor agreement",
        "reseller agreement",
        "collaboration agreement",
        "technology partnership",
    ],
    "Capacity/Expansion": [
        "capacity expansion",
        "new plant",
        "greenfield",
        "brownfield",
        "commissioning",
        "capex",
        "expansion plan",
    ],
    "Financial/Results": [
        "credit rating upgrade",
        "credit rating downgrade",
        "rating upgrade",
        "rating downgrade",
        "payment default",
        "default on payment",
        "insolvency proceedings",
        "ibc proceedings",
        "nclt order",
        "nclat order",
        "liquidation order",
        "resolution plan approved",
    ],
    "Litigation/Regulatory Action": [
        "sebi order",
        "show cause notice",
        "raid conducted",
        "fraud detected",
        "fir registered",
        "cbi investigation",
        "search and seizure",
        "regulatory penalty",
        "sebi penalty",
    ],
}


import re

EXCLUSIONS = {
    "Order/MoU/Contract": [
        "appointment",
        "managing director",
        "cmd",
        "whole time director",
        "board meeting",
        "agm",
        "egm",
        "resignation",
        "cessation",
        "income tax",
        "gst act",
        "tax act",
        "tax demand",
        "tax order",
        "district collector",
        "district magistrate",
        "order received from sebi",
        "order passed by sebi",
        "sebi order",
        "sebi circular",
        "itat",
        "income tax appellate",
        "penalty order",
        "demand order",
        "show cause",
        "please find the attached submission",
        "committee of creditors",
        "nclt convened",
        "regulation 30 of sebi",
    ]
}


def extract_key_details(text):
    details = {}
    money_patterns = [
        r"rs\.?\s*[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh|lac|million|billion|thousand)?",
        r"inr\s*[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh|lac|million|billion)?",
        r"usd\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?",
        r"[\d,]+(?:\.\d+)?\s*(?:crore|cr)\b",
        r"[\d,]+(?:\.\d+)?\s*(?:million|billion)\b",
    ]
    amounts = []
    for pattern in money_patterns:
        found = re.findall(pattern, text.lower())
        amounts.extend(found)
    seen_amounts = set()
    unique_amounts = []
    for a in amounts:
        normalized = re.sub(r"\s+", " ", a.strip())
        if normalized not in seen_amounts:
            seen_amounts.add(normalized)
            unique_amounts.append(normalized)
    if unique_amounts:
        details["order_value"] = ", ".join(unique_amounts[:2])
    client_patterns = [
        r"from\s+([A-Z][^\.]{3,60}?)(?:\s+for\s+|\s+towards\s+|\s+amounting|\s+worth|\s+valued)",
        r"awarded by\s+([A-Z][^\.]{3,60}?)(?:\s+for\s+|\.)",
        r"with\s+([A-Z][^\.]{3,60}?)\s+(?:for|on|dated|amounting)",
        r"(?:client|customer|authority)[:\s]+([A-Z][^\.]{3,60}?)(?:\s+for\s+|\.|\,)",
    ]
    for pattern in client_patterns:
        match = re.search(pattern, text)
        if match:
            client = match.group(1).strip()
            if 5 < len(client) < 80:
                details["client"] = client
                break
    return details


def clean_company_name_for_search(name):
    cleaned = re.sub(r"\b(ltd\.?|limited|pvt\.?|private|inc\.?|corp\.?|corporation)\b", "", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def search_order_value_from_news(company_name):
    try:
        import time
        import xml.etree.ElementTree as ET
        from urllib.parse import quote

        clean_name = clean_company_name_for_search(company_name)
        query = quote(f'"{clean_name}" order crore')
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, headers=headers, timeout=8)
        no_results = response.status_code != 200
        if no_results:
            return None
        root = ET.fromstring(response.content)
        items = root.findall(".//item")
        money_patterns = [
            r"rs\.?\s*[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh|lac)",
            r"inr\s*[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh)",
            r"[\d,]+(?:\.\d+)?\s*(?:crore|cr)\b",
            r"usd\s*[\d,]+(?:\.\d+)?\s*(?:million|billion)",
        ]
        for item in items[:5]:
            title = item.findtext("title", "")
            desc = item.findtext("description", "")
            combined = f"{title} {desc}".lower()
            for pattern in money_patterns:
                match = re.search(pattern, combined)
                if match:
                    return match.group(0).strip()
        return None
    except Exception:
        return None


def format_telegram_message_with_details(company, display_text, categories_str, source, details):
    lines = []
    lines.append(f"[{source}] <b>{company}</b>")
    lines.append(f"Category: {categories_str}")
    if "order_value" in details:
        lines.append(f"Value: {details['order_value'].upper()}")
    if "client" in details:
        lines.append(f"Client: {details['client']}")
    lines.append(f"\n{display_text[:600]}{'...' if len(display_text) > 600 else ''}")
    return "\n".join(lines)


def format_telegram_message(company, display_text, categories_str, source):
    details = extract_key_details(display_text)
    is_order = "Order" in categories_str
    no_value_found = "order_value" not in details
    if is_order and no_value_found:
        news_value = search_order_value_from_news(company)
        if news_value:
            details["order_value"] = news_value + " (via news)"
    lines = []
    lines.append(f"[{source}] <b>{company}</b>")
    lines.append(f"Category: {categories_str}")
    if "order_value" in details:
        lines.append(f"Value: {details['order_value'].upper()}")
    if "client" in details:
        lines.append(f"Client: {details['client']}")
    lines.append(f"\n{display_text[:600]}{'...' if len(display_text) > 600 else ''}")
    return "\n".join(lines)


def classify_announcement(headline, detailed_text, category_name, subcategory_name):
    combined_text = f"{headline} {detailed_text} {category_name} {subcategory_name}".lower()
    matched_categories = []
    for category, terms in KEYWORDS.items():
        term_idx = 0
        found_in_category = False
        while term_idx < len(terms):
            term = terms[term_idx]
            pattern = r"\b" + re.escape(term) + r"\b"
            found = re.search(pattern, combined_text) is not None
            if found:
                found_in_category = True
            term_idx = term_idx + 1
        if found_in_category:
            exclusion_terms = EXCLUSIONS.get(category, [])
            excluded = any(re.search(r"\b" + re.escape(e) + r"\b", combined_text) for e in exclusion_terms)
            if not excluded:
                matched_categories.append(category)
    return matched_categories


def load_seen_ids():
    file_exists = os.path.exists(SEEN_FILE)
    if not file_exists:
        return set()
    with open(SEEN_FILE) as f:
        data = json.load(f)
    return set(data.get("seen_ids", []))


def save_seen_ids(seen_ids):
    data = {"seen_ids": list(seen_ids)}
    with open(SEEN_FILE, "w") as f:
        json.dump(data, f)


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    response = requests.post(url, json=payload)
    return response.json()


def fetch_today_nse_announcements():
    try:
        nse = NSE(download_folder="./")
        data = nse.announcements(index="equities")
        nse.exit()
        return data
    except Exception as e:
        print(f"NSE fetch failed (continuing with BSE only): {e}")
        return []


def get_lookback_start_date():
    from datetime import timedelta

    today = datetime.now()
    is_monday = today.weekday() == 0
    lookback_days = 3 if is_monday else 1
    return today - timedelta(days=lookback_days)


def fetch_today_announcements():
    bse = BSE(download_folder="./")
    all_rows = []
    page_no = 1
    total_count = None
    while True:
        data = bse.announcements(page_no=page_no)
        rows = data.get("Table", [])
        no_rows = len(rows) == 0
        if no_rows:
            break
        all_rows.extend(rows)
        if total_count is None:
            table1 = data.get("Table1", [])
            has_count = len(table1) > 0
            if has_count:
                total_count = table1[0].get("ROWCNT", len(all_rows))
        reached_total = total_count is not None and len(all_rows) >= total_count
        if reached_total:
            break
        page_no = page_no + 1
        too_many_pages = page_no > 60
        if too_many_pages:
            break
    bse.exit()
    return all_rows


def process_announcement_list(announcements, source_name, seen_ids):
    new_alerts_sent = 0
    new_alert_items = []
    ann_idx = 0
    while ann_idx < len(announcements):
        ann = announcements[ann_idx]
        if source_name == "BSE":
            ann_id = "BSE_" + str(ann.get("NEWSID", ""))
            headline = ann.get("HEADLINE", "")
            newssub = ann.get("NEWSSUB", "")
            detailed_text = ann.get("MORE", "")
            display_text = detailed_text if len(detailed_text) > len(headline) else headline
            if not display_text.strip() or display_text.strip() == "As per the attached intimation":
                display_text = newssub
            company = ann.get("SLONGNAME", "")
            category_name = ann.get("CATEGORYNAME", "")
            subcategory_name = ann.get("SUBCATNAME", "")
            ann.get("ATTACHMENTNAME", "")
        else:
            ann_id = "NSE_" + str(ann.get("seq_id", ""))
            headline = ann.get("attchmntText", "") or ann.get("desc", "")
            newssub = ""
            display_text = headline
            company = ann.get("sm_name", "") or ann.get("symbol", "")
            category_name = ann.get("desc", "")
            subcategory_name = ""
        already_seen = ann_id in seen_ids
        if already_seen:
            ann_idx = ann_idx + 1
            continue
        extra_text = newssub if source_name == "BSE" else ""
        categories = classify_announcement(headline + " " + extra_text, display_text, category_name, subcategory_name)
        is_relevant = len(categories) > 0
        if is_relevant:
            categories_str = ", ".join(categories)
            details = extract_key_details(display_text)
            is_order = "Order" in categories_str
            no_value_found = "order_value" not in details
            enriched_value = None
            if is_order and no_value_found:
                news_value = search_order_value_from_news(company)
                if news_value:
                    enriched_value = news_value + " (via news)"
                    details["order_value"] = enriched_value
            message = format_telegram_message_with_details(company, display_text, categories_str, source_name, details)
            send_result = send_telegram_message(message)
            send_succeeded = send_result.get("ok", False)
            if send_succeeded:
                new_alerts_sent = new_alerts_sent + 1
                seen_ids.add(ann_id)
                from datetime import timedelta

                ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                display_with_value = display_text[:500]
                if enriched_value:
                    display_with_value = f"[Value: {enriched_value.upper()}] " + display_with_value
                new_alert_items.append(
                    {
                        "date": ist_now.isoformat(),
                        "company": company,
                        "text": display_with_value,
                        "categories": categories_str,
                        "source": source_name,
                    }
                )
            else:
                print(f"FAILED to send alert for {ann_id}: {send_result}")
        else:
            seen_ids.add(ann_id)
        ann_idx = ann_idx + 1
    return new_alerts_sent, new_alert_items


ALERTS_LOG_FILE = "alerts_log.json"
DASHBOARD_FILE = "index.html"
KEEP_DAYS = 7


def load_alerts_log():
    file_exists = os.path.exists(ALERTS_LOG_FILE)
    if not file_exists:
        return []
    with open(ALERTS_LOG_FILE) as f:
        return json.load(f)


def save_alerts_log(alerts):
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
    recent = [a for a in alerts if datetime.fromisoformat(a["date"]) > cutoff]
    recent_sorted = sorted(recent, key=lambda x: x["date"], reverse=True)
    with open(ALERTS_LOG_FILE, "w") as f:
        json.dump(recent_sorted, f, indent=2)
    return recent_sorted


def generate_dashboard(alerts):
    from datetime import timedelta

    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    now = ist_now.strftime("%d %b %Y, %I:%M %p IST")
    rows = ""
    for a in alerts:
        dt = datetime.fromisoformat(a["date"])
        formatted_date = dt.strftime("%d %b %Y, %I:%M %p")
        category_color = {
            "Order/MoU/Contract": "#0ea5e9",
            "Regulatory/Drug Approval": "#10b981",
            "M&A/Corporate Action": "#f59e0b",
            "Litigation/Regulatory Action": "#ef4444",
            "Capacity/Expansion": "#8b5cf6",
            "Financial/Results": "#6366f1",
        }.get(a["categories"], "#64748b")
        safe_text = a["text"][:300] + ("..." if len(a["text"]) > 300 else "")
        rows += f"""<tr data-category="{a["categories"]}">
<td class="date">{formatted_date}</td>
<td class="company">{a["company"]}</td>
<td class="text">{safe_text}</td>
<td><span class="badge" style="background:{category_color}">{a["categories"]}</span></td>
<td><span class="source">{a["source"]}</span></td>
</tr>"""

    order_count = len([a for a in alerts if "Order" in a["categories"]])
    drug_count = len([a for a in alerts if "Drug" in a["categories"] or "Regulatory" in a["categories"]])
    ma_count = len([a for a in alerts if "M&A" in a["categories"]])
    tbody = rows if alerts else '<tr><td colspan="5" class="empty">No alerts in the last 7 days</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<meta http-equiv="refresh" content="300">
<title>Market Intelligence Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
.header {{ background: #1e293b; border-bottom: 1px solid #334155; padding: 20px 32px; display: flex; justify-content: space-between; align-items: center; }}
.header h1 {{ font-size: 20px; font-weight: 600; color: #f8fafc; letter-spacing: -0.3px; }}
.header h1 span {{ color: #38bdf8; }}
.updated {{ font-size: 12px; color: #64748b; }}
.stats {{ display: flex; gap: 16px; padding: 20px 32px; }}
.stat {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px 20px; flex: 1; cursor: pointer; transition: all 0.15s; user-select: none; }}
.stat:hover {{ border-color: #38bdf8; transform: translateY(-1px); }}
.stat.active {{ border-color: #38bdf8; background: #1a3a5c; }}
.stat-value {{ font-size: 28px; font-weight: 700; color: #38bdf8; }}
.stat-label {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
.filter-bar {{ padding: 0 32px 16px; display: flex; align-items: center; gap: 12px; }}
.filter-label {{ font-size: 12px; color: #64748b; }}
.reset-btn {{ padding: 4px 12px; border-radius: 6px; background: #334155; color: #94a3b8; border: none; font-size: 12px; cursor: pointer; display: none; }}
.reset-btn:hover {{ background: #475569; color: #e2e8f0; }}
.container {{ padding: 0 32px 32px; }}
.table-wrap {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; overflow: hidden; }}
table {{ width: 100%; border-collapse: collapse; }}
thead {{ background: #0f172a; }}
th {{ padding: 12px 16px; text-align: left; font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }}
td {{ padding: 14px 16px; border-top: 1px solid #263045; font-size: 13px; vertical-align: top; }}
tr:hover td {{ background: #263045; }}
tr.hidden {{ display: none; }}
.date {{ color: #64748b; font-size: 12px; white-space: nowrap; min-width: 130px; }}
.company {{ font-weight: 600; color: #f1f5f9; min-width: 180px; }}
.text {{ color: #94a3b8; line-height: 1.5; }}
.badge {{ display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; color: white; white-space: nowrap; }}
.source {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; background: #334155; color: #94a3b8; }}
.empty {{ text-align: center; padding: 60px; color: #64748b; }}
.no-results {{ display: none; text-align: center; padding: 60px; color: #64748b; }}
@media (max-width: 768px) {{ .stats {{ flex-direction: column; }} .filter-bar {{ padding: 0 16px 16px; }} .container {{ padding: 0 16px 16px; }} .header {{ padding: 16px; }} .stats {{ padding: 16px; }} }}
</style>
</head>
<body>
<div class="header">
<h1>Market <span>Intelligence</span> Dashboard</h1>
<span class="updated">Last updated: {now}</span>
</div>
<div class="stats">
<div class="stat" onclick="filterBy('all')" id="stat-all">
<div class="stat-value">{len(alerts)}</div>
<div class="stat-label">All Alerts (Last 7 Days)</div>
</div>
<div class="stat" onclick="filterBy('Order')" id="stat-order">
<div class="stat-value">{order_count}</div>
<div class="stat-label">Order Wins / Contracts</div>
</div>
<div class="stat" onclick="filterBy('Drug')" id="stat-drug">
<div class="stat-value">{drug_count}</div>
<div class="stat-label">Regulatory / Drug</div>
</div>
<div class="stat" onclick="filterBy('M&A')" id="stat-ma">
<div class="stat-value">{ma_count}</div>
<div class="stat-label">M&A / Corporate</div>
</div>
</div>
<div class="filter-bar">
<span class="filter-label" id="filter-label">Showing all alerts</span>
<button class="reset-btn" id="reset-btn" onclick="filterBy('all')">Show All</button>
</div>
<div class="container">
<div class="table-wrap">
<table>
<thead><tr><th>Time (IST)</th><th>Company</th><th>Announcement</th><th>Category</th><th>Source</th></tr></thead>
<tbody id="table-body">{tbody}</tbody>
</table>
<div class="no-results" id="no-results">No alerts match this filter</div>
</div>
</div>
<script>
var currentFilter = 'all';
function filterBy(category) {{
  currentFilter = category;
  var rows = document.querySelectorAll('#table-body tr');
  var visibleCount = 0;
  rows.forEach(function(row) {{
    var cat = row.getAttribute('data-category') || '';
    var show = category === 'all' || cat.indexOf(category) !== -1;
    row.classList.toggle('hidden', !show);
    if (show) visibleCount++;
  }});
  var stats = document.querySelectorAll('.stat');
  stats.forEach(function(s) {{ s.classList.remove('active'); }});
  var activeId = category === 'all' ? 'stat-all' : category === 'Order' ? 'stat-order' : category === 'Drug' ? 'stat-drug' : 'stat-ma';
  var activeEl = document.getElementById(activeId);
  if (activeEl) activeEl.classList.add('active');
  var label = document.getElementById('filter-label');
  var resetBtn = document.getElementById('reset-btn');
  var noResults = document.getElementById('no-results');
  if (category === 'all') {{
    label.textContent = 'Showing all alerts';
    resetBtn.style.display = 'none';
  }} else {{
    var names = {{'Order': 'Order Wins / Contracts', 'Drug': 'Regulatory / Drug', 'M&A': 'M&A / Corporate'}};
    label.textContent = 'Filtered: ' + (names[category] || category) + ' (' + visibleCount + ' alerts)';
    resetBtn.style.display = 'inline-block';
  }}
  noResults.style.display = visibleCount === 0 ? 'block' : 'none';
}}
document.getElementById('stat-all').classList.add('active');
</script>
</body>
</html>"""
    with open(DASHBOARD_FILE, "w") as f:
        f.write(html)


def run_scan():
    seen_ids = load_seen_ids()
    alerts_log = load_alerts_log()

    bse_announcements = fetch_today_announcements()
    print(f"Fetched {len(bse_announcements)} total announcements from BSE today.")
    bse_alerts, new_alert_items = process_announcement_list(bse_announcements, "BSE", seen_ids)

    nse_announcements = fetch_today_nse_announcements()
    print(f"Fetched {len(nse_announcements)} total announcements from NSE today.")
    nse_alerts, nse_alert_items = process_announcement_list(nse_announcements, "NSE", seen_ids)

    new_alert_items.extend(nse_alert_items)
    alerts_log.extend(new_alert_items)
    alerts_log = save_alerts_log(alerts_log)
    generate_dashboard(alerts_log)

    save_seen_ids(seen_ids)
    total_alerts = bse_alerts + nse_alerts
    print(f"Sent {total_alerts} new alerts ({bse_alerts} BSE, {nse_alerts} NSE).")
    timestamp = datetime.now().isoformat()
    print(f"Scan complete at {timestamp}")


run_scan()
