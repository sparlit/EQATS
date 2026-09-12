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
Estimate "real fill latency" from on-chain Polygon logs for a proxy wallet.

How it works:
1) Reads recent ENTRY_ACK + ENTRY_FILL events from tracking.db (order_id + local timestamps).
2) Queries Polygon RPC logs for the wallet on the Polymarket exchange contract(s).
3) Matches on-chain fills by order_id (topics[1]) and computes latency:
   - submit -> first chain fill
   - ack -> first chain fill
   - first chain fill -> local ENTRY_FILL event

Usage:
  python3 scripts/filled_latency_onchain.py \
    --wallet 0xC9323138FafCCBCB514730fBfF53B9AC8C1E3545 \
    --hours 24 --limit 300
"""


import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_RPC = os.getenv("POLY_POLYGON_RPC_HTTP_URL", "").strip() or "https://polygon-bor-rpc.publicnode.com"
DEFAULT_EXCHANGE_ADDRESSES = [
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # Polymarket CTF Exchange
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # Polymarket Neg Risk CTF Exchange
]


def now_ms() -> int:
    return int(time.time() * 1000)


def ms_to_utc_str(ms: int | None) -> str:
    if ms is None:
        return "-"
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")


def normalize_hex_32(value: str) -> str:
    value = value.lower().strip()
    value = value.removeprefix("0x")
    if len(value) > 64:
        value = value[-64:]
    return "0x" + value.rjust(64, "0")


def parse_json_field(text: str | None, key: str) -> object | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed.get(key)
    return None


def parse_order_id_from_fill_event_key(event_key: str | None) -> str | None:
    if not event_key:
        return None
    prefix = "entry_fill_order:"
    if not event_key.startswith(prefix):
        return None
    order_id = event_key[len(prefix) :].strip().lower()
    if order_id.startswith("0x") and len(order_id) == 66:
        return order_id
    return None


class RpcClient:
    def __init__(self, url: str, timeout_s: float = 20.0, retries: int = 3) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self.retries = retries
        self._id = 1

    def call(self, method: str, params: list[object]) -> object:
        last_err: Exception | None = None
        for attempt in range(self.retries):
            payload = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode("utf-8")
            self._id += 1
            req = urllib.request.Request(
                self.url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "evpoly-latency-tracker/1.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                if "error" in body:
                    msg = f"rpc {method} error: {body['error']}"
                    raise RuntimeError(msg)
                return body["result"]
            except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as err:
                last_err = err
                if attempt + 1 < self.retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                break
        assert last_err is not None
        raise last_err

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def block_ts_s(self, block_number: int, cache: dict[int, int]) -> int:
        if block_number in cache:
            return cache[block_number]
        block_hex = hex(block_number)
        block = self.call("eth_getBlockByNumber", [block_hex, False])
        if not isinstance(block, dict) or "timestamp" not in block:
            msg = f"missing block/timestamp for block {block_number}"
            raise RuntimeError(msg)
        ts_s = int(block["timestamp"], 16)
        cache[block_number] = ts_s
        return ts_s

    def get_logs(self, params: dict[str, object]) -> list[dict[str, object]]:
        out = self.call("eth_getLogs", [params])
        if not isinstance(out, list):
            msg = "eth_getLogs returned non-list"
            raise RuntimeError(msg)
        return out  # type: ignore[return-value]


def find_block_at_or_after_ts(
    rpc: RpcClient, target_ts_s: int, latest_block: int, block_ts_cache: dict[int, int]
) -> int:
    latest_ts = rpc.block_ts_s(latest_block, block_ts_cache)
    if target_ts_s >= latest_ts:
        return latest_block
    low = 1
    high = latest_block
    while low < high:
        mid = (low + high) // 2
        mid_ts = rpc.block_ts_s(mid, block_ts_cache)
        if mid_ts < target_ts_s:
            low = mid + 1
        else:
            high = mid
    return low


@dataclass
class AckOrder:
    order_id: str
    strategy_id: str
    asset_symbol: str
    timeframe: str
    period_timestamp: int
    submit_ms: int | None
    ack_ms: int | None
    ack_event_ms: int
    ack_latency_ms: int | None
    local_fill_ms: int | None = None
    local_fill_source: str | None = None


@dataclass
class ChainFill:
    first_ms: int
    last_ms: int
    first_tx: str
    count: int


def load_recent_ack_orders(db_path: str, since_ms: int, limit: int) -> dict[str, AckOrder]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT ts_ms, strategy_id, asset_symbol, timeframe, period_timestamp, reason
        FROM trade_events
        WHERE event_type='ENTRY_ACK'
          AND ts_ms >= ?
        ORDER BY ts_ms DESC
        LIMIT ?
        """,
        (since_ms, limit),
    ).fetchall()
    out: dict[str, AckOrder] = {}
    for row in rows:
        reason = row["reason"]
        oid = parse_json_field(reason, "order_id")
        if not isinstance(oid, str):
            continue
        oid = oid.strip().lower()
        if not (oid.startswith("0x") and len(oid) == 66):
            continue
        submit_ms = parse_json_field(reason, "submitted_at_ms")
        ack_ms = parse_json_field(reason, "acked_at_ms")
        ack_latency_ms = parse_json_field(reason, "order_ack_latency_ms")
        if not isinstance(submit_ms, int):
            submit_ms = None
        if not isinstance(ack_ms, int):
            ack_ms = None
        if not isinstance(ack_latency_ms, int):
            ack_latency_ms = None
        # Keep earliest ack record for a given order id if duplicates appear.
        prev = out.get(oid)
        ack_event_ms = int(row["ts_ms"])
        if prev and prev.ack_event_ms <= ack_event_ms:
            continue
        out[oid] = AckOrder(
            order_id=oid,
            strategy_id=str(row["strategy_id"]),
            asset_symbol=str(row["asset_symbol"]),
            timeframe=str(row["timeframe"]),
            period_timestamp=int(row["period_timestamp"]),
            submit_ms=submit_ms,
            ack_ms=ack_ms,
            ack_event_ms=ack_event_ms,
            ack_latency_ms=ack_latency_ms,
        )

    if out:
        placeholders = ",".join(["?"] * len(out))
        fill_rows = cur.execute(
            f"""
            SELECT ts_ms, event_key, reason
            FROM trade_events
            WHERE event_type='ENTRY_FILL'
              AND event_key LIKE 'entry_fill_order:%'
              AND event_key IN ({placeholders})
            """,
            [f"entry_fill_order:{oid}" for oid in out],
        ).fetchall()
        for row in fill_rows:
            oid = parse_order_id_from_fill_event_key(row["event_key"])
            if not oid or oid not in out:
                continue
            fill_ms = int(row["ts_ms"])
            rec = out[oid]
            if rec.local_fill_ms is None or fill_ms < rec.local_fill_ms:
                rec.local_fill_ms = fill_ms
                source = parse_json_field(row["reason"], "fill_source")
                rec.local_fill_source = str(source) if isinstance(source, str) else None

    conn.close()
    return out


def collect_chain_fills(
    rpc: RpcClient,
    wallet: str,
    order_ids: Iterable[str],
    start_ts_ms: int,
    exchange_addresses: list[str],
    max_block_span: int = 45000,
) -> dict[str, ChainFill]:
    tracked = {oid.lower() for oid in order_ids}
    if not tracked:
        return {}

    wallet_topic = normalize_hex_32(wallet)
    block_ts_cache: dict[int, int] = {}
    latest_block = rpc.block_number()
    start_block = find_block_at_or_after_ts(rpc, start_ts_ms // 1000, latest_block, block_ts_cache)

    result: dict[str, ChainFill] = {}
    for addr in exchange_addresses:
        cur = start_block
        while cur <= latest_block:
            to_block = min(cur + max_block_span - 1, latest_block)
            params = {
                "fromBlock": hex(cur),
                "toBlock": hex(to_block),
                "address": addr.lower(),
                # topics[2] is maker/taker wallet in observed PM fills.
                "topics": [None, None, wallet_topic],
            }
            logs = rpc.get_logs(params)
            for lg in logs:
                topics = lg.get("topics", [])
                if not isinstance(topics, list) or len(topics) < 2:
                    continue
                t1 = topics[1]
                if not isinstance(t1, str):
                    continue
                oid = "0x" + t1.lower().replace("0x", "")[-64:]
                if oid not in tracked:
                    continue
                block_number = int(str(lg["blockNumber"]), 16)
                if "blockTimestamp" in lg and isinstance(lg["blockTimestamp"], str):
                    ts_s = int(lg["blockTimestamp"], 16)
                else:
                    ts_s = rpc.block_ts_s(block_number, block_ts_cache)
                ts_ms = ts_s * 1000
                tx_hash = str(lg.get("transactionHash", ""))
                prev = result.get(oid)
                if prev is None:
                    result[oid] = ChainFill(first_ms=ts_ms, last_ms=ts_ms, first_tx=tx_hash, count=1)
                else:
                    first_ms = min(prev.first_ms, ts_ms)
                    first_tx = prev.first_tx if prev.first_ms <= ts_ms else tx_hash
                    result[oid] = ChainFill(
                        first_ms=first_ms,
                        last_ms=max(prev.last_ms, ts_ms),
                        first_tx=first_tx,
                        count=prev.count + 1,
                    )
            cur = to_block + 1
    return result


def median_or_none(values: list[int]) -> float | None:
    if not values:
        return None
    return statistics.median(values)


def pct_or_none(values: list[int], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    idx = round((len(xs) - 1) * p)
    idx = max(0, min(idx, len(xs) - 1))
    return float(xs[idx])


def fmt_ms(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:.0f}"


def print_report(
    orders: dict[str, AckOrder],
    chain: dict[str, ChainFill],
    only_with_chain: bool,
    max_rows: int,
) -> None:
    rows = []
    for oid, rec in orders.items():
        c = chain.get(oid)
        if only_with_chain and c is None:
            continue
        submit_to_chain = None
        ack_to_chain = None
        chain_to_local = None
        if c and rec.submit_ms is not None:
            submit_to_chain = c.first_ms - rec.submit_ms
        if c and rec.ack_ms is not None:
            ack_to_chain = c.first_ms - rec.ack_ms
        if c and rec.local_fill_ms is not None:
            chain_to_local = rec.local_fill_ms - c.first_ms
        rows.append(
            (
                rec.ack_event_ms,
                oid,
                rec,
                c,
                submit_to_chain,
                ack_to_chain,
                chain_to_local,
            )
        )
    rows.sort(key=lambda x: x[0], reverse=True)

    print(
        "ts_utc | strategy | symbol | tf | period | ack_ms | submit->chain_ms | ack->chain_ms | chain->local_fill_ms | chain_logs | first_tx | order_id"
    )
    print("-" * 210)
    for _, oid, rec, c, s2c, a2c, c2l in rows[:max_rows]:
        print(
            f"{ms_to_utc_str(rec.ack_event_ms)} | {rec.strategy_id:14s} | {rec.asset_symbol:4s} | {rec.timeframe:3s} | "
            f"{rec.period_timestamp} | {rec.ack_latency_ms if rec.ack_latency_ms is not None else '-':>6} | "
            f"{s2c if s2c is not None else '-':>15} | {a2c if a2c is not None else '-':>11} | "
            f"{c2l if c2l is not None else '-':>19} | {c.count if c else 0:>10} | "
            f"{(c.first_tx[:10] + '...') if c and c.first_tx else '-':12s} | {oid[:12]}..."
        )

    s2c_all = [r[4] for r in rows if isinstance(r[4], int)]
    a2c_all = [r[5] for r in rows if isinstance(r[5], int)]
    c2l_all = [r[6] for r in rows if isinstance(r[6], int)]
    print()
    print(f"orders_with_ack={len(orders)} orders_with_chain={len(chain)} shown={min(len(rows), max_rows)}")
    print(
        "submit->chain ms: "
        f"avg={fmt_ms(sum(s2c_all) / len(s2c_all) if s2c_all else None)} "
        f"med={fmt_ms(median_or_none(s2c_all))} p95={fmt_ms(pct_or_none(s2c_all, 0.95))}"
    )
    print(
        "ack->chain ms:    "
        f"avg={fmt_ms(sum(a2c_all) / len(a2c_all) if a2c_all else None)} "
        f"med={fmt_ms(median_or_none(a2c_all))} p95={fmt_ms(pct_or_none(a2c_all, 0.95))}"
    )
    print(
        "chain->local ms:  "
        f"avg={fmt_ms(sum(c2l_all) / len(c2l_all) if c2l_all else None)} "
        f"med={fmt_ms(median_or_none(c2l_all))} p95={fmt_ms(pct_or_none(c2l_all, 0.95))}"
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Track real fill latency via Polygon RPC logs")
    p.add_argument("--wallet", required=True, help="Proxy wallet address (0x...)")
    p.add_argument("--db", default="tracking.db", help="Path to tracking.db")
    p.add_argument("--rpc", default=DEFAULT_RPC, help="Polygon RPC URL")
    p.add_argument("--hours", type=float, default=24.0, help="Lookback hours")
    p.add_argument("--limit", type=int, default=400, help="Max ACK orders to inspect from DB")
    p.add_argument("--rows", type=int, default=50, help="Rows to print in report (sorted by latest ACK)")
    p.add_argument(
        "--exchange-address",
        action="append",
        default=[],
        help="Exchange address to scan (repeatable). Defaults to known PM exchange.",
    )
    p.add_argument(
        "--include-no-chain",
        action="store_true",
        help="Show rows even if no chain log was found for that order_id",
    )
    p.add_argument(
        "--max-block-span",
        type=int,
        default=45000,
        help="Max block range per eth_getLogs call (keep <= 50000 for many public RPCs)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    since_ms = now_ms() - int(args.hours * 3600 * 1000)

    exchange_addrs = [a.lower() for a in (args.exchange_address or []) if a]
    if not exchange_addrs:
        exchange_addrs = list(DEFAULT_EXCHANGE_ADDRESSES)

    orders = load_recent_ack_orders(args.db, since_ms, args.limit)
    if not orders:
        print("No recent ENTRY_ACK orders with exchange order_id found.")
        return 0

    earliest_submit = min([o.submit_ms for o in orders.values() if o.submit_ms is not None] or [since_ms])
    # small buffer before first local submit
    start_ts_ms = earliest_submit - 5 * 60 * 1000

    rpc = RpcClient(args.rpc)
    chain = collect_chain_fills(
        rpc=rpc,
        wallet=args.wallet,
        order_ids=orders.keys(),
        start_ts_ms=start_ts_ms,
        exchange_addresses=exchange_addrs,
        max_block_span=args.max_block_span,
    )

    print_report(
        orders=orders,
        chain=chain,
        only_with_chain=not args.include_no_chain,
        max_rows=args.rows,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
