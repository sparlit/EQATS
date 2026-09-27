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


"""NSE ingestion service: MCP tool calls -> raw store -> canonical contracts.

Flow for every acquisition:
    1. call MCP tool
    2. persist the exact response payload to RawStore (immutable, hashed)
    3. parse into canonical contracts carrying lineage (raw_hash, timestamps)
"""


import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from indian_quant.ingestion.mcp.client import NseBseMcpClient, new_request_id
from indian_quant.ingestion.nse.parsing import (
    CANDIDATE_OHLC,
    CANDIDATE_TS_FIELDS,
    extract_record_list,
    parse_candle_rows,
    parse_date,
    parse_float,
    parse_timestamp,
)
from indian_quant.schemas import (
    Announcement,
    CorporateAction,
    CorporateActionType,
    Exchange,
    MarketBar,
    Segment,
    Timeframe,
    make_instrument_id,
)

if TYPE_CHECKING:
    from indian_quant.storage.metadata import MetadataStore
    from indian_quant.storage.raw_store import RawStore


class NseIngestionService:
    source = "NSE"

    def __init__(
        self,
        client: NseBseMcpClient,
        raw_store: RawStore,
        metadata: MetadataStore | None = None,
    ) -> None:
        self.client = client
        self.raw_store = raw_store
        self.metadata = metadata

    def _persist_raw(self, tool: str, payload: Any, request_meta: dict[str, Any]) -> tuple[bytes, str]:
        body = json.dumps(payload, sort_keys=True, default=str).encode()
        _, digest = self.raw_store.save(
            source=self.source,
            tool=tool,
            payload=body,
            request_meta=request_meta,
        )
        return body, digest

    def _run_tool(self, tool: str, arguments: dict[str, Any]) -> tuple[Any, str]:
        job_id = new_request_id()
        if self.metadata:
            self.metadata.start_job(job_id, tool=tool, source=self.source, params=arguments)
        try:
            payload = self.client.call_tool(tool, arguments)
            _, digest = self._persist_raw(tool, payload, {"tool": tool, **arguments})
        except Exception as exc:
            if self.metadata:
                self.metadata.finish_job(job_id, status="FAILED", error=str(exc))
            raise
        if self.metadata:
            self.metadata.finish_job(job_id, status="OK", raw_hash=digest)
        return payload, digest

    def equity_historical(
        self,
        symbol: str,
        from_date: date | str,
        to_date: date | str,
        *,
        series: str = "EQ",
    ) -> list[MarketBar]:
        from_s = from_date.isoformat() if isinstance(from_date, date) else from_date
        to_s = to_date.isoformat() if isinstance(to_date, date) else to_date
        payload, raw_hash = self._run_tool(
            "nse_equity_historical",
            {"symbol": symbol.upper(), "from_date": from_s, "to_date": to_s, "series": series},
        )
        records = extract_record_list(payload)
        if not records and isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list) and value and isinstance(value[0], list):
                    records = parse_candle_rows(value)
                    break

        instrument_id = make_instrument_id(Exchange.NSE, Segment.EQ, symbol.upper())
        bars: list[MarketBar] = []
        for rec in records:
            ts = parse_timestamp(_first(rec, CANDIDATE_TS_FIELDS))
            o = parse_float(_first(rec, CANDIDATE_OHLC["open"]))
            h = parse_float(_first(rec, CANDIDATE_OHLC["high"]))
            low = parse_float(_first(rec, CANDIDATE_OHLC["low"]))
            c = parse_float(_first(rec, CANDIDATE_OHLC["close"]))
            v = parse_float(_first(rec, CANDIDATE_OHLC["volume"])) or 0.0
            if ts is None or o is None or h is None or low is None or c is None:
                continue
            bars.append(
                MarketBar(
                    instrument_id=instrument_id,
                    exchange=Exchange.NSE.value,
                    timestamp=ts,
                    timeframe=Timeframe.DAY,
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    volume=v,
                    source=self.source,
                    source_timestamp=ts,
                    ingestion_timestamp=datetime.now(UTC),
                    raw_hash=raw_hash,
                )
            )
        return bars

    def corporate_actions(
        self,
        symbol: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> list[CorporateAction]:
        args: dict[str, Any] = {}
        if symbol:
            args["symbol"] = symbol.upper()
        if from_date:
            args["from_date"] = from_date.isoformat() if isinstance(from_date, date) else from_date
        if to_date:
            args["to_date"] = to_date.isoformat() if isinstance(to_date, date) else to_date
        payload, raw_hash = self._run_tool("nse_corporate_actions", args)

        actions: list[CorporateAction] = []
        for rec in extract_record_list(payload):
            sym = rec.get("symbol") or rec.get("SYMBOL") or symbol or "UNKNOWN"
            action_type = _classify_action(rec)
            if action_type is None:
                continue
            inst_id = make_instrument_id(Exchange.NSE, Segment.EQ, str(sym).upper())
            subject_text = _first(rec, ["subject", "desc", "purpose"])
            actions.append(
                CorporateAction(
                    instrument_id=inst_id,
                    isin=rec.get("isin") or rec.get("ISIN"),
                    action_type=action_type,
                    announcement_date=parse_date(_first(rec, ["date", "DATE", "exDate", "dt"])),
                    record_date=parse_date(_first(rec, ["recordDate", "recDate"])),
                    ex_date=parse_date(_first(rec, ["exDate", "exDt"])),
                    amount=parse_float(_first(rec, ["rate", "amount", "dividend", "divRate"]))
                    or dividend_amount_from_subject(str(subject_text) if subject_text else None),
                    ratio=_parse_ratio(_first(rec, ["bv", "bonus", "ratio"])),
                    old_value=parse_float(_first(rec, ["fvFrom", "oldFv", "from"])),
                    new_value=parse_float(_first(rec, ["fvTo", "newFv", "to"])),
                    source=self.source,
                    source_id=str(rec.get("seqId") or rec.get("bmSeqId") or ""),
                    document_url=_first(rec, ["attachmentURL", "url"]) or None,
                    source_timestamp=parse_timestamp(_first(rec, ["lastUpdatedOn", "ts"])),
                    ingestion_timestamp=datetime.now(UTC),
                    raw_payload_hash=raw_hash,
                    extra={k: v for k, v in rec.items() if k not in _KNOWN_ACTION_KEYS},
                )
            )
        return actions

    def corporate_announcements(
        self,
        symbol: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> list[Announcement]:
        args: dict[str, Any] = {}
        if symbol:
            args["symbol"] = symbol.upper()
        if from_date:
            args["from_date"] = from_date.isoformat() if isinstance(from_date, date) else from_date
        if to_date:
            args["to_date"] = to_date.isoformat() if isinstance(to_date, date) else to_date
        payload, raw_hash = self._run_tool("nse_corporate_announcements", args)

        announcements: list[Announcement] = []
        for i, rec in enumerate(extract_record_list(payload)):
            sym = rec.get("symbol") or rec.get("SYMBOL") or symbol or "UNKNOWN"
            published = parse_timestamp(
                _first(rec, ["sort_date", "sortDate", "an_dt", "exchdisstime", "date", "publishedAt"])
            )
            if published is None:
                continue
            announcements.append(
                Announcement(
                    announcement_id=f"{sym}-{int(published.timestamp())}-{i}",
                    instrument_id=make_instrument_id(Exchange.NSE, Segment.EQ, str(sym).upper()),
                    exchange=Exchange.NSE.value,
                    published_at=published,
                    event_date=published.date(),
                    category=_first(rec, ["attchmntText", "category"]) or None,
                    headline=str(_first(rec, ["desc", "attchmntText", "subject"]) or ""),
                    description=_first(rec, ["attchmntText", "description"]),
                    document_url=_first(rec, ["attchmntFile", "fileUrl"]),
                    source=self.source,
                    source_timestamp=published,
                    ingestion_timestamp=datetime.now(UTC),
                    raw_document_hash=raw_hash,
                    extra={k: v for k, v in rec.items() if k not in _KNOWN_ANNOUNCEMENT_KEYS},
                )
            )
        return announcements

    def equity_meta(self, symbol: str) -> dict[str, Any]:
        payload, _ = self._run_tool("nse_equity_meta_info", {"symbol": symbol.upper()})
        return payload if isinstance(payload, dict) else {}

    def lookup_symbol(self, query: str) -> list[dict[str, Any]]:
        payload, _ = self._run_tool("nse_lookup_symbol", {"query": query})
        return extract_record_list(payload)


def _first(record: dict[str, Any], aliases: list[str]) -> Any:
    lowered = {str(k).lower(): v for k, v in record.items()}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def _classify_action(rec: dict[str, Any]) -> CorporateActionType | None:
    subject = str(_first(rec, ["subject", "desc", "purpose"]) or "").lower()
    rate = _first(rec, ["rate"])
    bv = _first(rec, ["bv", "bonus"])
    fv_from = _first(rec, ["fvFrom", "oldFv"])
    if bv and str(bv).strip() not in ("-", ""):
        return CorporateActionType.BONUS
    if fv_from:
        return CorporateActionType.SPLIT
    if rate is not None or "dividend" in subject:
        return CorporateActionType.DIVIDEND
    if "rights" in subject:
        return CorporateActionType.RIGHTS
    if "merger" in subject:
        return CorporateActionType.MERGER
    if "demerger" in subject:
        return CorporateActionType.DEMERGER
    if "buyback" in subject:
        return CorporateActionType.BUYBACK
    return None


_DIVIDEND_PATTERNS = ("rs ", "rs.", "₹")


def dividend_amount_from_subject(subject: str | None) -> float | None:
    """NSE states dividends as 'Dividend - Rs 6 Per Share'; extract the amount."""
    if not subject:
        return None
    low = subject.lower()
    if "dividend" not in low:
        return None
    for pat in _DIVIDEND_PATTERNS:
        idx = low.find(pat)
        if idx == -1:
            continue
        tail = subject[idx + len(pat) :]
        digits = ""
        for ch in tail.strip():
            if ch.isdigit() or ch == ".":
                digits += ch
            elif digits:
                break
        try:
            return float(digits) if digits else None
        except ValueError:
            return None
    return None


def _parse_ratio(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(" ", "")
    if ":" in text:
        try:
            a, b = text.split(":")
            return float(a) / float(b) if float(b) else None
        except (ValueError, ZeroDivisionError):
            return None
    return parse_float(text)


_KNOWN_ACTION_KEYS = {
    "symbol",
    "SYMBOL",
    "isin",
    "ISIN",
    "series",
    "rate",
    "amount",
    "bv",
    "bonus",
    "fvFrom",
    "fvTo",
    "oldFv",
    "newFv",
    "exDate",
    "recordDate",
    "recDate",
    "date",
    "DATE",
    "dt",
    "subject",
    "desc",
    "purpose",
    "seqId",
    "bmSeqId",
    "attachmentURL",
    "url",
    "lastUpdatedOn",
    "ts",
}
_KNOWN_ANNOUNCEMENT_KEYS = {
    "symbol",
    "SYMBOL",
    "sortDate",
    "sort_date",
    "an_dt",
    "publishedAt",
    "date",
    "dt",
    "desc",
    "attchmntText",
    "attchmntFile",
    "fileUrl",
    "subject",
    "smIsin",
    "sm_isin",
    "smIndustry",
    "sm_name",
    "seq_id",
    "exchdisstime",
    "bflag",
    "csvName",
}
