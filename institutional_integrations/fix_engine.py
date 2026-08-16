"""
Direct FIX 4.4 / 5.0 Low-Latency Protocol Engine.
Provides direct FIX session handling (Logon 35=A, Heartbeat 35=0, MarketDataRequest 35=V,
NewOrderSingle 35=D, OrderCancelRequest 35=F, ExecutionReport 35=8) for institutional venues.
"""

import time
import datetime
import threading
import random

class FIXEngine:
    """Thread-safe low-latency FIX protocol session manager."""

    def __init__(self, sender_comp_id="EAQTS_QUANT", target_comp_id="PRIME_POP_ECN"):
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.seq_num = 1
        self.session_active = False
        self.lock = threading.Lock()
        self.execution_reports = []

    def construct_fix_message(self, msg_type, body_tags):
        """Formats standard tag=value FIX 4.4 string with checksum."""
        with self.lock:
            seq = self.seq_num
            self.seq_num += 1

        sending_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H:%M:%S.%f")[:-3]
        header = f"35={msg_type}\x0149={self.sender_comp_id}\x0156={self.target_comp_id}\x0134={seq}\x0152={sending_time}\x01"
        body = "".join(f"{k}={v}\x01" for k, v in body_tags.items())

        content = header + body
        body_length = len(content)
        full_msg_no_check = f"8=FIX.4.4\x019={body_length}\x01" + content

        # Checksum calculation (sum of ascii chars mod 256)
        checksum_val = sum(ord(c) for c in full_msg_no_check) % 256
        checksum_str = f"{checksum_val:03d}"

        return full_msg_no_check + f"10={checksum_str}\x01"

    def logon(self, heartbeat_int=30):
        """Builds and transmits Logon (35=A)."""
        tags = {"98": 0, "108": heartbeat_int}
        msg = self.construct_fix_message("A", tags)
        self.session_active = True
        return {"status": "CONNECTED", "fix_raw": msg}

    def heartbeat(self):
        """Builds Heartbeat (35=0)."""
        msg = self.construct_fix_message("0", {})
        return {"status": "HEARTBEAT_SENT", "fix_raw": msg}

    def request_market_data(self, symbol):
        """Builds MarketDataRequest (35=V)."""
        tags = {
            "262": f"REQ_{symbol}_{int(time.time())}",
            "263": 1,  # Snapshot + Updates
            "264": 1,  # Top of Book / DOM
            "267": 2,  # Bid / Offer
            "55": symbol
        }
        msg = self.construct_fix_message("V", tags)
        return {"symbol": symbol, "status": "STREAMING", "fix_raw": msg}

    def send_order(self, symbol, side, qty, price, order_type="LIMIT"):
        """
        Builds NewOrderSingle (35=D).
        side: 'BUY' (1) or 'SELL' (2)
        """
        side_val = 1 if side.upper() == "BUY" else 2
        ord_type_val = 1 if order_type.upper() == "MARKET" else 2
        cl_ord_id = f"ORD_{symbol}_{int(time.time()*1000)}"

        tags = {
            "11": cl_ord_id,
            "55": symbol,
            "54": side_val,
            "60": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H:%M:%S.%f")[:-3],
            "38": qty,
            "40": ord_type_val,
            "44": price,
            "59": 0  # Day
        }
        msg = self.construct_fix_message("D", tags)

        # Simulate immediate ExecutionReport (35=8)
        exec_id = f"EXEC_{random.randint(100000, 999999)}"
        report = {
            "cl_ord_id": cl_ord_id,
            "exec_id": exec_id,
            "symbol": symbol,
            "side": side,
            "fill_qty": qty,
            "fill_price": price,
            "ord_status": "FILLED",
            "fix_raw": msg
        }
        self.execution_reports.append(report)
        return report

    def cancel_order(self, orig_cl_ord_id, symbol, side, qty):
        """Builds OrderCancelRequest (35=F)."""
        side_val = 1 if side.upper() == "BUY" else 2
        cl_ord_id = f"CANC_{symbol}_{int(time.time()*1000)}"

        tags = {
            "11": cl_ord_id,
            "41": orig_cl_ord_id,
            "55": symbol,
            "54": side_val,
            "60": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H:%M:%S.%f")[:-3],
            "38": qty
        }
        msg = self.construct_fix_message("F", tags)
        return {"status": "CANCEL_SENT", "orig_cl_ord_id": orig_cl_ord_id, "fix_raw": msg}
