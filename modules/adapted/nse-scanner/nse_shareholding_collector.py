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


"""Incremental, point-in-time NSE shareholding XBRL collection.

The NSE listing is only an index; the XBRL document is the authoritative input
for a normalized record.  Listing history is versioned with normalized
snapshots so disposable GitHub Actions runners never need to rediscover an
already processed filing.
"""

import contextlib
import csv
import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from nse_historical_downloader import HEADERS

if TYPE_CHECKING:
    from collections.abc import Iterable

LISTING_URL = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&from_date={from_date}&to_date={to_date}"
RAW_ROOT = Path("corporate_data/raw/shareholding")
NORMALIZED_PATH = Path("corporate_data/normalized/shareholding_patterns.csv")
HISTORY_PATH = Path("corporate_data/normalized/shareholding_filing_history.csv")
NORMAL_COLUMNS = [
    "symbol",
    "as_of_date",
    "available_date",
    "shares_outstanding",
    "promoter_holding_pct",
    "public_holding_pct",
    "source",
    "filing_id",
]
HISTORY_COLUMNS = ["filing_id", "source_url", "listing_signature", "sha256", "status", "error", "processed_at"]


@dataclass
class CollectionResult:
    status: str
    listed: int = 0
    unseen: int = 0
    normalized: int = 0
    rejected: int = 0
    excluded: int = 0
    reused: int = 0
    error: str = ""


def _lname(value: str) -> str:
    return value.rsplit("}", 1)[-1].lower()


def _date(value: object) -> str:
    if value is None or str(value).strip() in {"", "-", "nan", "None"}:
        return ""
    parsed = datetime.strptime(str(value).strip().split(" ")[0], "%d-%b-%Y")
    return parsed.date().isoformat()


def _available(row: dict) -> tuple[str, bool]:
    for name in ("EXCHANGE DISSEMINATION TIME", "BROADCAST DATE/TIME", "SUBMISSION DATE"):
        value = row.get(name)
        if value and str(value).strip() not in {"-", "nan"}:
            return _date(value), name == "SUBMISSION DATE"
    msg = "listing has no available date"
    raise ValueError(msg)


def filing_id(source_url: str) -> str:
    name = source_url.rstrip("/").rsplit("/", 1)[-1]
    if not name.startswith("SHP_"):
        msg = "not an NSE shareholding XBRL URL"
        raise ValueError(msg)
    return name.removesuffix("_WEB.xml").removesuffix(".xml")


def _signature(row: dict) -> str:
    keys = (
        "ACTION",
        "AS ON DATE",
        "SUBMISSION DATE",
        "REVISION DATE",
        "BROADCAST DATE/TIME",
        "EXCHANGE DISSEMINATION TIME",
        "PROMOTER & PROMOTER GROUP (A)",
        "PUBLIC (B)",
    )
    return hashlib.sha256("|".join(str(row.get(k, "")).strip() for k in keys).encode()).hexdigest()


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, columns: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    # Windows Defender/indexers can briefly hold a just-written CSV.  Retrying
    # the atomic replace is safer than falling back to an in-place overwrite.
    last_error: OSError | None = None
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.1 * (attempt + 1))
    raise last_error or OSError(f"could not replace {path}")


def _request(url: str, session: requests.Session | None = None, retries: int = 3, timeout: int = 30) -> bytes:
    client = session or requests.Session()
    headers = {**HEADERS, "Accept": "application/json,text/plain,*/*", "Referer": "https://www.nseindia.com/"}
    error: Exception | None = None
    for attempt in range(retries):
        try:
            response = client.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            if not response.content:
                msg = "empty NSE response"
                raise ValueError(msg)
            return response.content
        except Exception as exc:  # preserve last valid data; caller reports degradation
            error = exc
            if attempt + 1 < retries:
                time.sleep(0.5 * (2**attempt))
    raise RuntimeError(str(error))


def _cached_xbrl(fid: str) -> bytes | None:
    """Return a previously validated raw payload without another NSE request."""
    for path in sorted(RAW_ROOT.glob(f"{fid}_*.xml"), reverse=True):
        try:
            content = path.read_bytes()
            if content:
                ET.fromstring(content)
                return content
        except (OSError, ET.ParseError):
            continue
    return None


def fetch_listing(start: date, end: date, session: requests.Session | None = None) -> list[dict]:
    template = os.getenv("NSE_SHAREHOLDING_LISTING_URL", LISTING_URL)
    url = template.format(from_date=start.strftime("%d-%m-%Y"), to_date=end.strftime("%d-%m-%Y"))
    payload = json.loads(_request(url, session=session).decode("utf-8"))
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        msg = "unexpected NSE shareholding listing schema"
        raise ValueError(msg)
    return [
        _normalize_listing_row(row) for row in rows if isinstance(row, dict) and (row.get("ACTION") or row.get("xbrl"))
    ]


def _normalize_listing_row(row: dict) -> dict:
    """Map NSE's current API schema to the archived CSV contract."""
    if "ACTION" in row:
        return dict(row)
    return {
        "COMPANY": row.get("name", ""),
        "PROMOTER & PROMOTER GROUP (A)": row.get("pr_and_prgrp", ""),
        "PUBLIC (B)": row.get("public_val", ""),
        "SHARES HELD BY EMPLOYEE TRUSTS (C2)": row.get("employeeTrusts", ""),
        "STATUS": row.get("revisedStatus") or row.get("desc", ""),
        "AS ON DATE": row.get("date", ""),
        "SUBMISSION DATE": row.get("submissionDate", ""),
        "REVISION DATE": row.get("revisionDate") or row.get("revisedDate", ""),
        "ACTION": row.get("xbrl", ""),
        "BROADCAST DATE/TIME": row.get("broadcastDate", ""),
        # NSE's list response calls its exchange-time field systemDate.
        "EXCHANGE DISSEMINATION TIME": row.get("systemDate", "") or row.get("cgTimeStamp", ""),
    }


def _fact_values(root: ET.Element, contexts: dict[str, str], terms: tuple[str, ...], context_hint: str) -> list[float]:
    values = []
    for node in root.iter():
        local = _lname(node.tag)
        if not all(term in local for term in terms) or context_hint not in contexts.get(
            node.attrib.get("contextRef", ""), ""
        ):
            continue
        with contextlib.suppress(ValueError):
            values.append(float((node.text or "").strip().replace(",", "")))
    return values


def parse_xbrl(content: bytes, listing: dict) -> dict:
    """Parse only aggregate ownership facts; never sum shareholder categories."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        msg = f"invalid XML: {exc}"
        raise ValueError(msg) from exc
    contexts = {
        node.attrib.get("id", ""): (
            node.attrib.get("id", "") + " " + " ".join((child.text or "") for child in node.iter())
        ).lower()
        for node in root.iter()
        if _lname(node.tag) == "context"
    }
    symbol = next(
        (
            str(node.text).strip().upper()
            for node in root.iter()
            if _lname(node.tag) in {"symbol", "nse_symbol", "symbolofcompany"} and (node.text or "").strip()
        ),
        "",
    )
    if not symbol:
        msg = "XBRL has no NSE symbol"
        raise ValueError(msg)
    promoter_contexts = [key for key, text in contexts.items() if "promoter" in text and "group" in text]
    public_contexts = [key for key, text in contexts.items() if "public" in text]

    def derive(context_ids: list[str]) -> tuple[float, float] | None:
        for context_id in context_ids:
            text_contexts = {context_id: contexts[context_id]}
            pct = _fact_values(
                root, text_contexts, ("shareholdingasapercentageoftotalnumberofshares",), contexts[context_id]
            )
            shares = _fact_values(root, text_contexts, ("numberof", "paid", "equityshares"), contexts[context_id])
            # Same-context facts are required.  Fully and partly-paid aggregate
            # quantities may both appear and are additive only at this aggregate level.
            if not pct or not shares:
                continue
            percentage = pct[0] * 100 if pct[0] <= 1 else pct[0]
            if percentage <= 0 or percentage > 100:
                continue
            quantity = sum(shares)
            return round(quantity / (percentage / 100)), percentage
        return None

    promoter = derive(promoter_contexts)
    public = derive(public_contexts)
    chosen = promoter if promoter and promoter[1] > 0 else public
    if not chosen:
        msg = "no compatible aggregate ownership context"
        raise ValueError(msg)
    total, _ = chosen
    listed_promoter = float(str(listing.get("PROMOTER & PROMOTER GROUP (A)", "")).replace(",", ""))
    listed_public = float(str(listing.get("PUBLIC (B)", "")).replace(",", ""))
    if promoter and abs(promoter[1] - listed_promoter) > 0.05:
        msg = "promoter percentage differs from NSE listing"
        raise ValueError(msg)
    if public and abs(public[1] - listed_public) > 0.05:
        msg = "public percentage differs from NSE listing"
        raise ValueError(msg)
    if promoter and public and abs(promoter[0] - public[0]) / total > 0.005:
        msg = "aggregate ownership contexts imply inconsistent total shares"
        raise ValueError(msg)
    available, degraded = _available(listing)
    return {
        "symbol": symbol,
        "as_of_date": _date(listing["AS ON DATE"]),
        "available_date": available,
        "shares_outstanding": int(total),
        "promoter_holding_pct": listed_promoter,
        "public_holding_pct": listed_public,
        "source": "NSE_SHAREHOLDING_XBRL" + ("_SUBMISSION_DATE" if degraded else ""),
        "filing_id": filing_id(str(listing["ACTION"])),
    }


def collect(
    *,
    db_path: str | None = None,
    as_of: date | None = None,
    days: int = 7,
    csv_fallback: Path | None = None,
    limit: int | None = None,
    session: requests.Session | None = None,
    output_path: Path | None = None,
    start_date: date | None = None,
) -> CollectionResult:
    as_of = as_of or date.today()
    output_path = output_path or NORMALIZED_PATH
    history = _read_csv(HISTORY_PATH) if HISTORY_PATH.exists() else []
    known = {
        (row["filing_id"], row["source_url"], row.get("listing_signature", ""))
        for row in history
        if row.get("status") == "VALID"
    }
    fallback_used = False
    try:
        listing = fetch_listing(start_date or as_of - timedelta(days=days), as_of, session)
    except Exception as exc:
        if not csv_fallback or not csv_fallback.exists():
            return CollectionResult("REUSED_LAST_VALID" if output_path.exists() else "DEGRADED", error=str(exc))
        try:
            listing = _read_csv(csv_fallback)
            fallback_used = True
        except Exception as fallback_exc:
            return CollectionResult(
                "REUSED_LAST_VALID" if output_path.exists() else "DEGRADED",
                error=f"listing={exc}; fallback={fallback_exc}",
            )
    eligible = []
    for row in listing:
        try:
            available, _ = _available(row)
            if available and available <= as_of.isoformat():
                eligible.append(row)
        except Exception:
            continue
    candidates = []
    candidate_keys = set()
    excluded = len(listing) - len(eligible)
    for row in eligible:
        try:
            key = (filing_id(str(row["ACTION"])), str(row["ACTION"]), _signature(row))
        except ValueError:
            # Listing responses occasionally contain ACTION="-".  It is not
            # a filing and cannot be normalized safely.
            excluded += 1
            continue
        if key not in known and key not in candidate_keys:
            candidates.append(row)
            candidate_keys.add(key)
    if limit is not None:
        candidates = candidates[:limit]
    if not candidates:
        status = "DEGRADED" if (fallback_used or excluded) and not output_path.exists() else "NO_NEW_FILINGS"
        return CollectionResult(status, listed=len(listing), reused=len(eligible), excluded=excluded)
    records: list[dict] = []
    additions: list[dict] = []
    rejected = 0
    throttle_seconds = max(0.0, float(os.getenv("NSE_SHAREHOLDING_THROTTLE_SECONDS", "0.2")))
    old = _read_csv(output_path) if output_path.exists() else []
    merged = {(row["symbol"], row["as_of_date"]): row for row in old}
    for index, row in enumerate(candidates):
        url = str(row["ACTION"]).strip()
        fid = filing_id(url)
        try:
            if not url.startswith("https://nsearchives.nseindia.com/"):
                msg = "XBRL host is not nsearchives.nseindia.com"
                raise ValueError(msg)
            content = _cached_xbrl(fid) or _request(url, session=session)
            ET.fromstring(content)  # validate before caching
            digest = hashlib.sha256(content).hexdigest()
            raw = RAW_ROOT / f"{fid}_{digest[:12]}.xml"
            raw.parent.mkdir(parents=True, exist_ok=True)
            if not raw.exists():
                raw.write_bytes(content)
            record = parse_xbrl(content, row)
            records.append(record)
            key = (record["symbol"], record["as_of_date"])
            if key not in merged or record["available_date"] >= merged[key]["available_date"]:
                merged[key] = record
            # A successful filing is durable before it is marked known.  This
            # gives a stopped bootstrap an immediate, no-redownload resume point.
            _write_csv(
                output_path,
                NORMAL_COLUMNS,
                sorted(merged.values(), key=lambda item: (item["symbol"], item["as_of_date"])),
            )
            additions.append(
                {
                    "filing_id": fid,
                    "source_url": url,
                    "listing_signature": _signature(row),
                    "sha256": digest,
                    "status": "VALID",
                    "error": "",
                    "processed_at": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as exc:
            rejected += 1
            additions.append(
                {
                    "filing_id": fid,
                    "source_url": url,
                    "listing_signature": _signature(row),
                    "sha256": "",
                    "status": "REJECTED",
                    "error": str(exc),
                    "processed_at": datetime.now(UTC).isoformat(),
                }
            )
        _write_csv(HISTORY_PATH, HISTORY_COLUMNS, history + additions)
        if throttle_seconds and index + 1 < len(candidates):
            time.sleep(throttle_seconds)
    # A rejected retry must remain eligible next run, while audit history is kept.
    if records:
        if db_path:
            from scripts.import_nse_corporate_data import import_rows

            import_rows(db_path, "shareholding", str(output_path))
    return CollectionResult(
        "FRESH" if records else ("REUSED_LAST_VALID" if output_path.exists() else "DEGRADED"),
        len(listing),
        len(candidates),
        len(records),
        rejected,
        excluded,
    )
