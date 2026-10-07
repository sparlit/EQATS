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


"""Upstox Market Data Feed V3 WebSocket client + protobuf decoder.

Protocol: wss + protobuf binary frames (schema vendored from
assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto).
Modes: ltpc, option_greeks, full, full_d30.

Subscription requests are JSON payloads sent as BINARY websocket frames.
"""


import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

import indian_quant.adapters.upstox.proto.MarketDataFeedV3_pb2 as _pb2  # type: ignore[import-untyped]
from indian_quant.config.settings import UpstoxConfig

pb2: Any = _pb2


class FeedDecoder:
    """Decode a raw websocket frame into normalized record dicts."""

    def decode(self, payload: bytes) -> list[dict[str, Any]]:
        raise NotImplementedError


class JsonFeedDecoder(FeedDecoder):
    def decode(self, payload: bytes) -> list[dict[str, Any]]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
        return [data] if isinstance(data, dict) else [d for d in data if isinstance(d, dict)]


def _ms_to_iso(ms: int | float | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(float(ms) / 1000.0, tz=UTC).isoformat()


class ProtoFeedDecoder(FeedDecoder):
    """Decodes FeedResponse protobuf frames into flat record dicts."""

    def __init__(self, include_market_info: bool = True) -> None:
        self.include_market_info = include_market_info

    def decode(self, payload: bytes) -> list[dict[str, Any]]:
        response = pb2.FeedResponse.FromString(payload)
        records: list[dict[str, Any]] = []

        for key, feed in response.feeds.items():
            record: dict[str, Any] = {
                "instrument_key": key,
                "feed_type": pb2.Type.Name(response.type) if response.type else "live_feed",
                "request_mode": pb2.RequestMode.Name(feed.requestMode),
                "ts": _ms_to_iso(response.currentTs),
            }
            record.update(self._flatten_feed(feed))
            records.append(record)

        if self.include_market_info and response.HasField("marketInfo"):
            statuses = {
                segment: pb2.MarketStatus.Name(status)
                for segment, status in response.marketInfo.segmentStatus.items()
            }
            if statuses:
                records.append(
                    {
                        "market_info": statuses,
                        "feed_type": "market_info",
                        "ts": _ms_to_iso(response.currentTs),
                    }
                )
        return records

    def _flatten_feed(self, feed: pb2.Feed) -> dict[str, Any]:
        out: dict[str, Any] = {}
        kind = feed.WhichOneof("FeedUnion")
        out["feed_kind"] = kind

        if kind == "ltpc":
            out.update(self._ltpc(feed.ltpc))
        elif kind == "fullFeed":
            ff_kind = feed.fullFeed.WhichOneof("FullFeedUnion")
            out["full_kind"] = ff_kind
            if ff_kind == "marketFF":
                mf = feed.fullFeed.marketFF
                out.update(self._ltpc(mf.ltpc))
                out["atp"] = mf.atp
                out["volume_traded_today"] = mf.vtt
                out["open_interest"] = mf.oi
                out["total_buy_qty"] = mf.tbq
                out["total_sell_qty"] = mf.tsq
                if mf.marketLevel.bidAskQuote:
                    top = mf.marketLevel.bidAskQuote[0]
                    out["bid_price"] = top.bidP
                    out["bid_qty"] = top.bidQ
                    out["ask_price"] = top.askP
                    out["ask_qty"] = top.askQ
                    out["depth_levels"] = len(mf.marketLevel.bidAskQuote)
                if len(mf.marketOHLC.ohlc):
                    daily = next(
                        (o for o in mf.marketOHLC.ohlc if o.interval == "1d"),
                        mf.marketOHLC.ohlc[0],
                    )
                    out["ohlc_1d"] = {
                        "open": daily.open,
                        "high": daily.high,
                        "low": daily.low,
                        "close": daily.close,
                        "volume": daily.vol,
                        "ts": _ms_to_iso(daily.ts),
                    }
            elif ff_kind == "indexFF":
                idx = feed.fullFeed.indexFF
                out.update(self._ltpc(idx.ltpc))
                for o in idx.marketOHLC.ohlc:
                    if o.interval == "1d":
                        out["ohlc_1d"] = {
                            "open": o.open,
                            "high": o.high,
                            "low": o.low,
                            "close": o.close,
                            "volume": o.vol,
                            "ts": _ms_to_iso(o.ts),
                        }
                        break
        elif kind == "firstLevelWithGreeks":
            fl = feed.firstLevelWithGreeks
            out.update(self._ltpc(fl.ltpc))
            out.update(self._greeks(fl.optionGreeks))
            out["bid_price"] = fl.firstDepth.bidP
            out["bid_qty"] = fl.firstDepth.bidQ
            out["ask_price"] = fl.firstDepth.askP
            out["ask_qty"] = fl.firstDepth.askQ
            out["volume_traded_today"] = fl.vtt
            out["open_interest"] = fl.oi
        return out

    @staticmethod
    def _ltpc(ltpc: pb2.LTPC) -> dict[str, Any]:
        return {
            "ltp": ltpc.ltp,
            "last_trade_time": _ms_to_iso(ltpc.ltt),
            "last_trade_qty": ltpc.ltq,
            "close_prev": ltpc.cp,
        }

    @staticmethod
    def _greeks(g: pb2.OptionGreeks) -> dict[str, Any]:
        if not any((g.delta, g.gamma, g.theta, g.vega, g.rho)):
            return {}
        return {"delta": g.delta, "gamma": g.gamma, "theta": g.theta, "vega": g.vega, "rho": g.rho}


class UpstoxFeedClient:
    def __init__(
        self,
        config: UpstoxConfig,
        *,
        decoder: FeedDecoder | None = None,
        on_records: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config
        self.decoder = decoder or ProtoFeedDecoder()
        self.on_records = on_records
        self._ws: Any | None = None
        self._connected = False

    async def _authorize_url(self) -> str:
        """Resolve the feed socket URL via Upstox's authorize-redirect flow.

        GET {rest}/v3/feed/market-data-feed with Bearer auth returns 302
        whose Location is the live wss endpoint (token embedded).
        """
        token = self.config.resolve_token()
        if not token:
            raise RuntimeError(
                f"missing access token; set {self.config.access_token_env} "
                "(or upstox_tokens.json / .env)"
            )
        rest_base = "https://api.upstox.com"
        resp = httpx.get(
            f"{rest_base}/v3/feed/market-data-feed",
            headers={"Authorization": f"Bearer {token}", "Accept": "*/*"},
            follow_redirects=False,
            timeout=20,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location")
            if location:
                return location
        if resp.status_code == 200:
            return f"{self.config.ws_url}?authorization={token}"
        raise RuntimeError(f"feed authorize failed ({resp.status_code}): {resp.text[:150]}")

    async def connect(self) -> None:
        import websockets  # optional runtime dependency

        url = await self._authorize_url()
        self._ws = await websockets.connect(url)
        self._connected = True

    async def subscribe(self, instrument_keys: list[str], mode: str = "ltpc") -> None:
        if not self._connected or self._ws is None:
            raise RuntimeError("feed not connected")
        message = {
            "guid": "indian-quant",
            "method": "sub",
            "data": {
                "mode": mode,
                "instrumentKeys": instrument_keys,
            },
        }
        await self._ws.send(json.dumps(message).encode())

    async def run(self) -> None:
        if not self._connected or self._ws is None:
            raise RuntimeError("feed not connected")
        async for raw in self._ws:
            if isinstance(raw, str):
                raw = raw.encode()
            records = self.decoder.decode(raw)
            if records and self.on_records:
                await self.on_records(records)

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        self._connected = False

    @staticmethod
    def authorize_header_probe(config: UpstoxConfig) -> dict[str, str]:
        token = config.resolve_token()
        if not token:
            raise RuntimeError(f"set {config.access_token_env}")
        resp = httpx.get(
            "https://api.upstox.com/v2/user/profile",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return dict(resp.json())


async def stream_once(config: UpstoxConfig, seconds: float = 5.0) -> int:
    """Smoke-run the feed for a few seconds; returns number of decoded records."""
    received = 0

    async def on_records(records: list[dict[str, Any]]) -> None:
        nonlocal received
        received += len(records)

    client = UpstoxFeedClient(config, decoder=ProtoFeedDecoder(), on_records=on_records)
    await client.connect()
    await asyncio.wait_for(client.run(), timeout=seconds)
    return received
