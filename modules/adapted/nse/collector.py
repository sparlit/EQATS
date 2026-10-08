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


import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nse import NSE

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
RESULTS_FILE = DATA / "results.json"
CACHE = ROOT / ".nse_cache"
CACHE.mkdir(exist_ok=True)

SLEEP_SECONDS = 0.75
RETRIES = 3


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("₹", "").replace("%", "")
    if s in ("", "-", "—", "NA", "N/A", "None"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def pick(row, keys):
    for k in keys:
        if isinstance(row, dict) and k in row and row[k] not in (None, "", "-"):
            return row[k]
    return None


def bootstrap_companies(nse):
    """
    Do not require data/companies.json to already exist.
    GitHub Actions can create the Nifty 500 master directly from NSE.
    """
    print("Loading current NIFTY 500 constituents from NSE...", flush=True)
    payload = nse.listEquityStocksByIndex(index="NIFTY 500")
    rows = payload.get("data", []) if isinstance(payload, dict) else []

    if not rows:
        raise RuntimeError("NSE returned no NIFTY 500 constituents")

    companies = []
    for i, row in enumerate(rows, 1):
        symbol = pick(row, ["symbol", "Symbol"])
        name = pick(row, ["companyName", "companyname", "Company Name", "meta", "name"]) or symbol
        industry = pick(row, ["industry", "Industry"]) or ""
        isin = pick(row, ["isin", "ISIN", "isinCode"]) or ""
        if symbol:
            companies.append(
                {
                    "sl": i,
                    "company": str(name).strip(),
                    "industry": str(industry).strip(),
                    "symbol": str(symbol).strip(),
                    "isin": str(isin).strip(),
                }
            )

    if len(companies) < 450:
        raise RuntimeError(
            f"NSE NIFTY 500 response unexpectedly contains only {len(companies)} stocks"
        )

    (DATA / "companies.json").write_text(
        json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Created data/companies.json with {len(companies)} companies", flush=True)
    return companies


def load_old():
    if not RESULTS_FILE.exists():
        return {}
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8")).get("results", {})
    except Exception:
        return {}


def comparison_rows(payload):
    rows = payload.get("resCmpData") or payload.get("data") or []
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        out.append(
            {
                "period_end": pick(
                    row, ["re_to_dt", "re_to_date", "toDate", "periodEnded", "period_end"]
                ),
                "sales_lakh": num(
                    pick(
                        row,
                        [
                            "re_total_inc",
                            "re_total_income",
                            "re_revenue",
                            "re_total_revenue",
                            "totalIncome",
                        ],
                    )
                ),
                "net_profit_lakh": num(
                    pick(row, ["re_net_profit", "re_profit_after_tax", "re_pat", "netProfit"])
                ),
                "eps": num(pick(row, ["re_eps", "re_diluted_eps", "re_basic_eps", "eps"])),
                "tax_lakh": num(pick(row, ["re_tax", "re_tax_expense", "tax", "taxExpense"])),
                "other_income_lakh": num(
                    pick(row, ["re_other_income", "other_income", "otherIncome"])
                ),
            }
        )
    return out


def normalize_filings(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "financialResults", "financial_results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def filing_date(item):
    if not isinstance(item, dict):
        return None
    return (
        item.get("re_broadcast_timestamp")
        or item.get("broadcastDate")
        or item.get("broadcastdate")
        or item.get("broadcast_date")
        or item.get("filingDate")
        or item.get("filing_date")
    )


def latest_filing(filings):
    filings = normalize_filings(filings)
    if not filings:
        return None
    return (
        sorted(
            [x for x in filings if isinstance(x, dict)],
            key=lambda x: str(filing_date(x) or x.get("toDate") or x.get("periodEnded") or ""),
            reverse=True,
        )[0]
        if filings
        else None
    )


def latest_xbrl(filings):
    item = latest_filing(filings)
    if not item:
        return None
    for k in ("xbrl", "xbrlUrl", "xbrlURL", "xbrl_link", "xbrl_attachment"):
        if item.get(k):
            return item[k]
    return None


def xbrl_enrichment(url, nse):
    if not url:
        return {}
    try:
        path = nse.download_document(url, folder=CACHE)
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"    XBRL skipped: {e}", flush=True)
        return {}

    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)

    def find_amount(names):
        pattern = r"(?:{})[^0-9\-\(]{{0,180}}(\(?-?\d[\d,]*(?:\.\d+)?\)?)".format(
            "|".join(re.escape(x) for x in names)
        )
        m = re.search(pattern, text, re.I)
        if not m:
            return None
        v = m.group(1).replace(",", "")
        neg = v.startswith("(") and v.endswith(")")
        v = v.strip("()")
        try:
            x = float(v)
            return -x if neg else x
        except Exception:
            return None

    out = {}
    tax = find_amount(["TaxExpense", "IncomeTaxExpense", "CurrentTax", "TaxExpenseCurrent"])
    other = find_amount(["OtherIncome", "OtherIncomeFromOperations", "OtherIncomeExpense"])
    if tax is not None:
        out["tax_lakh"] = tax
    if other is not None:
        out["other_income_lakh"] = other
    return out


old = load_old()
results = {}
ok = 0
failed = 0

print("Starting automatic NSE Nifty 500 update", flush=True)

with NSE(download_folder=CACHE, server=True, timeout=30) as nse:
    # THIS fixes the current GitHub error:
    # data/companies.json is generated automatically if missing.
    companies_file = DATA / "companies.json"
    if companies_file.exists():
        try:
            companies = json.loads(companies_file.read_text(encoding="utf-8"))
            if len(companies) < 450:
                companies = bootstrap_companies(nse)
        except Exception:
            companies = bootstrap_companies(nse)
    else:
        companies = bootstrap_companies(nse)

    total = len(companies)
    print(f"Updating {total} companies", flush=True)

    for i, company in enumerate(companies, 1):
        symbol = company["symbol"]
        previous = old.get(symbol, {})

        rec = {
            "sl": company["sl"],
            "company": company["company"],
            "industry": company.get("industry", ""),
            "symbol": symbol,
            "isin": company.get("isin", ""),
            "status": "error",
            "periods": previous.get("periods", []),
            "source": "NSE India",
            "source_url": f"https://www.nseindia.com/companies-listing/corporate-filings-financial-results?symbol={symbol}&tabIndex=equity",
            "fetched_at": datetime.now(UTC).isoformat(),
        }

        success = False

        for attempt in range(RETRIES):
            try:
                # Use NSE Financial Results filings as the PRIMARY source.
                # This is important because a result filed in August 2026
                # has a reporting period of 30-Jun-2026.
                filings_payload = nse.financial_results(
                    segment="equities",
                    period="quarterly",
                    symbol=symbol,
                    from_date=datetime.now() - timedelta(days=120),
                    to_date=datetime.now(),
                )
                filings = normalize_filings(filings_payload)
                lf = latest_filing(filings)

                periods = []
                if lf:
                    period_end = pick(
                        lf,
                        [
                            "to_date",
                            "toDate",
                            "periodEnded",
                            "period_end",
                            "re_to_dt",
                            "re_to_date",
                        ],
                    )
                    broadcast = filing_date(lf)

                    primary = {
                        "period_end": period_end,
                        "broadcast_date": broadcast,
                        "sales_lakh": num(
                            pick(
                                lf,
                                [
                                    "income",
                                    "re_total_inc",
                                    "re_total_income",
                                    "re_revenue",
                                    "totalIncome",
                                ],
                            )
                        ),
                        "net_profit_lakh": num(
                            pick(
                                lf,
                                [
                                    "proLossAftTax",
                                    "re_net_profit",
                                    "re_profit_after_tax",
                                    "re_pat",
                                    "netProfit",
                                ],
                            )
                        ),
                        "eps": num(
                            pick(
                                lf, ["reDilEPS", "re_eps", "re_diluted_eps", "re_basic_eps", "eps"]
                            )
                        ),
                        "tax_lakh": num(
                            pick(lf, ["re_tax", "re_tax_expense", "tax", "taxExpense"])
                        ),
                        "other_income_lakh": num(
                            pick(lf, ["re_other_income", "other_income", "otherIncome"])
                        ),
                    }
                    periods.append(primary)

                    if broadcast:
                        rec["broadcast_date"] = broadcast
                    if lf.get("consolidated") is not None:
                        rec["consolidated"] = lf.get("consolidated")
                    if lf.get("audited") is not None:
                        rec["audited"] = lf.get("audited")

                    xurl = latest_xbrl(filings)
                    if xurl:
                        rec["xbrl_url"] = xurl
                        enrichment = xbrl_enrichment(xurl, nse)
                        for k, v in enrichment.items():
                            if periods[0].get(k) is None:
                                periods[0][k] = v

                # Fallback to Results Comparison if no filing row was returned.
                if not periods:
                    cmp = nse.results_comparison(symbol)
                    periods = comparison_rows(cmp)

                rec["periods"] = periods
                rec["status"] = "ok"
                success = True
                ok += 1
                break

            except Exception as e:
                rec["error"] = str(e)
                if attempt < RETRIES - 1:
                    time.sleep(2 + attempt * 2)

        if not success:
            failed += 1
            if previous:
                rec = previous.copy()
                rec["status"] = "stale"
                rec["fetched_at"] = datetime.now(UTC).isoformat()

        results[symbol] = rec
        print(f"[{i}/{total}] {symbol}: {rec['status']}", flush=True)
        time.sleep(SLEEP_SECONDS)

payload = {
    "updated_at": datetime.now(UTC).isoformat(),
    "source": "NSE India",
    "count": len(results),
    "results": results,
    "stats": {"ok": ok, "failed": failed},
}

tmp = RESULTS_FILE.with_suffix(".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(RESULTS_FILE)

print(f"FINISHED: {ok} successful, {failed} failed", flush=True)
