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


# -*- coding: utf-8 -*-
"""FREE vision reader for insurer P&L via Google Gemini (free tier — no billing, no card).

Insurers whose IRDAI filings the text parser can't crack (scanned/image P&L tables like ICICIGI/
STARHEALTH/LIC, or with-subsidiary owners-profit that's computed across rows like GICRE/NIACL/ICICIPRULI/
MFSL) are read by Gemini vision instead. Reads BOTH the current and the year-ago quarter (con + std) so
the caller can ANCHOR the read against our stored same-quarter-last-year con — never store an unanchored
guess. Gemini's free tier (aistudio.google.com key) is ~1,500 req/day; we use ~7/quarter → always free.

REST via stdlib urllib (no extra pip dep). Needs GEMINI_API_KEY in the environment (a repo secret in CI).
Returns None when the key is absent, so the daily job degrades gracefully to text-only.

Public: read_insurer(company, cur_label, yago_label, pngs, with_subsidiary)
    -> {"ok","company_matches","has_subsidiary","cur":{"con","std"},"yago":{"con","std"},"note"} | None
       (all PAT in Rs CRORE, owner-attributable for con)
"""
import base64
import contextlib
import json
import os
import re
import time
import urllib.error
import urllib.request

# 2026-09-05: models/gemini-2.0-flash answers HTTP 404 "no longer available … use models/gemini-3.6-flash"
# (measured in refresh-kpi-insights run 33988019640) — every caller was silently falling back to text-only.
_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
_PACE = {"last": 0.0}  # min spacing between calls to stay under the free-tier per-minute limit
_MIN_INTERVAL = 5.0
_URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ok": {"type": "BOOLEAN"},
        "company_matches": {"type": "BOOLEAN"},
        "has_subsidiary": {"type": "BOOLEAN"},
        "cur_con": {"type": "NUMBER", "nullable": True},
        "cur_std": {"type": "NUMBER", "nullable": True},
        "yago_con": {"type": "NUMBER", "nullable": True},
        "yago_std": {"type": "NUMBER", "nullable": True},
        "note": {"type": "STRING"},
    },
    "required": ["ok", "company_matches", "has_subsidiary", "cur_con", "yago_con", "cur_std", "yago_std", "note"],
}

_PROMPT = """These images are the quarterly results filing of an Indian INSURANCE company: %(company)s.
Insurers file in IRDAI format, NOT a standard P&L. Read the images (some are scanned).

Return PROFIT AFTER TAX (net profit), in Rs CRORE, for:
  - the CURRENT quarter %(cur)s  -> cur_con (consolidated) and cur_std (standalone)
  - the YEAR-AGO quarter %(yago)s -> yago_con and yago_std

WHICH ROW (this is where mistakes happen):
- Use the SHAREHOLDERS' Profit & Loss Account row "Profit AFTER tax" (a.k.a. "Profit for the period" in
  the Shareholders' A/c) — it comes after "Profit before tax" -> "Provision for tax".
- DO NOT use: "Operating Profit/(loss)" or "Operating Profit transferred to P&L" (that is the
  Policyholders' Revenue A/c), "Profit carried to Balance Sheet" (accumulated retained earnings, a huge
  cumulative number), segment results, or any "Net profit margin" ratio.
- CONSOLIDATED (con): if the company has subsidiaries/associates/minority, use OWNER-ATTRIBUTABLE profit —
  the "attributable to: Owners / Equity holders of the parent" line if present, else (total profit after
  tax) + (minority/non-controlling interest, with sign) + (share of profit of associates). For companies
  reporting continuing + discontinued operations, con = the TOTAL owners profit (sum of both).
- STANDALONE (std): the standalone Shareholders' A/c Profit after tax. If the filing shows only ONE
  statement, put that value in BOTH cur_std and cur_con and set has_subsidiary=false.

UNIT — convert to Rs CRORE: "in Lakhs" ÷100; "in Thousands" ÷100000; "in Millions" ÷10; "in Crores" keep;
bare Rupees ÷10000000. A quarterly insurer net profit is tens to a few thousand crore.

IDENTITY: if these images are NOT %(company)s or you can't find the Shareholders' P&L, set
company_matches=false (or ok=false) and null every figure. Losses are negative. Return ONLY the JSON."""


def _reason(body_txt):
    """Pull the human-readable status/message out of a Gemini error JSON body (for the CI log)."""
    try:
        e = json.loads(body_txt).get("error", {})
        return "{}: {}".format(e.get("status", "?"), (e.get("message", "") or "")[:140])
    except Exception:
        return (body_txt or "")[:140]


def _key():
    return os.environ.get("GEMINI_API_KEY")


_QUOTA = {"dead": False}  # set when the free-tier daily quota is exhausted (429 after retry)


def quota_dead():
    """True once the daily quota is exhausted — callers should stop queuing vision work
    (and NOT count the miss as a real extraction attempt)."""
    return _QUOTA["dead"]


def _post(body):
    """Paced, 429-retrying Gemini POST -> parsed JSON dict from the model, or None."""
    key = _key()
    if not key or _QUOTA["dead"]:
        return None
    data = json.dumps(body).encode()
    for attempt in range(2):  # fail-fast: 1 retry only, capped backoff (never hang CI)
        wait = _MIN_INTERVAL - (time.time() - _PACE["last"])  # pace: keep calls >= _MIN_INTERVAL apart
        if wait > 0:
            time.sleep(wait)
        _PACE["last"] = time.time()
        req = urllib.request.Request(
            _URL % (_MODEL, key), data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            raw = urllib.request.urlopen(req, timeout=90).read()
            resp = json.loads(raw)
            txt = resp["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(txt)
        except urllib.error.HTTPError as ex:
            body_txt = ""
            with contextlib.suppress(Exception):
                body_txt = ex.read().decode("utf-8", "replace")
            if ex.code == 429 and attempt == 0:
                m = re.search(r'"retryDelay":\s*"(\d+)s"', body_txt)
                delay = min(int(m.group(1)) + 2, 15) if m else 12  # capped so the run can't hang
                print("    gemini 429 — retry in %ds. reason: %s" % (delay, _reason(body_txt)))
                time.sleep(delay)
                continue
            if ex.code == 429:  # 429 again after backoff = DAILY quota exhausted
                _QUOTA["dead"] = True  # -> stop all further vision calls this run
                print("    gemini DAILY QUOTA EXHAUSTED — vision disabled for the rest of this run")
            print("    gemini err: HTTP %d — %s" % (ex.code, _reason(body_txt)))
            return None
        except Exception as ex:
            print("    gemini err:", str(ex)[:110])
            return None
    return None


_CORP_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ok": {"type": "BOOLEAN"},
        "company_matches": {"type": "BOOLEAN"},
        "cur_std": {"type": "NUMBER", "nullable": True},
        "cur_con": {"type": "NUMBER", "nullable": True},
        "prec_std": {"type": "NUMBER", "nullable": True},
        "prec_con": {"type": "NUMBER", "nullable": True},
        "yago_std": {"type": "NUMBER", "nullable": True},
        "yago_con": {"type": "NUMBER", "nullable": True},
        "note": {"type": "STRING"},
    },
    "required": ["ok", "company_matches", "cur_std", "cur_con", "prec_std", "prec_con", "yago_std", "yago_con", "note"],
}

_CORP_PROMPT = """These images are pages of a standard SEBI quarterly financial-results filing of the
Indian listed company: %(company)s. Some pages may be scanned. Read the results TABLE.

Return NET PROFIT AFTER TAX, in Rs CRORE, from the THREE-MONTHS columns for:
  - the quarter ended %(cur)s   -> cur_std (standalone) and cur_con (consolidated)
  - the quarter ended %(prec)s  -> prec_std and prec_con   (the "preceding 3 months" column)
  - the quarter ended %(yago)s  -> yago_std and yago_con   (the "corresponding 3 months of previous year" column)

WHICH COLUMN (this is where mistakes happen): the table also has "year to date" and "year ended"
columns whose end dates can EQUAL the dates above. Use ONLY the columns headed "3 months ended" /
"Quarter ended". If a period has no 3-months column, return null for it — never substitute a
YTD/annual figure.

WHICH ROW: "Profit/(Loss) for the period" a.k.a. "Profit after tax" (comes after "Total tax
expense"). On a CONSOLIDATED statement use the OWNER-ATTRIBUTABLE profit — the "attributable to:
Owners of the parent / Equity holders" line if printed; else (profit after tax) minus
(non-controlling / minority interest). DO NOT use: profit before tax, total comprehensive income,
segment results, or EPS. If the filing has only ONE statement, put its values in BOTH _std and _con.

UNIT — convert to Rs CRORE: "in Lakhs" ÷100; "in Millions" ÷10; "in Thousands" ÷100000;
"in Crores" keep; bare Rupees ÷10000000. Losses are NEGATIVE (figures in brackets are negative).

IDENTITY: if these images are NOT %(company)s or you cannot find the results table, set
company_matches=false (or ok=false) and null every figure. Return ONLY the JSON."""


def read_corp_results(company, cur_label, prec_label, yago_label, pngs):
    """Standard (non-insurer) SEBI results table: PAT std+con for the current / preceding / year-ago
    3-month columns, in Rs crore, owners-attributable for con. Caller MUST anchor cur_* against the
    stored XBRL value before trusting prec/yago. Returns
    {"ok","company_matches","cur":{...},"prec":{...},"yago":{...},"note"} | None."""
    key = _key()
    if not key or not pngs:
        return None
    parts = [
        {"inline_data": {"mime_type": "image/png", "data": base64.standard_b64encode(p).decode()}} for p in pngs[:6]
    ]
    parts.append(
        {"text": _CORP_PROMPT % {"company": company, "cur": cur_label, "prec": prec_label, "yago": yago_label}}
    )
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "response_mime_type": "application/json",
            "response_schema": _CORP_SCHEMA,
        },
    }
    d = _post(body)
    if d is None:
        return None
    return {
        "ok": bool(d.get("ok")),
        "company_matches": bool(d.get("company_matches")),
        "cur": {"std": d.get("cur_std"), "con": d.get("cur_con")},
        "prec": {"std": d.get("prec_std"), "con": d.get("prec_con")},
        "yago": {"std": d.get("yago_std"), "con": d.get("yago_con")},
        "note": d.get("note", ""),
    }


def read_insurer(company, cur_label, yago_label, pngs, with_subsidiary=True):
    """pngs: list of PNG byte strings (rendered P&L pages). Returns the normalized dict or None."""
    key = _key()
    if not key or not pngs:
        return None
    parts = [
        {"inline_data": {"mime_type": "image/png", "data": base64.standard_b64encode(p).decode()}} for p in pngs[:6]
    ]
    parts.append({"text": _PROMPT % {"company": company, "cur": cur_label, "yago": yago_label}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0, "response_mime_type": "application/json", "response_schema": _SCHEMA},
    }
    d = _post(body)
    if d is None:
        return None
    return {
        "ok": bool(d.get("ok")),
        "company_matches": bool(d.get("company_matches")),
        "has_subsidiary": bool(d.get("has_subsidiary")),
        "cur": {"con": d.get("cur_con"), "std": d.get("cur_std")},
        "yago": {"con": d.get("yago_con"), "std": d.get("yago_std")},
        "note": d.get("note", ""),
    }
