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


"""Small, non-destructive storage helper for fundamentals imports.

Importers deliberately use this module instead of row replacement.  A source
usually supplies only a subset of a fundamentals row; a null in that subset
must not erase a value supplied by another source.
"""
import datetime as _dt
import json
import math
import numbers

META_COLUMNS = {
    "symbol",
    "data_source",
    "uploaded_at",
    "field_sources",
    "field_updated_at",
    "data_quality_flags",
    "source_metadata",
}


def _present(value):
    if value is None:
        return False
    if isinstance(value, numbers.Real):
        return math.isfinite(float(value))
    return not (isinstance(value, str) and not value.strip())


def _json_object(value):
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _quality_flags(value):
    if isinstance(value, (list, tuple, set)):
        return {str(flag) for flag in value if flag}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            parsed = parsed.get("flags", [])
        if isinstance(parsed, (list, tuple, set)):
            return {str(flag) for flag in parsed if flag}
        return set(value.split(",")) - {""}
    return set()


def _columns(conn):
    return {row[1] for row in conn.execute("PRAGMA table_info(fundamentals)")}


def _deprecated_fields(source_map, cfo_positive, roce):
    fields = []
    for field, value in (("cfo_positive", cfo_positive), ("roce", roce)):
        source = source_map.get(field)
        source_name = str(source or "").strip().lower()
        if value is not None and (not source_name or source_name.startswith("tradingview")):
            fields.append(field)
    return fields


def merge(conn, values, source=None, observed_at=None):
    """Merge non-null fields in *values* into one fundamentals row.

    ``field_sources`` and ``field_updated_at`` are intentionally per-field;
    the row-level ``data_source``/``uploaded_at`` only describe the latest
    import event and do not make preserved fields look freshly observed.
    Returns the fields changed by this import.
    """
    if not values or not _present(values.get("symbol")):
        raise ValueError("fundamentals merge requires a symbol")
    cols = _columns(conn)
    symbol = values["symbol"]
    now = observed_at or _dt.datetime.now().isoformat()
    source = source or values.get("data_source") or "unknown"
    incoming = {
        key: value
        for key, value in values.items()
        if key in cols and key not in META_COLUMNS and _present(value)
    }
    # Quality flags are additive and are not a replacement for field data.
    flags = values.get("data_quality_flags")
    existing = conn.execute("SELECT * FROM fundamentals WHERE symbol=?", (symbol,)).fetchone()
    names = [row[1] for row in conn.execute("PRAGMA table_info(fundamentals)")]
    old = dict(zip(names, existing, strict=False)) if existing else {}
    field_sources = _json_object(old.get("field_sources"))
    field_updated = _json_object(old.get("field_updated_at"))
    changed = []
    for key in incoming:
        field_sources[key] = source
        field_updated[key] = now
        changed.append(key)
    old_flags = _quality_flags(old.get("data_quality_flags"))
    old_flags.update(_quality_flags(flags))

    metadata = {}
    if "data_source" in cols:
        metadata["data_source"] = source
    if "uploaded_at" in cols:
        metadata["uploaded_at"] = now
    if "field_sources" in cols:
        metadata["field_sources"] = json.dumps(field_sources, sort_keys=True)
    if "field_updated_at" in cols:
        metadata["field_updated_at"] = json.dumps(field_updated, sort_keys=True)
    if "source_metadata" in cols and values.get("source_metadata") is not None:
        metadata["source_metadata"] = json.dumps(
            values["source_metadata"], sort_keys=True, default=str
        )
    if "data_quality_flags" in cols and old_flags:
        metadata["data_quality_flags"] = json.dumps({"flags": sorted(old_flags)}, sort_keys=True)

    if existing is None:
        row = {"symbol": symbol}
        row.update(incoming)
        row.update(metadata)
        keys = [key for key in names if key in row]
        placeholders = ",".join("?" for _ in keys)
        conn.execute(
            "INSERT INTO fundamentals ({}) VALUES ({})".format(",".join(keys), placeholders),
            [row[key] for key in keys],
        )
    else:
        updates = dict(incoming)
        updates.update(metadata)
        if updates:
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(
                f"UPDATE fundamentals SET {assignments} WHERE symbol=?",
                list(updates.values()) + [symbol],
            )
    return changed


def integrity_report(conn):
    """Return legacy rows needing review without rewriting their values.

    Historical data is never silently reclassified.  The report flags rows
    that predate field provenance and the known TradingView FCF/CFO proxy.
    """
    cols = _columns(conn)
    if "field_sources" not in cols:
        return {
            "remediation_needed": True,
            "rows": [],
            "reason": "field provenance migration is not available",
        }
    rows = []
    for row in conn.execute(
        "SELECT symbol,cfo_positive,roce,field_sources,data_quality_flags FROM fundamentals"
    ):
        sources = _json_object(row[3])
        reasons = []
        if not sources:
            reasons.append("legacy row has no field provenance")
        deprecated = _deprecated_fields(sources, row[1], row[2])
        if "cfo_positive" in deprecated:
            reasons.append("cfo_positive may be an historical FCF sign proxy")
        if "roce" in deprecated:
            reasons.append("roce may contain return_on_invested_capital_fy")
        if reasons:
            rows.append(
                {
                    "symbol": row[0],
                    "reasons": reasons,
                    "flags": sorted(_quality_flags(row[4])),
                    "deprecated_fields": deprecated,
                }
            )
    return {"remediation_needed": bool(rows), "rows": rows}


def flag_legacy_deprecated(conn, apply=False):
    """Preview or mark ambiguous legacy CFO/ROCE values without changing them."""
    cols = _columns(conn)
    required = {
        "symbol",
        "data_source",
        "cfo_positive",
        "roce",
        "field_sources",
        "data_quality_flags",
    }
    missing = required - cols
    if missing:
        raise RuntimeError(
            "legacy deprecation tagging requires columns: " + ", ".join(sorted(missing))
        )

    result = {
        "candidate_count": 0,
        "newly_flagged": 0,
        "already_flagged": 0,
        "rows": [],
    }
    candidates = []
    for row in conn.execute(
        "SELECT symbol,cfo_positive,roce,field_sources,data_quality_flags FROM fundamentals"
    ):
        sources = _json_object(row[3])
        fields = _deprecated_fields(sources, row[1], row[2])
        if not fields:
            continue
        flags = _quality_flags(row[4])
        already_flagged = "legacy_deprecated" in flags
        candidates.append((row[0], fields, flags, already_flagged))

    result["candidate_count"] = len(candidates)
    result["already_flagged"] = sum(1 for _, _, _, already_flagged in candidates if already_flagged)
    for symbol, fields, flags, already_flagged in candidates:
        if apply and not already_flagged:
            flags.add("legacy_deprecated")
            conn.execute(
                "UPDATE fundamentals SET data_quality_flags=? WHERE symbol=?",
                (json.dumps({"flags": sorted(flags)}, sort_keys=True), symbol),
            )
            result["newly_flagged"] += 1
        result["rows"].append(
            {
                "symbol": symbol,
                "deprecated_fields": fields,
                "already_flagged": already_flagged,
            }
        )
    return result
