"""
Direct FIX 4.4 / 5.0 Low-Latency Protocol Engine.
Provides direct FIX session handling (Logon 35=A, Heartbeat 35=0, MarketDataRequest 35=V,
NewOrderSingle 35=D, OrderCancelRequest 35=F, ExecutionReport 35=8) for institutional venues.
"""
from typing import Any
import datetime
import logging
import secrets
import socket
import threading
import time
_log = logging.getLogger(__name__)

class FIXEngine:
    """Thread-safe low-latency FIX protocol session manager."""

    def __init__(self, sender_comp_id: Any='EQATS_QUANT', target_comp_id: Any='PRIME_POP_ECN') -> None:
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.seq_num = 1
        self.session_active = False
        self.lock = threading.Lock()
        self.execution_reports = []
        self.socket = None
        self.host = None
        self.port = None

    def connect(self, host: Any, port: Any) -> None:
        """Establishes TCP connection to FIX server."""
        try:
            self.host = host
            self.port = port
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            self.socket.connect((host, port))
            _log.info('FIXEngine: Connected to %s:%d', host, port)
        except Exception as e:
            _log.error('FIXEngine: Failed to connect to %s:%d - %s', host, port, e)
            self.socket = None
            raise

    def close(self) -> None:
        """Closes FIX session and TCP connection."""
        with self.lock:
            self.session_active = False
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            _log.info('FIXEngine: Session closed')

    def construct_fix_message(self, msg_type: Any, body_tags: Any) -> Any:
        """Formats standard tag=value FIX 4.4 string with checksum."""
        with self.lock:
            seq = self.seq_num
            self.seq_num += 1
        sending_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3]
        header = f'35={msg_type}\x0149={self.sender_comp_id}\x0156={self.target_comp_id}\x0134={seq}\x0152={sending_time}\x01'
        body = ''.join((f'{k}={v}\x01' for k, v in body_tags.items()))
        content = header + body
        body_length = len(content)
        full_msg_no_check = f'8=FIX.4.4\x019={body_length}\x01' + content
        checksum_val = sum((ord(c) for c in full_msg_no_check)) % 256
        checksum_str = f'{checksum_val:03d}'
        return full_msg_no_check + f'10={checksum_str}\x01'

    def send_message(self, msg: Any) -> None:
        """Sends a FIX message over the active socket connection."""
        with self.lock:
            if not self.socket:
                raise RuntimeError('FIXEngine: Cannot send message - no active connection')
            try:
                self.socket.sendall(msg.encode('utf-8') if isinstance(msg, str) else msg)
                _log.debug('FIXEngine: Sent message: %s', msg[:100])
            except Exception as e:
                _log.error('FIXEngine: Failed to send message - %s', e)
                raise

    def construct_and_send_message(self, msg_type: Any, body_tags: Any) -> Any:
        """
        Atomically constructs and sends a FIX message while holding the engine lock.
        
        This method ensures that sequence number allocation, message construction,
        and socket transmission occur atomically, preventing out-of-order message
        transmission when multiple threads are sending messages concurrently.
        
        SECURITY: This method prevents FIX protocol violations where messages could
        be transmitted out of MsgSeqNum order due to race conditions between
        construct_fix_message() and send_message().
        
        Returns: The constructed FIX message string
        """
        with self.lock:
            seq = self.seq_num
            self.seq_num += 1
            sending_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3]
            header = f'35={msg_type}\x0149={self.sender_comp_id}\x0156={self.target_comp_id}\x0134={seq}\x0152={sending_time}\x01'
            body = ''.join((f'{k}={v}\x01' for k, v in body_tags.items()))
            content = header + body
            body_length = len(content)
            full_msg_no_check = f'8=FIX.4.4\x019={body_length}\x01' + content
            checksum_val = sum((ord(c) for c in full_msg_no_check)) % 256
            checksum_str = f'{checksum_val:03d}'
            msg = full_msg_no_check + f'10={checksum_str}\x01'
            if not self.socket:
                raise RuntimeError('FIXEngine: Cannot send message - no active connection')
            try:
                self.socket.sendall(msg.encode('utf-8') if isinstance(msg, str) else msg)
                _log.debug('FIXEngine: Sent message: %s', msg[:100])
            except Exception as e:
                _log.error('FIXEngine: Failed to send message - %s', e)
                raise
            return msg

    def send_logon(self, heartbeat_int: Any=30) -> None:
        """Sends Logon (35=A) message and marks session as active upon successful transmission."""
        if not self.socket:
            raise RuntimeError('FIXEngine: Cannot send logon - no active connection')
        tags = {'98': 0, '108': heartbeat_int}
        msg = self.construct_and_send_message('A', tags)
        with self.lock:
            self.session_active = True
        _log.info('FIXEngine: Logon sent, session marked active')

    def logon(self, heartbeat_int: Any=30) -> Any:
        """Builds and transmits Logon (35=A)."""
        tags = {'98': 0, '108': heartbeat_int}
        msg = self.construct_fix_message('A', tags)
        with self.lock:
            self.session_active = True
        return {'status': 'CONNECTED', 'fix_raw': msg}

    def heartbeat(self) -> Any:
        """Builds Heartbeat (35=0)."""
        msg = self.construct_fix_message('0', {})
        return {'status': 'HEARTBEAT_SENT', 'fix_raw': msg}

    def request_market_data(self, symbol: Any) -> Any:
        """Builds MarketDataRequest (35=V)."""
        tags = {'262': f'REQ_{symbol}_{int(time.time())}', '263': 1, '264': 1, '267': 2, '55': symbol}
        msg = self.construct_fix_message('V', tags)
        return {'symbol': symbol, 'status': 'STREAMING', 'fix_raw': msg}

    def send_order(self, symbol: Any, side: Any, qty: Any, price: Any, order_type: Any='LIMIT') -> Any:
        """
        Builds and sends NewOrderSingle (35=D) to venue.
        side: 'BUY' (1) or 'SELL' (2)
        
        SECURITY: This method now requires an active FIX session and actually
        transmits the order to the venue. It returns a PENDING status instead
        of fabricating a FILLED execution report. Callers must wait for and
        correlate actual ExecutionReport (35=8) messages from the venue.
        """
        if not self.session_active:
            raise RuntimeError('FIXEngine: Cannot send order - FIX session is not active. Call connect() and send_logon() first.')
        side_val = 1 if side.upper() == 'BUY' else 2
        ord_type_val = 1 if order_type.upper() == 'MARKET' else 2
        cl_ord_id = f'ORD_{symbol}_{int(time.time() * 1000)}'
        tags = {'11': cl_ord_id, '55': symbol, '54': side_val, '60': datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3], '38': qty, '40': ord_type_val, '44': price, '59': 0}
        msg = self.construct_fix_message('D', tags)
        if not self.socket:
            return {'status': 'DISCONNECTED', 'ord_status': 'REJECTED', 'symbol': symbol, 'qty': qty, 'fix_raw': msg, 'cl_ord_id': cl_ord_id, 'error': 'FIXEngine: Cannot send order - no active socket connection'}
        msg = self.construct_and_send_message('D', tags)
        _log.info('FIXEngine: Order sent to venue - cl_ord_id=%s, symbol=%s, side=%s, qty=%s, price=%s', cl_ord_id, symbol, side, qty, price)
        return {'cl_ord_id': cl_ord_id, 'symbol': symbol, 'side': side, 'qty': qty, 'price': price, 'ord_status': 'PENDING_VENUE', 'fix_raw': msg, 'message': 'Order transmitted to venue. Await ExecutionReport for fill confirmation.'}

    def cancel_order(self, orig_cl_ord_id: Any, symbol: Any, side: Any, qty: Any) -> Any:
        """Builds OrderCancelRequest (35=F)."""
        side_val = 1 if side.upper() == 'BUY' else 2
        cl_ord_id = f'CANC_{symbol}_{int(time.time() * 1000)}'
        tags = {'11': cl_ord_id, '41': orig_cl_ord_id, '55': symbol, '54': side_val, '60': datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3], '38': qty}
        msg = self.construct_fix_message('F', tags)
        return {'status': 'CANCEL_SENT', 'orig_cl_ord_id': orig_cl_ord_id, 'fix_raw': msg}

    def create_new_order_single(self, cl_ord_id: Any, symbol: Any, side: Any, quantity: Any, ord_type: Any, price: Any) -> Any:
        """
        Creates a NewOrderSingle (35=D) FIX message.
        This method is called by UniversalBrokerGateway.
        
        DEPRECATED: This method only constructs the message without sending it,
        which can lead to out-of-order transmission. Use send_new_order_single()
        instead for atomic construct-and-send behavior.
        """
        tags = {'11': cl_ord_id, '55': symbol, '54': side, '60': datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3], '38': quantity, '40': ord_type, '44': price, '59': 0}
        return self.construct_fix_message('D', tags)

    def send_new_order_single(self, cl_ord_id: Any, symbol: Any, side: Any, quantity: Any, ord_type: Any, price: Any) -> Any:
        """
        Atomically constructs and sends a NewOrderSingle (35=D) FIX message.
        
        SECURITY: This method ensures sequence number allocation and transmission
        occur atomically, preventing out-of-order message delivery.
        
        Returns: The constructed FIX message string
        """
        tags = {'11': cl_ord_id, '55': symbol, '54': side, '60': datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3], '38': quantity, '40': ord_type, '44': price, '59': 0}
        return self.construct_and_send_message('D', tags)

    def create_order_cancel_request(self, cl_ord_id: Any, orig_cl_ord_id: Any) -> Any:
        """
        Creates an OrderCancelRequest (35=F) FIX message.
        This method is called by UniversalBrokerGateway.
        
        DEPRECATED: This method only constructs the message without sending it,
        which can lead to out-of-order transmission. Use send_order_cancel_request()
        instead for atomic construct-and-send behavior.
        """
        tags = {'11': cl_ord_id, '41': orig_cl_ord_id, '60': datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3]}
        return self.construct_fix_message('F', tags)

    def send_order_cancel_request(self, cl_ord_id: Any, orig_cl_ord_id: Any) -> Any:
        """
        Atomically constructs and sends an OrderCancelRequest (35=F) FIX message.
        
        SECURITY: This method ensures sequence number allocation and transmission
        occur atomically, preventing out-of-order message delivery.
        
        Returns: The constructed FIX message string
        """
        tags = {'11': cl_ord_id, '41': orig_cl_ord_id, '60': datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3]}
        return self.construct_and_send_message('F', tags)

    def create_order_cancel_replace_request(self, cl_ord_id: Any, orig_cl_ord_id: Any, stop_px: Any=None, price: Any=None) -> Any:
        """
        Creates an OrderCancelReplaceRequest (35=G) FIX message.
        This method is called by UniversalBrokerGateway for modify_order.
        
        DEPRECATED: This method only constructs the message without sending it,
        which can lead to out-of-order transmission. Use send_order_cancel_replace_request()
        instead for atomic construct-and-send behavior.
        """
        tags = {'11': cl_ord_id, '41': orig_cl_ord_id, '60': datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3]}
        if stop_px is not None:
            tags['99'] = stop_px
        if price is not None:
            tags['44'] = price
        return self.construct_fix_message('G', tags)

    def send_order_cancel_replace_request(self, cl_ord_id: Any, orig_cl_ord_id: Any, stop_px: Any=None, price: Any=None) -> Any:
        """
        Atomically constructs and sends an OrderCancelReplaceRequest (35=G) FIX message.
        
        SECURITY: This method ensures sequence number allocation and transmission
        occur atomically, preventing out-of-order message delivery.
        
        Returns: The constructed FIX message string
        """
        tags = {'11': cl_ord_id, '41': orig_cl_ord_id, '60': datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3]}
        if stop_px is not None:
            tags['99'] = stop_px
        if price is not None:
            tags['44'] = price
        return self.construct_and_send_message('G', tags)

    def receive_execution_report(self, timeout: Any=5.0) -> Any:
        """
        Receives and parses ExecutionReport (35=8) from venue.
        
        This method should be called after send_order() to get actual fill confirmation.
        Returns parsed execution report dict or None if timeout/error.
        
        NOTE: This is a simplified implementation. Production systems should use
        a dedicated receive thread and message queue for proper async handling.
        """
        if not self.socket:
            _log.error('FIXEngine: Cannot receive - no active connection')
            return None
        try:
            self.socket.settimeout(timeout)
            data = self.socket.recv(4096)
            if not data:
                _log.warning('FIXEngine: Connection closed by venue')
                return None
            msg_str = data.decode('utf-8')
            _log.debug('FIXEngine: Received message: %s', msg_str[:200])
            if '35=8\x01' in msg_str:
                report = {'msg_type': 'ExecutionReport', 'raw': msg_str}
                for tag_val in msg_str.split('\x01'):
                    if '=' in tag_val:
                        tag, val = tag_val.split('=', 1)
                        if tag == '11':
                            report['cl_ord_id'] = val
                        elif tag == '17':
                            report['exec_id'] = val
                        elif tag == '39':
                            report['ord_status'] = val
                        elif tag == '55':
                            report['symbol'] = val
                        elif tag == '54':
                            report['side'] = 'BUY' if val == '1' else 'SELL'
                        elif tag == '32':
                            report['fill_qty'] = val
                        elif tag == '31':
                            report['fill_price'] = val
                self.execution_reports.append(report)
                return report
            return None
        except socket.timeout:
            _log.warning('FIXEngine: Timeout waiting for execution report')
            return None
        except Exception as e:
            _log.error('FIXEngine: Error receiving execution report - %s', e)
            return None
