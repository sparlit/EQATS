"""
TectonicDB High-Throughput Compressed Tick Storage Gateway
Adapted from 0b01/tectonicdb for EQATS Microkernel Monolith
Assigned Immutable Magic Number: 9500001
"""

import ctypes
import logging
import os
import struct
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CompactTickRecord(ctypes.Structure):
    _fields_ = [
        ("timestamp_ns", ctypes.c_uint64),
        ("bid_price", ctypes.c_double),
        ("ask_price", ctypes.c_double),
        ("bid_size", ctypes.c_double),
        ("ask_size", ctypes.c_double),
        ("trade_price", ctypes.c_double),
        ("trade_volume", ctypes.c_double),
    ]


def _load_rust_tectonic_lib() -> Any:
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "..", "eqats_rust_core", "target", "release", "libeqats_rust_core.so"),
        os.path.join(os.path.dirname(__file__), "..", "eqats_rust_core", "target", "debug", "libeqats_rust_core.so"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            try:
                lib = ctypes.CDLL(path)
                return lib
            except Exception as e:
                logger.warning(f"Failed to load Rust C-ABI library at {path}: {e}")
    return None


_RUST_LIB = _load_rust_tectonic_lib()


class TectonicDBEngine:
    """
    High-Throughput Compressed Tick Storage Engine Gateway.
    Assigned Magic Number: 9500001
    Handles delta bit-packing, compressed binary tick storage, and high-speed timestamp range queries.
    """

    def __init__(self, magic_number: int = 9500001) -> None:
        self.magic_number: int = magic_number
        self.rust_lib = _RUST_LIB
        if self.rust_lib:
            self._setup_c_signatures()

    def _setup_c_signatures(self) -> None:
        if not self.rust_lib:
            return
        self.rust_lib.rust_tectonicdb_pack_ticks.argtypes = [
            ctypes.POINTER(CompactTickRecord),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.rust_lib.rust_tectonicdb_pack_ticks.restype = ctypes.c_int
        self.rust_lib.rust_tectonicdb_unpack_ticks.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int,
            ctypes.POINTER(CompactTickRecord),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.rust_lib.rust_tectonicdb_unpack_ticks.restype = ctypes.c_int
        self.rust_lib.rust_tectonicdb_filter_range.argtypes = [
            ctypes.POINTER(CompactTickRecord),
            ctypes.c_int,
            ctypes.c_ulonglong,
            ctypes.c_ulonglong,
            ctypes.POINTER(CompactTickRecord),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.rust_lib.rust_tectonicdb_filter_range.restype = ctypes.c_int

    def pack_ticks(self, ticks: list[dict[str, Any]]) -> bytes:
        """
        Compress a list of tick dictionaries into delta binary byte stream.
        """
        if not ticks:
            return b""
        if self.rust_lib:
            try:
                count = len(ticks)
                tick_array = (CompactTickRecord * count)()
                for idx, t in enumerate(ticks):
                    tick_array[idx].timestamp_ns = int(t.get("timestamp_ns", 0))
                    tick_array[idx].bid_price = float(t.get("bid_price", 0.0))
                    tick_array[idx].ask_price = float(t.get("ask_price", 0.0))
                    tick_array[idx].bid_size = float(t.get("bid_size", 0.0))
                    tick_array[idx].ask_size = float(t.get("ask_size", 0.0))
                    tick_array[idx].trade_price = float(t.get("trade_price", 0.0))
                    tick_array[idx].trade_volume = float(t.get("trade_volume", 0.0))
                cap = 4 + 56 * count + 1024
                buf = (ctypes.c_uint8 * cap)()
                written = ctypes.c_int(0)
                res = self.rust_lib.rust_tectonicdb_pack_ticks(tick_array, count, buf, cap, ctypes.byref(written))
                if res == 0:
                    return bytes(buf[: written.value])
            except Exception as e:
                logger.error(f"Rust pack_ticks failed, falling back to Python: {e}")
        return self._python_pack_ticks(ticks)

    def unpack_ticks(self, data: bytes) -> list[dict[str, Any]]:
        """
        Decompress delta binary byte stream back into list of tick dictionaries.
        """
        if not data or len(data) < 4:
            return []
        if self.rust_lib:
            try:
                total_count = struct.unpack("<I", data[:4])[0]
                if total_count == 0:
                    return []
                in_buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
                out_array = (CompactTickRecord * total_count)()
                out_count = ctypes.c_int(0)
                res = self.rust_lib.rust_tectonicdb_unpack_ticks(
                    in_buf, len(data), out_array, total_count, ctypes.byref(out_count),
                )
                if res == 0:
                    result = []
                    for idx in range(out_count.value):
                        rec = out_array[idx]
                        result.append(
                            {
                                "timestamp_ns": rec.timestamp_ns,
                                "bid_price": rec.bid_price,
                                "ask_price": rec.ask_price,
                                "bid_size": rec.bid_size,
                                "ask_size": rec.ask_size,
                                "trade_price": rec.trade_price,
                                "trade_volume": rec.trade_volume,
                                "magic_number": self.magic_number,
                            },
                        )
                    return result
            except Exception as e:
                logger.error(f"Rust unpack_ticks failed, falling back to Python: {e}")
        return self._python_unpack_ticks(data)

    def filter_time_range(self, ticks: list[dict[str, Any]], start_ns: int, end_ns: int) -> list[dict[str, Any]]:
        """
        Filter ticks within timestamp window [start_ns, end_ns].
        """
        if not ticks:
            return []
        if self.rust_lib:
            try:
                count = len(ticks)
                tick_array = (CompactTickRecord * count)()
                for idx, t in enumerate(ticks):
                    tick_array[idx].timestamp_ns = int(t.get("timestamp_ns", 0))
                    tick_array[idx].bid_price = float(t.get("bid_price", 0.0))
                    tick_array[idx].ask_price = float(t.get("ask_price", 0.0))
                    tick_array[idx].bid_size = float(t.get("bid_size", 0.0))
                    tick_array[idx].ask_size = float(t.get("ask_size", 0.0))
                    tick_array[idx].trade_price = float(t.get("trade_price", 0.0))
                    tick_array[idx].trade_volume = float(t.get("trade_volume", 0.0))
                out_array = (CompactTickRecord * count)()
                out_count = ctypes.c_int(0)
                res = self.rust_lib.rust_tectonicdb_filter_range(
                    tick_array, count, start_ns, end_ns, out_array, count, ctypes.byref(out_count),
                )
                if res == 0:
                    result = []
                    for idx in range(out_count.value):
                        rec = out_array[idx]
                        result.append(
                            {
                                "timestamp_ns": rec.timestamp_ns,
                                "bid_price": rec.bid_price,
                                "ask_price": rec.ask_price,
                                "bid_size": rec.bid_size,
                                "ask_size": rec.ask_size,
                                "trade_price": rec.trade_price,
                                "trade_volume": rec.trade_volume,
                                "magic_number": self.magic_number,
                            },
                        )
                    return result
            except Exception as e:
                logger.error(f"Rust filter_time_range failed, falling back to Python: {e}")
        return [t for t in ticks if start_ns <= t.get("timestamp_ns", 0) <= end_ns]

    def _python_pack_ticks(self, ticks: list[dict[str, Any]]) -> bytes:
        count = len(ticks)
        out = bytearray()
        out.extend(struct.pack("<I", count))
        if count == 0:
            return bytes(out)
        anchor = ticks[0]
        out.extend(
            struct.pack(
                "<Qdddddd",
                int(anchor.get("timestamp_ns", 0)),
                float(anchor.get("bid_price", 0.0)),
                float(anchor.get("ask_price", 0.0)),
                float(anchor.get("bid_size", 0.0)),
                float(anchor.get("ask_size", 0.0)),
                float(anchor.get("trade_price", 0.0)),
                float(anchor.get("trade_volume", 0.0)),
            ),
        )
        prev_ts = int(anchor.get("timestamp_ns", 0))
        prev_bid = round(float(anchor.get("bid_price", 0.0)) * 10000)
        prev_ask = round(float(anchor.get("ask_price", 0.0)) * 10000)
        for t in ticks[1:]:
            curr_ts = int(t.get("timestamp_ns", 0))
            curr_bid = round(float(t.get("bid_price", 0.0)) * 10000)
            curr_ask = round(float(t.get("ask_price", 0.0)) * 10000)
            ts_delta = curr_ts - prev_ts
            bid_delta = curr_bid - prev_bid
            ask_delta = curr_ask - prev_ask
            out.extend(
                struct.pack(
                    "<Qqdddd",
                    ts_delta,
                    bid_delta,
                    float(t.get("bid_size", 0.0)),
                    float(t.get("ask_size", 0.0)),
                    float(t.get("trade_price", 0.0)),
                    float(t.get("trade_volume", 0.0)),
                ),
            )
            prev_ts = curr_ts
            prev_bid = curr_bid
            prev_ask = curr_ask
        return bytes(out)

    def _python_unpack_ticks(self, data: bytes) -> list[dict[str, Any]]:
        count = struct.unpack("<I", data[:4])[0]
        if count == 0:
            return []
        cursor = 4
        anchor_data = struct.unpack("<Qdddddd", data[cursor : cursor + 56])
        cursor += 56
        results = [
            {
                "timestamp_ns": anchor_data[0],
                "bid_price": anchor_data[1],
                "ask_price": anchor_data[2],
                "bid_size": anchor_data[3],
                "ask_size": anchor_data[4],
                "trade_price": anchor_data[5],
                "trade_volume": anchor_data[6],
                "magic_number": self.magic_number,
            },
        ]
        prev_ts = anchor_data[0]
        prev_bid = round(anchor_data[1] * 10000)
        prev_ask = round(anchor_data[2] * 10000)
        for _ in range(1, count):
            row = struct.unpack("<Qqdddd", data[cursor : cursor + 48])
            cursor += 48
            curr_ts = prev_ts + row[0]
            curr_bid = prev_bid + row[1]
            curr_ask = prev_ask
            results.append(
                {
                    "timestamp_ns": curr_ts,
                    "bid_price": curr_bid / 10000.0,
                    "ask_price": prev_ask / 10000.0,
                    "bid_size": row[2],
                    "ask_size": row[3],
                    "trade_price": row[4],
                    "trade_volume": row[5],
                    "magic_number": self.magic_number,
                },
            )
            prev_ts = curr_ts
            prev_bid = curr_bid
        return results
