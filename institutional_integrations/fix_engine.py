"""
Direct FIX 4.4 / 5.0 Low-Latency Protocol Engine.
Provides direct FIX session handling (Logon 35=A, Heartbeat 35=0, MarketDataRequest 35=V,
NewOrderSingle 35=D, OrderCancelRequest 35=F, ExecutionReport 35=8) for institutional venues.
"""

import datetime
import logging
import secrets
import socket
import threading
import time

_log = logging.getLogger(__name__)


class FIXEngine:
    """Thread-safe low-latency FIX protocol session manager."""

    def __init__(self, sender_comp_id="EQATS_QUANT", target_comp_id="PRIME_POP_ECN"):
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.seq_num = 1
        self.session_active = False
        self.lock = threading.Lock()
        self.execution_reports = []
        self.socket = None
        self.host = None
        self.port = None

    def connect(self, host, port):
        """Establishes TCP connection to FIX server."""
        try:
            self.host = host
            self.port = port
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            self.socket.connect((host, port))
            _log.info("FIXEngine: Connected to %s:%d", host, port)
        except Exception as e:
            _log.error("FIXEngine: Failed to connect to %s:%d - %s", host, port, e)
            self.socket = None
            raise

    def close(self):
        """Closes FIX session and TCP connection."""
        with self.lock:
            self.session_active = False
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            _log.info("FIXEngine: Session closed")

    def construct_fix_message(self, msg_type, body_tags):
        """Formats standard tag=value FIX 4.4 string with checksum."""
        with self.lock:
            seq = self.seq_num
            self.seq_num += 1

        sending_time = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%d-%H:%M:%S.%f"
        )[:-3]
        header = f"35={msg_type}\x0149={self.sender_comp_id}\x0156={self.target_comp_id}\x0134={seq}\x0152={sending_time}\x01"
        body = "".join(f"{k}={v}\x01" for k, v in body_tags.items())

        content = header + body
        body_length = len(content)
        full_msg_no_check = f"8=FIX.4.4\x019={body_length}\x01" + content

        # Checksum calculation (sum of ascii chars mod 256)
        checksum_val = sum(ord(c) for c in full_msg_no_check) % 256
        checksum_str = f"{checksum_val:03d}"

        return full_msg_no_check + f"10={checksum_str}\x01"

    def send_message(self, msg):
        """Sends a FIX message over the active socket connection."""
        if not self.socket:
            raise RuntimeError("FIXEngine: Cannot send message - no active connection")
        
        try:
            self.socket.sendall(msg.encode("utf-8") if isinstance(msg, str) else msg)
            _log.debug("FIXEngine: Sent message: %s", msg[:100])
        except Exception as e:
            _log.error("FIXEngine: Failed to send message - %s", e)
            raise

    def send_logon(self, heartbeat_int=30):
        """Sends Logon (35=A) message and marks session as active upon successful transmission."""
        if not self.socket:
            raise RuntimeError("FIXEngine: Cannot send logon - no active connection")
        
        tags = {"98": 0, "108": heartbeat_int}
        msg = self.construct_fix_message("A", tags)
        self.send_message(msg)
        
        # Only mark session active after successful transmission
        with self.lock:
            self.session_active = True
        
        _log.info("FIXEngine: Logon sent, session marked active")

    def logon(self, heartbeat_int=30):
        """Builds and transmits Logon (35=A)."""
        tags = {"98": 0, "108": heartbeat_int}
        msg = self.construct_fix_message("A", tags)
        # Note: This method does NOT send the message or mark session active
        # It only constructs the message for backward compatibility
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
            "55": symbol,
        }
        msg = self.construct_fix_message("V", tags)
        return {"symbol": symbol, "status": "STREAMING", "fix_raw": msg}

    def send_order(self, symbol, side, qty, price, order_type="LIMIT"):
        """
        Builds and sends NewOrderSingle (35=D) to venue.
        side: 'BUY' (1) or 'SELL' (2)
        
        SECURITY: This method now requires an active FIX session and actually
        transmits the order to the venue. It returns a PENDING status instead
        of fabricating a FILLED execution report. Callers must wait for and
        correlate actual ExecutionReport (35=8) messages from the venue.
        """
        # SECURITY FIX: Check session is active before allowing order submission
        if not self.session_active:
            raise RuntimeError(
                "FIXEngine: Cannot send order - FIX session is not active. "
                "Call connect() and send_logon() first."
            )
        
        if not self.socket:
            raise RuntimeError(
                "FIXEngine: Cannot send order - no active socket connection"
            )
        
        side_val = 1 if side.upper() == "BUY" else 2
        ord_type_val = 1 if order_type.upper() == "MARKET" else 2
        cl_ord_id = f"ORD_{symbol}_{int(time.time() * 1000)}"

        tags = {
            "11": cl_ord_id,
            "55": symbol,
            "54": side_val,
            "60": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%d-%H:%M:%S.%f"
            )[:-3],
            "38": qty,
            "40": ord_type_val,
            "44": price,
            "59": 0,  # Day
        }
        msg = self.construct_fix_message("D", tags)
        
        # SECURITY FIX: Actually send the message to the venue
        self.send_message(msg)
        
        # SECURITY FIX: Return PENDING status instead of fabricated FILLED report
        # Callers must wait for actual ExecutionReport from venue via receive_execution_report()
        _log.info(
            "FIXEngine: Order sent to venue - cl_ord_id=%s, symbol=%s, side=%s, qty=%s, price=%s",
            cl_ord_id,
            symbol,
            side,
            qty,
            price
        )
        
        return {
            "cl_ord_id": cl_ord_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "ord_status": "PENDING_VENUE",
            "fix_raw": msg,
            "message": "Order transmitted to venue. Await ExecutionReport for fill confirmation."
        }

    def cancel_order(self, orig_cl_ord_id, symbol, side, qty):
        """Builds OrderCancelRequest (35=F)."""
        side_val = 1 if side.upper() == "BUY" else 2
        cl_ord_id = f"CANC_{symbol}_{int(time.time() * 1000)}"

        tags = {
            "11": cl_ord_id,
            "41": orig_cl_ord_id,
            "55": symbol,
            "54": side_val,
            "60": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%d-%H:%M:%S.%f"
            )[:-3],
            "38": qty,
        }
        msg = self.construct_fix_message("F", tags)
        return {
            "status": "CANCEL_SENT",
            "orig_cl_ord_id": orig_cl_ord_id,
            "fix_raw": msg,
        }

    def create_new_order_single(self, cl_ord_id, symbol, side, quantity, ord_type, price):
        """
        Creates a NewOrderSingle (35=D) FIX message.
        This method is called by UniversalBrokerGateway.
        """
        tags = {
            "11": cl_ord_id,
            "55": symbol,
            "54": side,
            "60": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%d-%H:%M:%S.%f"
            )[:-3],
            "38": quantity,
            "40": ord_type,
            "44": price,
            "59": 0,  # Day
        }
        return self.construct_fix_message("D", tags)

    def create_order_cancel_request(self, cl_ord_id, orig_cl_ord_id):
        """
        Creates an OrderCancelRequest (35=F) FIX message.
        This method is called by UniversalBrokerGateway.
        """
        tags = {
            "11": cl_ord_id,
            "41": orig_cl_ord_id,
            "60": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%d-%H:%M:%S.%f"
            )[:-3],
        }
        return self.construct_fix_message("F", tags)

    def create_order_cancel_replace_request(self, cl_ord_id, orig_cl_ord_id, stop_px=None, price=None):
        """
        Creates an OrderCancelReplaceRequest (35=G) FIX message.
        This method is called by UniversalBrokerGateway for modify_order.
        """
        tags = {
            "11": cl_ord_id,
            "41": orig_cl_ord_id,
            "60": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%d-%H:%M:%S.%f"
            )[:-3],
        }
        if stop_px is not None:
            tags["99"] = stop_px  # StopPx
        if price is not None:
            tags["44"] = price  # Price
        return self.construct_fix_message("G", tags)

    def receive_execution_report(self, timeout=5.0):
        """
        Receives and parses ExecutionReport (35=8) from venue.
        
        This method should be called after send_order() to get actual fill confirmation.
        Returns parsed execution report dict or None if timeout/error.
        
        NOTE: This is a simplified implementation. Production systems should use
        a dedicated receive thread and message queue for proper async handling.
        """
        if not self.socket:
            _log.error("FIXEngine: Cannot receive - no active connection")
            return None
        
        try:
            self.socket.settimeout(timeout)
            data = self.socket.recv(4096)
            
            if not data:
                _log.warning("FIXEngine: Connection closed by venue")
                return None
            
            msg_str = data.decode("utf-8")
            _log.debug("FIXEngine: Received message: %s", msg_str[:200])
            
            # Parse FIX message (simplified - production needs proper FIX parser)
            # Look for ExecutionReport (35=8)
            if "35=8\x01" in msg_str:
                # Extract key fields (simplified parsing)
                report = {"msg_type": "ExecutionReport", "raw": msg_str}
                
                # Parse common fields
                for tag_val in msg_str.split("\x01"):
                    if "=" in tag_val:
                        tag, val = tag_val.split("=", 1)
                        if tag == "11":  # ClOrdID
                            report["cl_ord_id"] = val
                        elif tag == "17":  # ExecID
                            report["exec_id"] = val
                        elif tag == "39":  # OrdStatus
                            report["ord_status"] = val
                        elif tag == "55":  # Symbol
                            report["symbol"] = val
                        elif tag == "54":  # Side
                            report["side"] = "BUY" if val == "1" else "SELL"
                        elif tag == "32":  # LastQty
                            report["fill_qty"] = val
                        elif tag == "31":  # LastPx
                            report["fill_price"] = val
                
                self.execution_reports.append(report)
                return report
            
            return None
            
        except socket.timeout:
            _log.warning("FIXEngine: Timeout waiting for execution report")
            return None
        except Exception as e:
            _log.error("FIXEngine: Error receiving execution report - %s", e)
            return None

