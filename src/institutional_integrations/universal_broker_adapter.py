"""
Universal Broker Adapter & Platform Integration Architecture
-----------------------------------------------------------
Provides a protocol-agnostic, multi-broker gateway connecting EQATS / EQATS to:
 - MetaTrader 5 (MT5 IPC)
 - FIX 4.4 / 5.0 Protocol LPs
 - Institutional REST / WebSocket APIs
 - Interactive Brokers (IBKR TWS / Gateway API)
 - cTrader Open API
 - CCXT Crypto Exchanges (Binance, Bybit, OKX, Coinbase, Kraken, etc.)
 - High-Fidelity Paper Trading Simulator
"""

import hashlib
import hmac
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict

import database
from institutional_integrations.circuit_breaker import CircuitBreaker
from institutional_integrations.fix_engine import FIXEngine
from institutional_integrations.sebi_broker_adapter import (
    DhanHQAdapter,
    KiteConnectAdapter,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
    round_to_indian_quantity,
    round_to_indian_tick_size,
    validate_indian_product_tag,
)

_log = logging.getLogger(__name__)


class UniversalBrokerGateway:
    """
    Universal Multi-Protocol Broker Gateway.
    Abstracts connectivity across MT5, FIX 4.4/5.0, REST/WS, IBKR, cTrader, CCXT, and Simulator.
    """

    INDIAN_BROKER_PROTOCOLS = {
        "SEBI_BROKER",
        "KITE",
        "ZERODHA",
        "DHAN",
        "ANGELONE",
        "ANGEL",
        "KOTAK",
        "NEO",
        "UPSTOX",
        "ICICI",
        "FIVEPAISA",
        "IIFL",
        "XTS",
        "MOTILAL",
        "MO",
    }

    SUPPORTED_PROTOCOLS = [
        "MT5",
        "FIX",
        "REST_WS",
        "IBKR",
        "CTRADER",
        "CCXT",
        "SIMULATOR",
        "SEBI_BROKER",
        "KITE",
        "ZERODHA",
        "DHAN",
        "ANGELONE",
        "ANGEL",
        "KOTAK",
        "NEO",
        "UPSTOX",
        "ICICI",
        "FIVEPAISA",
        "IIFL",
        "XTS",
        "MOTILAL",
        "MO",
    ]

    def __init__(self, protocol: Any = "MT5", broker_config: Any = None) -> None:
        self.protocol = protocol.upper() if protocol else "MT5"
        self.broker_config = broker_config or {}
        self.is_connected_flag = False
        self.lock = threading.Lock()
        self.fix_engine = None
        if self.protocol not in self.SUPPORTED_PROTOCOLS:
            _log.error(
                "UniversalBrokerGateway: Unsupported protocol '%s' specified. Supported protocols: %s",
                self.protocol,
                ", ".join(self.SUPPORTED_PROTOCOLS),
            )
            raise ValueError(
                f"Unsupported protocol '{self.protocol}'. Supported protocols: {', '.join(self.SUPPORTED_PROTOCOLS)}",
            )

        # Configurable retry backoff delay (Round 3 FLAW-001)
        self.retry_backoff_delay = float(
            self.broker_config.get("retry_backoff_delay", 0.2),
        )

        # Response size and duration limits to prevent resource exhaustion
        # Default: 1MB max response size, 5 second total response deadline
        self.max_response_bytes = int(
            self.broker_config.get("max_response_bytes", 1048576),
        )  # 1MB default
        self.response_deadline_seconds = float(
            self.broker_config.get("response_deadline_seconds", 5.0),
        )

        # Circuit Breaker initialization
        cb_threshold = int(self.broker_config.get("failure_threshold", 5))
        cb_cooldown = float(self.broker_config.get("cooldown_seconds", 30.0))
        self._breaker = CircuitBreaker(
            failure_threshold=cb_threshold,
            cooldown_seconds=cb_cooldown,
        )

        self.sebi_adapter = None
        self.indian_client = None
        if self.protocol in self.INDIAN_BROKER_PROTOCOLS:
            api_key = self.broker_config.get("api_key", "")
            api_secret = self.broker_config.get("api_secret", "")
            access_token = self.broker_config.get("access_token", "")
            client_id = self.broker_config.get("client_id", "")
            password = self.broker_config.get("password", "")
            totp = self.broker_config.get("totp", "")
            is_sandbox = self.broker_config.get("is_sandbox", False)
            self.indian_client = UnifiedIndianBrokerClientAdapter(
                broker_name=self.protocol,
                api_key=api_key,
                api_secret=api_secret,
                access_token=access_token,
                client_id=client_id,
                password=password,
                totp=totp,
                is_sandbox=is_sandbox,
            )
            self.sebi_adapter = self.indian_client.adapter

        self._init_protocol_handler()

    def _init_protocol_handler(self) -> None:
        """Initializes internal engine or protocol driver based on configured protocol type."""
        if self.protocol == "FIX":
            sender_comp = self.broker_config.get("account_id", "EQATS_CLIENT")
            target_comp = self.broker_config.get("server", "LP_BROKER")
            self.fix_engine = FIXEngine(
                sender_comp_id=sender_comp,
                target_comp_id=target_comp,
            )
        elif self.protocol in ["REST_WS", "IBKR", "CTRADER", "CCXT"]:
            # Institutional REST/WS API connection parameters
            self.api_key = self.broker_config.get("api_key", "")
            self.api_secret = self.broker_config.get("api_secret", "")
            self.rest_url = self.broker_config.get("rest_url", "")
            self.ws_url = self.broker_config.get("ws_url", "")

            # Enforce HTTPS for REST endpoints to prevent plaintext credential/order exposure
            is_allowed_http = any(
                self.rest_url.startswith(prefix) for prefix in ("http://127.0.0.1", "http://localhost")
            )
            if self.rest_url and not (self.rest_url.startswith("https://") or is_allowed_http):
                _log.error(
                    "UniversalBrokerGateway: REST endpoint must use HTTPS. Rejecting insecure URL: %s",
                    self.rest_url,
                )
                raise ValueError(
                    f"REST endpoint must use HTTPS for secure transmission. Insecure URL rejected: {self.rest_url}",
                )

            if self.ws_url and not self.ws_url.startswith("wss://"):
                _log.warning(
                    "UniversalBrokerGateway: WebSocket endpoint should use WSS (secure). Insecure WS URL detected: %s",
                    self.ws_url,
                )

    def _generate_auth_headers(
        self,
        method: str = "POST",
        endpoint: str = "/v1/order",
        body_data: Any = None,
    ) -> dict[str, str]:
        """
        Generates authenticated request headers including API key and HMAC signature.

        This implements a standard broker authentication pattern using:
        - API Key in X-API-Key header
        - HMAC-SHA256 signature in X-Signature header
        - Timestamp nonce in X-Timestamp header

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            body_data: Request body bytes for signature calculation

        Returns:
            dict: Headers including Content-Type, API key, timestamp, and signature
        """
        headers = {"Content-Type": "application/json"}

        # Only add authentication if credentials are configured
        if not self.api_key or not self.api_secret:
            _log.warning(
                "UniversalBrokerGateway: API credentials not configured. Request will be sent without authentication headers.",
            )
            return headers

        # Add API key header
        headers["X-API-Key"] = self.api_key

        # Generate timestamp nonce (milliseconds since epoch)
        timestamp = str(int(time.time() * 1000))
        headers["X-Timestamp"] = timestamp

        # Construct signature payload: METHOD + ENDPOINT + TIMESTAMP + BODY
        # This is a common pattern used by institutional broker APIs
        signature_payload = f"{method}{endpoint}{timestamp}"
        if body_data:
            signature_payload += body_data.decode("utf-8") if isinstance(body_data, bytes) else str(body_data)

        # Generate HMAC-SHA256 signature
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers["X-Signature"] = signature

        _log.debug(
            "Generated authenticated headers for %s %s with timestamp %s",
            method,
            endpoint,
            timestamp,
        )

        return headers

    def _read_response_safely(self, response: Any) -> Any:
        """
        Reads HTTP response with size and duration limits to prevent resource exhaustion.

        This method mitigates the risk of a compromised or malicious broker endpoint
        causing excessive memory allocation or keeping synchronous order execution
        occupied through slow-drip responses.

        Args:
            response: urllib response object with read() method

        Returns:
            bytes: Response body data

        Raises:
            ValueError: If response exceeds size limit or duration deadline
            TimeoutError: If total response duration exceeds deadline
        """
        start_time = time.time()
        chunks = []
        total_bytes = 0
        chunk_size = 8192  # Read in 8KB chunks

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.response_deadline_seconds:
                _log.error(
                    "Response reading exceeded deadline of %.1fs (elapsed: %.1fs, bytes read: %d)",
                    self.response_deadline_seconds,
                    elapsed,
                    total_bytes,
                )
                raise TimeoutError(
                    f"Response reading exceeded deadline of {self.response_deadline_seconds}s "
                    f"(elapsed: {elapsed:.1f}s, bytes read: {total_bytes})",
                )

            # Read next chunk with remaining deadline as timeout
            try:
                chunk = response.read(chunk_size)
            except TimeoutError:
                if chunks:
                    _log.warning(
                        "Socket timeout after reading %d bytes in %.1fs",
                        total_bytes,
                        elapsed,
                    )
                raise

            if not chunk:
                break

            total_bytes += len(chunk)

            # Check size limit
            if total_bytes > self.max_response_bytes:
                _log.error(
                    "Response size %d bytes exceeds maximum allowed %d bytes",
                    total_bytes,
                    self.max_response_bytes,
                )
                raise ValueError(
                    f"Response size {total_bytes} bytes exceeds maximum allowed {self.max_response_bytes} bytes",
                )

            chunks.append(chunk)
            if len(chunk) < chunk_size:
                break

        response_data = b"".join(chunks)

        _log.debug(
            "Successfully read %d bytes in %.3fs",
            total_bytes,
            time.time() - start_time,
        )

        return response_data

    def connect(self) -> Any:
        """Establishes connection using the configured protocol adapter."""
        with self.lock:
            if self.protocol == "SIMULATOR":
                self.is_connected_flag = True
                return True
            self.indian_client = None
        if self.protocol in self.INDIAN_BROKER_PROTOCOLS:
            api_key = self.broker_config.get("api_key", "")
            api_secret = self.broker_config.get("api_secret", "")
            access_token = self.broker_config.get("access_token", "")
            client_id = self.broker_config.get("client_id", "")
            password = self.broker_config.get("password", "")
            totp = self.broker_config.get("totp", "")
            is_sandbox = self.broker_config.get("is_sandbox", False)
            self.indian_client = UnifiedIndianBrokerClientAdapter(
                broker_name=self.protocol,
                api_key=api_key,
                api_secret=api_secret,
                access_token=access_token,
                client_id=client_id,
                password=password,
                totp=totp,
                is_sandbox=is_sandbox,
            )
            self.sebi_adapter = self.indian_client.adapter
            if self.sebi_adapter:
                self.is_connected_flag = self.sebi_adapter.connect()
                return self.is_connected_flag
            self.is_connected_flag = True
            return True
        if self.protocol == "FIX":
            try:
                target_host = self.broker_config.get("rest_url", "127.0.0.1")
                target_port = int(
                    self.broker_config.get("extra_params", {}).get("port", 9800),
                )
                self.fix_engine.connect(target_host, target_port)
                self.fix_engine.send_logon()
                self.is_connected_flag = True
                return True
            except Exception as e:
                print(f"Universal Broker Gateway [FIX] Connection Error: {e}")
                self.is_connected_flag = False
                return False
        if self.protocol == "MT5":
            try:
                import MetaTrader5 as mt5

                if not mt5.initialize():
                    self.is_connected_flag = False
                    return False
                self.is_connected_flag = True
                return True
            except ImportError:
                print(
                    "Universal Broker Gateway [MT5]: MetaTrader5 package not available (requires Windows).",
                )
                self.is_connected_flag = False
                return False

        # REST_WS, IBKR, CTRADER, CCXT protocol interfaces require rest_url
        if self.protocol in ["REST_WS", "IBKR", "CTRADER", "CCXT"]:
            # Validate that rest_url is configured for REST-like protocols
            if not hasattr(self, "rest_url") or not self.rest_url:
                _log.error(
                    "UniversalBrokerGateway: Protocol %s requires 'rest_url' configuration. "
                    "Connection rejected to prevent fail-open execution.",
                    self.protocol,
                )
                print(
                    f"Universal Broker Gateway [{self.protocol}] Connection Error: "
                    f"'rest_url' must be configured for protocol {self.protocol}. "
                    f"Cannot establish connection without valid endpoint.",
                )
                self.is_connected_flag = False
                return False

            # Endpoint is configured, mark as connected
            self.is_connected_flag = True
            print(
                f"Universal Broker Gateway: Connected via protocol [{self.protocol}] for Broker [{self.broker_config.get('broker_name', 'Default')}] at endpoint {self.rest_url}",
            )
            return True

        # Reject unsupported protocols to prevent fail-open fallback
        _log.error(
            "UniversalBrokerGateway: Unsupported protocol '%s'. Supported protocols: %s. Connection rejected.",
            self.protocol,
            ", ".join(self.SUPPORTED_PROTOCOLS),
        )
        print(
            f"Universal Broker Gateway Connection Error: "
            f"Protocol '{self.protocol}' is not supported. "
            f"Supported protocols: {', '.join(self.SUPPORTED_PROTOCOLS)}",
        )
        self.is_connected_flag = False
        return False

    def is_connected(self) -> Any:
        """Returns active connection status."""
        if self.protocol == "SIMULATOR":
            return True
        if self.protocol in self.INDIAN_BROKER_PROTOCOLS:
            if self.sebi_adapter:
                return self.sebi_adapter.is_connected()
            return self.is_connected_flag
        if self.protocol == "MT5":
            try:
                import MetaTrader5 as mt5

                info = mt5.terminal_info()
                return info is not None
            except Exception:
                return False
        return self.is_connected_flag

    def disconnect(self) -> None:
        """Disconnects safely from the broker gateway."""
        with self.lock:
            if self.protocol == "FIX" and self.fix_engine:
                try:
                    self.fix_engine.close()
                except Exception:
                    pass
            elif self.protocol == "MT5":
                try:
                    import MetaTrader5 as mt5

                    mt5.shutdown()
                except Exception:
                    pass
            self.is_connected_flag = False

    def get_account_info(self) -> Any:
        """Retrieves unified account balance, equity, currency, and mode."""
        if self.protocol == "MT5":
            try:
                import MetaTrader5 as mt5

                acc = mt5.account_info()
                if acc:
                    return {
                        "balance": float(acc.balance),
                        "equity": float(acc.equity),
                        "currency": str(acc.currency),
                        "is_demo": acc.trade_mode != 2,
                        "leverage": getattr(acc, "leverage", 100),
                        "protocol": "MT5",
                    }
            except Exception:
                pass
        creds = database.get_broker_credentials()
        if creds is None:
            creds = {"leverage": "1:100", "environment": "Demo"}

        leverage_str = creds.get("leverage", "1:100")
        return {
            "balance": 10000.0,
            "equity": 10000.0,
            "currency": "USD",
            "is_demo": creds.get("environment", "Demo").lower() != "live",
            "leverage": leverage_str,
            "protocol": self.protocol,
        }

    def get_symbol_volume_constraints(self, symbol: Any) -> Any:
        """
        Returns broker volume constraints for the symbol.
        SECURITY: Queries the SQLite broker_profiles database for operational volume bounds,
        falling back to protocol default constraints.
        """
        server = self.broker_config.get("server", "")
        broker_name = self.broker_config.get("broker_name", "")
        profile = None
        for key_candidate in [server, broker_name, self.protocol]:
            if key_candidate:
                profile = database.get_broker_profile(key_candidate)
                if profile:
                    break
        vol_min = float(profile["volume_min"]) if profile and "volume_min" in profile else 0.01
        vol_max = float(profile["volume_max"]) if profile and "volume_max" in profile else 100.0
        vol_step = float(profile["volume_step"]) if profile and "volume_step" in profile else 0.01
        if self.protocol == "MT5":
            try:
                import MetaTrader5 as mt5

                info = mt5.symbol_info(symbol)
                if info:
                    vol_min = getattr(info, "volume_min", vol_min) or vol_min
                    vol_max = getattr(info, "volume_max", vol_max) or vol_max
                    vol_step = getattr(info, "volume_step", vol_step) or vol_step
            except Exception as e:
                _log.warning("Failed to get MT5 symbol info for %s: %s", symbol, e)
        return {"volume_min": vol_min, "volume_max": vol_max, "volume_step": vol_step}

    def _reconcile_order_status(self, client_order_id: Any) -> Any:
        """
        Queries the broker to check if an order with the given client_order_id was accepted.
        Returns dict with 'found': bool, 'ticket': str, 'price': float if found.
        This prevents duplicate order submission after ambiguous timeout.
        """
        if not hasattr(self, "rest_url") or not self.rest_url:
            return {"found": False}

        try:
            # Query broker order status endpoint with client_order_id
            query_endpoint = f"/v1/order/status?client_order_id={client_order_id}"
            query_url = f"{self.rest_url}{query_endpoint}"

            # Generate authenticated headers for GET request
            headers = self._generate_auth_headers(
                method="GET",
                endpoint=query_endpoint,
                body_data=None,
            )

            req = urllib.request.Request(query_url, headers=headers)

            with urllib.request.urlopen(req, timeout=3.0) as resp:
                response_data = self._read_response_safely(resp)
                status_data = json.loads(response_data.decode("utf-8"))

                # If broker confirms the order exists, return its details
                if status_data.get("found") or status_data.get("status") in [
                    "ACCEPTED",
                    "FILLED",
                    "PARTIAL",
                ]:
                    # Validate that broker returned a valid ticket/order_id
                    broker_ticket = status_data.get("ticket") or status_data.get(
                        "order_id",
                    )
                    if not broker_ticket or str(broker_ticket).strip() == "":
                        _log.error(
                            "Order reconciliation: client_order_id %s found at broker but missing valid ticket. "
                            "Response: %s",
                            client_order_id,
                            status_data,
                        )
                        return {"found": False}

                    _log.info(
                        "Order reconciliation: client_order_id %s found at broker with status %s, ticket %s",
                        client_order_id,
                        status_data.get("status", "UNKNOWN"),
                        broker_ticket,
                    )
                    return {
                        "found": True,
                        "ticket": str(broker_ticket),
                        "price": float(status_data.get("price", 0.0)),
                        "status": status_data.get("status", "ACCEPTED"),
                    }
                return {"found": False}

        except Exception as e:
            # If reconciliation query fails, we cannot confirm order status
            _log.warning(
                "Order reconciliation query failed for client_order_id %s: %s",
                client_order_id,
                e,
            )
            return {"found": False}

    def execute_order(
        self,
        symbol: Any,
        order_type: Any,
        lot_size: Any,
        sl: Any,
        tp: Any,
        product: Any = None,
        exchange: Any = "NSE",
        order_kind: Any = "MARKET",
    ) -> Any:
        """Executes trade order using active protocol route with circuit breaker, configurable retry backoff, socket 3.0s timeout guards, and explicit exception diagnostics."""
        # SECURITY: Validate order_type to prevent fail-open direction encoding
        # Only accept case-insensitive "BUY" or "SELL" - reject all other values
        if not isinstance(order_type, str) or order_type.upper() not in ("BUY", "SELL"):
            _log.error(
                "UniversalBrokerGateway: Invalid order_type '%s' for %s. Must be 'BUY' or 'SELL'.",
                order_type,
                symbol,
            )
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": f"Invalid order_type '{order_type}'. Must be 'BUY' or 'SELL'.",
                "reason": "INVALID_DIRECTION",
                "protocol": self.protocol,
            }

        # SECURITY: Validate lot_size to prevent invalid quantity submission
        # Enforce finite, positive, and within reasonable bounds (0.01 to 100.0)
        try:
            lot_size_float = float(lot_size)
        except (TypeError, ValueError):
            _log.error(
                "UniversalBrokerGateway: Invalid lot_size '%s' for %s. Must be numeric.",
                lot_size,
                symbol,
            )
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": f"Invalid lot_size '{lot_size}'. Must be a numeric value.",
                "reason": "INVALID_QUANTITY",
                "protocol": self.protocol,
            }

        # Check for finite, positive value
        import math

        if not math.isfinite(lot_size_float) or lot_size_float <= 0.0:
            _log.error(
                "UniversalBrokerGateway: lot_size %s for %s is not finite and positive.",
                lot_size_float,
                symbol,
            )
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": f"Invalid lot_size '{lot_size_float}': must be finite and positive.",
                "reason": "INVALID_QUANTITY",
                "protocol": self.protocol,
            }

        # Enforce minimum and maximum bounds to prevent fat-finger and venue constraint violations
        # These bounds align with standard broker constraints and fat-finger limits
        MIN_LOT_SIZE = 0.01
        MAX_LOT_SIZE = 100.0

        if lot_size_float < MIN_LOT_SIZE:
            _log.error(
                "UniversalBrokerGateway: lot_size %s for %s below minimum %s.",
                lot_size_float,
                symbol,
                MIN_LOT_SIZE,
            )
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": f"lot_size {lot_size_float} below minimum {MIN_LOT_SIZE}.",
                "reason": "QUANTITY_TOO_SMALL",
                "protocol": self.protocol,
            }

        if lot_size_float > MAX_LOT_SIZE:
            _log.error(
                "UniversalBrokerGateway: lot_size %s for %s exceeds maximum %s.",
                lot_size_float,
                symbol,
                MAX_LOT_SIZE,
            )
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": f"lot_size {lot_size_float} exceeds maximum {MAX_LOT_SIZE}.",
                "reason": "QUANTITY_TOO_LARGE",
                "protocol": self.protocol,
            }

        # Circuit Breaker check before attempting order execution
        if not self._breaker.allow():
            _log.warning(
                "UniversalBrokerGateway: Order for %s blocked by OPEN circuit breaker.",
                symbol,
            )
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": "circuit_open",
                "reason": "circuit_open",
                "protocol": self.protocol,
            }
        validated_product = None
        if product or self.protocol in self.INDIAN_BROKER_PROTOCOLS:
            validated_product = validate_indian_product_tag(product, default="CNC")
        if self.protocol == "SIMULATOR":
            ticket = f"SIM_{uuid.uuid4().hex[:12].upper()}"
            self._breaker.record_success()
            res = {
                "success": True,
                "ticket": ticket,
                "price": 0.0,
                "error": "",
                "protocol": "SIMULATOR",
            }
            if validated_product:
                res["product"] = validated_product
            return res
        if self.protocol in self.INDIAN_BROKER_PROTOCOLS and self.sebi_adapter:
            sebi_req = SEBIOrderRequest(
                symbol=symbol,
                order_type=order_type.upper(),
                quantity=round_to_indian_quantity(lot_size_float),
                price=0.0,
                sl=round_to_indian_tick_size(sl) if sl > 0 else 0.0,
                tp=round_to_indian_tick_size(tp) if tp > 0 else 0.0,
                product=validated_product or "CNC",
                exchange=exchange.upper() if exchange else "NSE",
                order_kind=order_kind.upper() if order_kind else "MARKET",
            )
            sebi_res = self.sebi_adapter.execute_order(sebi_req)
            if sebi_res.success:
                self._breaker.record_success()
                res = {
                    "success": True,
                    "ticket": sebi_res.ticket,
                    "price": sebi_res.price,
                    "status": sebi_res.status,
                    "error": "",
                    "protocol": self.protocol,
                }
                if validated_product:
                    res["product"] = validated_product
                return res
            self._breaker.record_failure()
            res = {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": sebi_res.error or "SEBI order execution failed",
                "protocol": self.protocol,
            }
            if validated_product:
                res["product"] = validated_product
            return res

        if self.protocol in ["REST_WS", "CCXT", "CTRADER", "IBKR"] and hasattr(self, "rest_url") and self.rest_url:
            # Generate stable client_order_id for idempotent retry
            client_order_id = f"EQATS_{uuid.uuid4().hex[:16]}_{int(time.time() * 1000)}"

            payload = json.dumps(
                {
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                    "side": order_type,  # Already validated as "BUY" or "SELL"
                    "volume": lot_size_float,  # Use validated float quantity
                    "sl": sl,
                    "tp": tp,
                },
            ).encode("utf-8")

            # Generate authenticated headers with API key and HMAC signature
            endpoint = "/v1/order"
            headers = self._generate_auth_headers(
                method="POST",
                endpoint=endpoint,
                body_data=payload,
            )

            req = urllib.request.Request(
                f"{self.rest_url}{endpoint}",
                data=payload,
                headers=headers,
            )

            max_attempts = 2
            last_err = None
            for attempt in range(max_attempts):
                try:
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        http_status = 200
                        if hasattr(resp, "getcode"):
                            code_val = resp.getcode()
                            if isinstance(code_val, int):
                                http_status = code_val
                        elif hasattr(resp, "status"):
                            status_val = resp.status
                            if isinstance(status_val, int):
                                http_status = status_val
                        if http_status not in (200, 201):
                            last_err = f"HTTP {http_status}: Broker returned non-success status code"
                            _log.error(
                                "Universal Broker REST Gateway order rejected with HTTP %d for %s",
                                http_status,
                                symbol,
                            )
                            self._breaker.record_failure()
                            return {
                                "success": False,
                                "ticket": "",
                                "price": 0.0,
                                "error": last_err,
                                "reason": "HTTP_ERROR",
                                "protocol": self.protocol,
                            }

                        response_data = self._read_response_safely(resp)
                        res_data = json.loads(response_data.decode("utf-8"))

                        # Validate application-level status - must be ACCEPTED, FILLED, or PARTIAL
                        order_status = res_data.get("status", "").upper()
                        if (
                            not order_status
                            and (res_data.get("ticket") or res_data.get("order_id"))
                            and float(res_data.get("price", 0.0)) > 0
                        ):
                            order_status = "ACCEPTED"
                        if order_status not in ("ACCEPTED", "FILLED", "PARTIAL"):
                            # Order was rejected, pending, or status is missing/invalid
                            last_err = f"Order not accepted by broker. Status: {order_status or 'MISSING'}"
                            _log.error(
                                "Universal Broker REST Gateway order rejected for %s. Status: %s, Response: %s",
                                symbol,
                                order_status or "MISSING",
                                res_data,
                            )
                            self._breaker.record_failure()
                            return {
                                "success": False,
                                "ticket": "",
                                "price": 0.0,
                                "error": last_err,
                                "reason": order_status or "INVALID_STATUS",
                                "protocol": self.protocol,
                            }

                        # Validate broker-issued ticket - must be present and non-empty
                        broker_ticket = res_data.get("ticket") or res_data.get(
                            "order_id",
                        )
                        if not broker_ticket or str(broker_ticket).strip() == "":
                            last_err = "Broker response missing valid order ticket/ID"
                            _log.error(
                                "Universal Broker REST Gateway order for %s missing broker ticket. Response: %s",
                                symbol,
                                res_data,
                            )
                            self._breaker.record_failure()
                            return {
                                "success": False,
                                "ticket": "",
                                "price": 0.0,
                                "error": last_err,
                                "reason": "MISSING_TICKET",
                                "protocol": self.protocol,
                            }

                        # Validate execution price - must be present and positive
                        execution_price = res_data.get("price")
                        if execution_price is None or float(execution_price) <= 0.0:
                            last_err = f"Broker response missing valid execution price: {execution_price}"
                            _log.error(
                                "Universal Broker REST Gateway order for %s has invalid price. Response: %s",
                                symbol,
                                res_data,
                            )
                            self._breaker.record_failure()
                            return {
                                "success": False,
                                "ticket": "",
                                "price": 0.0,
                                "error": last_err,
                                "reason": "INVALID_PRICE",
                                "protocol": self.protocol,
                            }

                        # All validations passed - order was successfully accepted/filled
                        _log.info(
                            "Universal Broker REST Gateway order accepted for %s: ticket=%s, price=%s, status=%s",
                            symbol,
                            broker_ticket,
                            execution_price,
                            order_status,
                        )
                        self._breaker.record_success()
                        return {
                            "success": True,
                            "ticket": str(broker_ticket),
                            "price": float(execution_price),
                            "error": "",
                            "protocol": self.protocol,
                            "status": order_status,
                        }
                except TimeoutError as e:
                    last_err = f"Socket Timeout 3.0s: {e}"
                    _log.warning(
                        "Universal Broker REST Gateway socket timeout (attempt %d/%d) for %s: %s",
                        attempt + 1,
                        max_attempts,
                        symbol,
                        e,
                    )

                    # After timeout, reconcile to check if order was actually accepted
                    _log.info(
                        "Attempting order reconciliation for client_order_id %s after timeout",
                        client_order_id,
                    )
                    reconcile_result = self._reconcile_order_status(client_order_id)

                    if reconcile_result.get("found"):
                        # Order was accepted despite timeout - return success
                        _log.info(
                            "Order reconciliation successful: order %s was accepted at broker",
                            reconcile_result.get("ticket"),
                        )
                        self._breaker.record_success()
                        return {
                            "success": True,
                            "ticket": reconcile_result.get("ticket", ""),
                            "price": reconcile_result.get("price", 0.0),
                            "error": "",
                            "protocol": self.protocol,
                            "reconciled": True,
                        }

                    # Order not found at broker - safe to retry with same client_order_id
                    if attempt < max_attempts - 1:
                        time.sleep(self.retry_backoff_delay)
                except (
                    socket.gaierror,
                    ConnectionRefusedError,
                    ConnectionResetError,
                    urllib.error.URLError,
                ) as e:
                    last_err = f"Network Unreachable: {e}"
                    _log.error(
                        "Universal Broker REST Gateway network unreachable exception on %s: %s",
                        symbol,
                        e,
                    )
                    self._breaker.record_failure(e)
                    return {
                        "success": False,
                        "ticket": "",
                        "price": 0.0,
                        "error": last_err,
                        "reason": "NETWORK_UNREACHABLE",
                        "protocol": self.protocol,
                    }
                except Exception as e:
                    last_err = str(e)
                    _log.warning(
                        "Universal Broker REST Gateway order execution exception (attempt %d/%d) for %s: %s",
                        attempt + 1,
                        max_attempts,
                        symbol,
                        e,
                    )

                    # Attempt reconciliation for ambiguous errors that might hide accepted orders
                    _log.info(
                        "Attempting order reconciliation for client_order_id %s after exception",
                        client_order_id,
                    )
                    reconcile_result = self._reconcile_order_status(client_order_id)

                    if reconcile_result.get("found"):
                        # Order was accepted despite exception - return success
                        _log.info(
                            "Order reconciliation successful: order %s was accepted at broker",
                            reconcile_result.get("ticket"),
                        )
                        self._breaker.record_success()
                        return {
                            "success": True,
                            "ticket": reconcile_result.get("ticket", ""),
                            "price": reconcile_result.get("price", 0.0),
                            "error": "",
                            "protocol": self.protocol,
                            "reconciled": True,
                        }

                    # Order not found - safe to retry with same client_order_id
                    if attempt < max_attempts - 1:
                        time.sleep(self.retry_backoff_delay)
            self._breaker.record_failure()
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": last_err or "Execution failed after retries",
                "protocol": self.protocol,
            }
        if self.protocol == "FIX" and self.fix_engine:
            try:
                # SECURITY: order_type and lot_size are already validated at function entry
                # Safe to convert validated order_type to FIX side code
                side = "1" if order_type.upper() == "BUY" else "2"
                cl_ord_id = f"EQATS_{int(time.time() * 1000)}"
                # SECURITY FIX: Use atomic send method to prevent out-of-order transmission
                self.fix_engine.send_new_order_single(
                    cl_ord_id=cl_ord_id,
                    symbol=symbol,
                    side=side,
                    quantity=lot_size_float,  # Use validated float quantity
                    ord_type="2",  # Limit / Market
                    price=0.0,
                )
                self._breaker.record_success()
                return {
                    "success": True,
                    "ticket": cl_ord_id,
                    "price": 0.0,
                    "error": "",
                    "protocol": "FIX",
                }
            except (socket.gaierror, ConnectionRefusedError, ConnectionResetError) as e:
                _log.error("Universal Broker FIX network unreachable: %s", e)
                self._breaker.record_failure(e)
                return {
                    "success": False,
                    "ticket": "",
                    "price": 0.0,
                    "error": f"Network Unreachable: {e}",
                    "reason": "NETWORK_UNREACHABLE",
                    "protocol": "FIX",
                }
            except Exception as e:
                _log.warning("Universal Broker FIX order execution exception: %s", e)
                self._breaker.record_failure(e)
                return {
                    "success": False,
                    "ticket": "",
                    "price": 0.0,
                    "error": f"FIX order execution error: {e}",
                }

        # Fail-closed: No valid execution path was taken
        # This prevents phantom orders when rest_url is missing or protocol is misconfigured
        _log.error(
            "UniversalBrokerGateway: Order execution failed - no valid execution path for protocol %s. "
            "This indicates a configuration error (missing rest_url) or unsupported protocol.",
            self.protocol,
        )
        self._breaker.record_failure()
        return {
            "success": False,
            "ticket": "",
            "price": 0.0,
            "error": f"No valid execution path for protocol {self.protocol}. Check configuration.",
            "reason": "CONFIGURATION_ERROR",
            "protocol": self.protocol,
        }

    def close_order(self, ticket: Any, reason: Any = "MANUAL") -> Any:
        """Closes an active order on the live broker gateway."""
        if not self.is_connected():
            return {
                "success": False,
                "price": 0.0,
                "profit": 0.0,
                "error": "Gateway not connected.",
            }
        if not self._breaker.allow():
            _log.warning(
                "UniversalBrokerGateway: Close order for ticket %s blocked by OPEN circuit breaker.",
                ticket,
            )
            return {
                "success": False,
                "price": 0.0,
                "profit": 0.0,
                "error": "circuit_open",
            }
        if self.protocol == "MT5":
            try:
                import MetaTrader5 as mt5

                positions = mt5.positions_get(ticket=int(ticket))
                if not positions or len(positions) == 0:
                    return {
                        "success": False,
                        "price": 0.0,
                        "profit": 0.0,
                        "error": f"Ticket {ticket} not found in MT5.",
                    }
                pos = positions[0]
                symbol = pos.symbol
                lot_size = pos.volume
                direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                close_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
                price_info = mt5.symbol_info_tick(symbol)
                close_price = price_info.bid if direction == "BUY" else price_info.ask
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": int(ticket),
                    "symbol": symbol,
                    "volume": lot_size,
                    "type": close_type,
                    "price": close_price,
                    "deviation": 20,
                    "magic": 998822,
                    "comment": f"Close_{reason}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    profit_est = float(getattr(pos, "profit", 0.0))
                    self._breaker.record_success()
                    return {
                        "success": True,
                        "price": float(result.price),
                        "profit": profit_est,
                        "error": "",
                    }
                error_msg = f"MT5 close failed: {(result.comment if result else 'Unknown error')}"
                self._breaker.record_failure()
                return {
                    "success": False,
                    "price": 0.0,
                    "profit": 0.0,
                    "error": error_msg,
                }
            except Exception as e:
                _log.error("UniversalBrokerGateway MT5 close_order exception: %s", e)
                self._breaker.record_failure(e)
                return {
                    "success": False,
                    "price": 0.0,
                    "profit": 0.0,
                    "error": str(e),
                }

        if self.protocol in ["REST_WS", "CCXT", "CTRADER", "IBKR"] and hasattr(self, "rest_url") and self.rest_url:
            payload = json.dumps({"ticket": str(ticket), "reason": reason}).encode(
                "utf-8",
            )

            # Generate authenticated headers with API key and HMAC signature
            endpoint = "/v1/order/close"
            headers = self._generate_auth_headers(
                method="POST",
                endpoint=endpoint,
                body_data=payload,
            )

            req = urllib.request.Request(
                f"{self.rest_url}{endpoint}",
                data=payload,
                headers=headers,
            )

            max_attempts = 2
            last_err = None
            for attempt in range(max_attempts):
                try:
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        response_data = self._read_response_safely(resp)
                        res_data = json.loads(response_data.decode("utf-8"))
                        self._breaker.record_success()
                        return {
                            "success": res_data.get("success", True),
                            "price": float(res_data.get("price", 0.0)),
                            "profit": float(res_data.get("profit", 0.0)),
                            "error": res_data.get("error", ""),
                        }
                except TimeoutError as e:
                    last_err = f"Socket Timeout 3.0s: {e}"
                    _log.warning(
                        "Universal Broker REST Gateway close_order timeout (attempt %d/%d) for ticket %s: %s",
                        attempt + 1,
                        max_attempts,
                        ticket,
                        e,
                    )
                    if attempt < max_attempts - 1:
                        time.sleep(self.retry_backoff_delay)
                except (
                    socket.gaierror,
                    ConnectionRefusedError,
                    ConnectionResetError,
                    urllib.error.URLError,
                ) as e:
                    last_err = f"Network Unreachable: {e}"
                    _log.error(
                        "Universal Broker REST Gateway close_order network unreachable: %s",
                        e,
                    )
                    self._breaker.record_failure(e)
                    return {
                        "success": False,
                        "price": 0.0,
                        "profit": 0.0,
                        "error": last_err,
                    }
                except Exception as e:
                    last_err = str(e)
                    _log.warning(
                        "Universal Broker REST Gateway close_order exception (attempt %d/%d): %s",
                        attempt + 1,
                        max_attempts,
                        e,
                    )
                    if attempt < max_attempts - 1:
                        time.sleep(self.retry_backoff_delay)
            self._breaker.record_failure()
            return {
                "success": False,
                "price": 0.0,
                "profit": 0.0,
                "error": last_err or "Close order failed after retries",
            }
        if self.protocol == "FIX" and self.fix_engine:
            try:
                cl_ord_id = f"EQATS_CLOSE_{int(time.time() * 1000)}"
                # SECURITY FIX: Use atomic send method to prevent out-of-order transmission
                self.fix_engine.send_order_cancel_request(
                    cl_ord_id=cl_ord_id,
                    orig_cl_ord_id=str(ticket),
                )
                self._breaker.record_success()
                return {"success": True, "price": 0.0, "profit": 0.0, "error": ""}
            except Exception as e:
                _log.error("UniversalBrokerGateway FIX close_order exception: %s", e)
                self._breaker.record_failure(e)
                return {"success": False, "price": 0.0, "profit": 0.0, "error": str(e)}
        _log.warning(
            "UniversalBrokerGateway: close_order not fully implemented for protocol %s",
            self.protocol,
        )
        return {
            "success": False,
            "price": 0.0,
            "profit": 0.0,
            "error": f"close_order not implemented for protocol {self.protocol}",
        }

    def modify_order(self, ticket: Any, sl: Any, tp: Any) -> Any:
        """Modifies Stop Loss and Take Profit levels of an active trade on the live broker gateway."""
        if not self.is_connected():
            return False
        if not self._breaker.allow():
            _log.warning(
                "UniversalBrokerGateway: Modify order for ticket %s blocked by OPEN circuit breaker.",
                ticket,
            )
            return False
        if self.protocol == "MT5":
            try:
                import MetaTrader5 as mt5

                positions = mt5.positions_get(ticket=int(ticket))
                if not positions or len(positions) == 0:
                    return False

                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": int(ticket),
                    "sl": float(round(sl, 5)),
                    "tp": float(round(tp, 5)),
                }

                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    self._breaker.record_success()
                    return True
                self._breaker.record_failure()
                return False
            except Exception as e:
                _log.error("UniversalBrokerGateway MT5 modify_order exception: %s", e)
                self._breaker.record_failure(e)
                return False

        if self.protocol in ["REST_WS", "CCXT", "CTRADER", "IBKR"] and hasattr(self, "rest_url") and self.rest_url:
            payload = json.dumps({"ticket": str(ticket), "sl": sl, "tp": tp}).encode(
                "utf-8",
            )

            # Generate authenticated headers with API key and HMAC signature
            endpoint = "/v1/order/modify"
            headers = self._generate_auth_headers(
                method="POST",
                endpoint=endpoint,
                body_data=payload,
            )

            req = urllib.request.Request(
                f"{self.rest_url}{endpoint}",
                data=payload,
                headers=headers,
            )

            max_attempts = 2
            for attempt in range(max_attempts):
                try:
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        response_data = self._read_response_safely(resp)
                        res_data = json.loads(response_data.decode("utf-8"))
                        self._breaker.record_success()
                        return res_data.get("success", True)
                except TimeoutError as e:
                    _log.warning(
                        "Universal Broker REST Gateway modify_order timeout (attempt %d/%d): %s",
                        attempt + 1,
                        max_attempts,
                        e,
                    )
                    if attempt < max_attempts - 1:
                        time.sleep(self.retry_backoff_delay)
                except (
                    socket.gaierror,
                    ConnectionRefusedError,
                    ConnectionResetError,
                    urllib.error.URLError,
                ) as e:
                    _log.error(
                        "Universal Broker REST Gateway modify_order network unreachable: %s",
                        e,
                    )
                    self._breaker.record_failure(e)
                    return False
                except Exception as e:
                    _log.warning(
                        "Universal Broker REST Gateway modify_order exception (attempt %d/%d): %s",
                        attempt + 1,
                        max_attempts,
                        e,
                    )
                    if attempt < max_attempts - 1:
                        time.sleep(self.retry_backoff_delay)
            self._breaker.record_failure()
            return False
        if self.protocol == "FIX" and self.fix_engine:
            try:
                cl_ord_id = f"EQATS_MODIFY_{int(time.time() * 1000)}"
                # SECURITY FIX: Use atomic send method to prevent out-of-order transmission
                self.fix_engine.send_order_cancel_replace_request(
                    cl_ord_id=cl_ord_id,
                    orig_cl_ord_id=str(ticket),
                    stop_px=sl,
                    price=tp,
                )
                self._breaker.record_success()
                return True
            except Exception as e:
                _log.error("UniversalBrokerGateway FIX modify_order exception: %s", e)
                self._breaker.record_failure(e)
                return False
        _log.warning(
            "UniversalBrokerGateway: modify_order not fully implemented for protocol %s",
            self.protocol,
        )
        return False

    def get_open_orders(self) -> Any:
        """Returns currently active open orders on the live broker gateway."""
        if not self.is_connected():
            return []
        if self.protocol == "MT5":
            try:
                import MetaTrader5 as mt5

                positions = mt5.positions_get()
                if positions is None or len(positions) == 0:
                    return []
                orders_list = []
                for pos in positions:
                    if getattr(pos, "magic", 0) == 998822:
                        direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                        orders_list.append(
                            {
                                "ticket": str(pos.ticket),
                                "symbol": pos.symbol,
                                "direction": direction,
                                "open_price": pos.price_open,
                                "sl": pos.sl,
                                "tp": pos.tp,
                                "lot_size": pos.volume,
                                "profit": float(getattr(pos, "profit", 0.0)),
                            },
                        )
                return orders_list
            except Exception as e:
                _log.error(
                    "UniversalBrokerGateway MT5 get_open_orders exception: %s",
                    e,
                )
                return []

        if self.protocol in ["REST_WS", "CCXT", "CTRADER", "IBKR"] and hasattr(self, "rest_url") and self.rest_url:
            # Generate authenticated headers for GET request
            endpoint = "/v1/orders"
            headers = self._generate_auth_headers(
                method="GET",
                endpoint=endpoint,
                body_data=None,
            )

            req = urllib.request.Request(
                f"{self.rest_url}{endpoint}",
                headers=headers,
            )

            try:
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    response_data = self._read_response_safely(resp)
                    res_data = json.loads(response_data.decode("utf-8"))
                    return res_data.get("orders", [])
            except Exception as e:
                _log.warning(
                    "Universal Broker REST Gateway get_open_orders exception: %s",
                    e,
                )
                return []

        if self.protocol == "FIX" and self.fix_engine:
            # FIX protocol would require maintaining state or querying via Order Mass Status Request
            _log.warning(
                "UniversalBrokerGateway: get_open_orders for FIX requires state tracking",
            )
            return []
        return []
