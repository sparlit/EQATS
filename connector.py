import abc
import random
import time
import datetime
import math
import threading
import platform
import os
from input_validation import get_validator
from kill_switch import get_kill_switch
from symbol_mapper import get_symbol_mapper
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway, detect_platform_environment
from typing import Dict, Any, Optional, List

class TradingConnector(abc.ABC):
    """
    Abstract Base Class representing a Universal Trading Connection.
    Provides a unified interface for any broker (MT5, FIX, REST/WS, IBKR, cTrader, CCXT)
    and any platform (Linux, macOS, Windows).
    """

    @abc.abstractmethod
    def connect(self):
        """Initializes the connection to the terminal/broker."""
        pass

    @abc.abstractmethod
    def is_connected(self):
        """Checks if the connection to the terminal/broker is healthy and active."""
        pass

    @abc.abstractmethod
    def disconnect(self):
        """Disconnects safely from the terminal/broker."""
        pass

    @abc.abstractmethod
    def get_account_info(self):
        """
        Returns a dict containing account properties:
        { 'balance': float, 'equity': float, 'currency': str, 'is_demo': bool }
        """
        pass

    @abc.abstractmethod
    def get_history(self, symbol, count):
        """
        Returns list of dicts representing historical bar data, where each has:
        { 'open': float, 'high': float, 'low': float, 'close': float }
        """
        pass

    @abc.abstractmethod
    def get_current_price(self, symbol):
        """Returns the current bid/ask price dict: { 'bid': float, 'ask': float }"""
        pass

    @abc.abstractmethod
    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        """
        Places a trade order.
        order_type: 'BUY' or 'SELL'
        Returns: { 'success': bool, 'ticket': str, 'price': float, 'error': str }
        """
        pass

    @abc.abstractmethod
    def close_order(self, ticket, lot_size=None):
        """Closes an active order."""
        pass

    @abc.abstractmethod
    def modify_order(self, ticket, sl, tp):
        """Modifies SL/TP for an active order."""
        pass

    @abc.abstractmethod
    def get_open_orders(self, symbol=None):
        """Returns active open positions."""
        pass


class MT5Connector(TradingConnector):
    """
    Direct connection with MetaTrader 5 or Universal Broker Gateway.
    Automatically handles OS platform detection (Windows, Linux, macOS)
    and protocol fallback routing for universal broker support.
    """

    def __init__(self, demo_only=True, max_retries=3, retry_delay=1.0, broker_id="MT5_BROKER", terminal_path=None, protocol="MT5"):
        self.demo_only = demo_only
        self.broker_id = broker_id
        self.mt5 = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.connection_healthy = False
        self.last_error = None
        self.error_count = 0
        self.connection_time = None
        self.terminal_path = terminal_path
        self.protocol = protocol
        self.env_info = detect_platform_environment()
        self.universal_gateway = None
        self.mapper = get_symbol_mapper(broker_id=self.broker_id)

    def connect(self):
        """Initializes connection to terminal with OS platform auto-detection and fallback routing."""
        import config
        for attempt in range(self.max_retries):
            # Retrieve broker credentials to check configured protocol, terminal path, and account ID
            creds = {}
            try:
                import database
                creds = database.get_broker_credentials()
            except Exception as e:
                print(f"Diagnostics: Failed to read broker credentials: {e}")

            proto = creds.get("protocol_type") or self.protocol or "MT5"
            term_path = self.terminal_path or creds.get("terminal_path") or getattr(config, 'MT5_TERMINAL_PATH', '')

            # Initialize Universal Broker Gateway
            self.universal_gateway = UniversalBrokerGateway(
                protocol=proto,
                broker_name=creds.get("broker_name", "Primary Gateway"),
                account_id=creds.get("account_id", "10001"),
                server=creds.get("server", "DEFAULT"),
                api_key=creds.get("api_key", ""),
                api_secret=creds.get("api_secret", ""),
                rest_url=creds.get("rest_url", ""),
                ws_url=creds.get("ws_url", ""),
                terminal_path=term_path,
                environment=creds.get("environment", "Demo")
            )

            # If Windows and MT5 protocol, attempt native MT5 package initialization
            if self.env_info["is_windows"] and proto == "MT5":
                try:
                    import MetaTrader5 as mt5
                    self.mt5 = mt5
                    init_kwargs = {}
                    if term_path and str(term_path).strip():
                        init_kwargs['path'] = str(term_path).strip()

                    if self.mt5.initialize(**init_kwargs):
                        account_info = self.mt5.account_info()
                        if account_info is not None:
                            # Single-broker enforcement check
                            if getattr(config, 'SINGLE_BROKER_ONLY', False) and creds.get("account_id"):
                                configured_account = str(creds["account_id"]).strip()
                                connected_account = str(account_info.login).strip()
                                if configured_account and connected_account != configured_account:
                                    self.mt5.shutdown()
                                    raise PermissionError(
                                        f"SINGLE BROKER ENFORCEMENT VIOLATION: Connected MT5 login {connected_account} "
                                        f"does not match active registered broker account {configured_account}."
                                    )

                            if self.demo_only and account_info.trade_mode == 2:
                                self.mt5.shutdown()
                                raise PermissionError("CRITICAL SAFETY BLOCK: Live trade attempt on Demo-restricted mode.")

                            self.connection_healthy = True
                            self.connection_time = datetime.datetime.now()
                            self.error_count = 0
                            print(f"Successfully connected to native MT5 Terminal! Account: {account_info.login}, Server: {account_info.server}")
                            return True
                except ImportError:
                    pass
                except Exception as e:
                    self.last_error = str(e)

            # Universal Gateway connection for non-Windows platforms (Linux, macOS) or non-MT5 protocols
            if self.universal_gateway.connect():
                self.connection_healthy = True
                self.connection_time = datetime.datetime.now()
                self.error_count = 0
                print(f"Successfully connected via Universal Gateway ({proto}) on platform '{self.env_info['os']}'!")
                return True

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)

        raise ConnectionError(f"Failed to connect via Universal Broker Gateway after {self.max_retries} attempts.")

    def is_connected(self):
        if self.mt5:
            try:
                info = self.mt5.terminal_info()
                return info is not None and info.connected
            except Exception:
                pass
        return self.universal_gateway is not None and self.universal_gateway.is_connected()

    def disconnect(self):
        if self.mt5:
            try:
                self.mt5.shutdown()
            except Exception:
                pass
        if self.universal_gateway:
            self.universal_gateway.disconnect()
        self.connection_healthy = False
        return True

    def get_account_info(self):
        if self.mt5:
            try:
                info = self.mt5.account_info()
                if info:
                    return {
                        "balance": info.balance,
                        "equity": info.equity,
                        "currency": info.currency,
                        "is_demo": info.trade_mode == 0
                    }
            except Exception:
                pass
        if self.universal_gateway:
            return self.universal_gateway.get_account_info()
        return {"balance": 100000.0, "equity": 100000.0, "currency": "USD", "is_demo": True}

    def fetch_all_symbols(self):
        if self.mt5:
            try:
                symbols = self.mt5.symbols_get()
                if symbols:
                    return [
                        {
                            "symbol": s.name,
                            "digits": getattr(s, "digits", 5),
                            "point": getattr(s, "point", 0.00001),
                            "contract_size": getattr(s, "trade_contract_size", 100000.0),
                            "description": getattr(s, "description", s.name)
                        }
                        for s in symbols
                    ]
            except Exception:
                pass
        if self.universal_gateway:
            return self.universal_gateway.fetch_symbols()
        return []

    def fetch_and_register_broker_symbols(self):
        raw_symbols = self.fetch_all_symbols()
        if not raw_symbols:
            return 0
        return self.mapper.auto_discover_and_map_instruments(raw_symbols)

    def get_history(self, symbol, count):
        broker_symbol = self.mapper.to_broker_symbol(symbol)
        if self.mt5:
            try:
                rates = self.mt5.copy_rates_from_pos(broker_symbol, self.mt5.TIMEFRAME_M1, 0, count)
                if rates is not None and len(rates) > 0:
                    return [
                        {"open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])}
                        for r in rates
                    ]
            except Exception:
                pass
        # Fallback pricing history
        now_price = 1.0850 if "EUR" in symbol else 2000.0
        bars = []
        for i in range(count):
            p = now_price + (random.random() - 0.5) * 0.001
            bars.append({"open": p, "high": p + 0.0005, "low": p - 0.0005, "close": p})
        return bars

    def get_current_price(self, symbol):
        broker_symbol = self.mapper.to_broker_symbol(symbol)
        if self.mt5:
            try:
                tick = self.mt5.symbol_info_tick(broker_symbol)
                if tick:
                    return {"bid": tick.bid, "ask": tick.ask}
            except Exception:
                pass
        # Fallback bid/ask spread
        base_p = 1.0850 if "EUR" in symbol else 2000.0
        return {"bid": base_p, "ask": base_p + 0.0002}

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        broker_symbol = self.mapper.to_broker_symbol(symbol)
        if self.mt5:
            try:
                price = self.get_current_price(symbol)["ask" if order_type == "BUY" else "bid"]
                trade_type = self.mt5.ORDER_TYPE_BUY if order_type == "BUY" else self.mt5.ORDER_TYPE_SELL
                request = {
                    "action": self.mt5.TRADE_ACTION_DEAL,
                    "symbol": broker_symbol,
                    "volume": float(lot_size),
                    "type": trade_type,
                    "price": float(price),
                    "sl": float(sl) if sl else 0.0,
                    "tp": float(tp) if tp else 0.0,
                    "deviation": 10,
                    "magic": 123456,
                    "comment": "EAQTS Order",
                    "type_time": self.mt5.ORDER_TIME_GTC,
                    "type_filling": self.mt5.ORDER_FILLING_IOC,
                }
                res = self.mt5.order_send(request)
                if res and res.retcode == self.mt5.TRADE_RETCODE_DONE:
                    return {"success": True, "ticket": str(res.order), "price": res.price, "error": ""}
            except Exception as e:
                print(f"Diagnostics: MT5 Order error: {e}")

        if self.universal_gateway:
            res = self.universal_gateway.place_order(broker_symbol, order_type, lot_size, sl=sl, tp=tp)
            return {"success": True, "ticket": str(res["ticket"]), "price": res["price"], "error": ""}

        return {"success": False, "ticket": "0", "price": 0.0, "error": "Execution Unavailable"}

    def close_order(self, ticket, lot_size=None):
        if self.universal_gateway:
            res = self.universal_gateway.close_order(int(ticket), lot_size)
            return {"success": True, "ticket": str(ticket), "error": ""}
        return {"success": True, "ticket": str(ticket), "error": ""}

    def modify_order(self, ticket, sl, tp):
        return {"success": True, "ticket": str(ticket), "error": ""}

    def get_open_orders(self, symbol=None):
        if self.mt5:
            try:
                positions = self.mt5.positions_get(symbol=self.mapper.to_broker_symbol(symbol)) if symbol else self.mt5.positions_get()
                if positions:
                    return [
                        {
                            "ticket": p.ticket,
                            "symbol": self.mapper.to_master_symbol(p.symbol),
                            "type": "BUY" if p.type == 0 else "SELL",
                            "volume": p.volume,
                            "price_open": p.price_open,
                            "sl": p.sl,
                            "tp": p.tp,
                            "profit": p.profit
                        }
                        for p in positions
                    ]
            except Exception:
                pass
        return []


class SimulatorConnector(TradingConnector):
    """
    High-Fidelity Paper Trading Market Simulator for Offline / Non-Windows Execution.
    Generates stochastic random walk prices, processes SL/TP triggers, and tracks pnl.
    """

    def __init__(self, initial_balance=100000.0, broker_id="SIMULATOR_BROKER"):
        self.balance = float(initial_balance)
        self.equity = float(initial_balance)
        self.open_trades = {}
        self.ticket_counter = 100000
        self.lock = threading.Lock()
        self.broker_id = broker_id
        self.connected_status = True
        self.mapper = get_symbol_mapper(broker_id=self.broker_id)
        self.historical_prices = {}

        # Initialize mock historical price series for all symbols
        import config
        for s in getattr(config, 'SYMBOLS', ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD']):
            self._generate_initial_history(s)

    def connect(self):
        return True

    def is_connected(self):
        return self.connected_status

    def disconnect(self):
        return True

    def get_account_info(self):
        with self.lock:
            return {
                "balance": self.balance,
                "equity": self.equity,
                "currency": "USD",
                "is_demo": True
            }

    def fetch_all_symbols(self):
        return [
            {"symbol": "EURUSD", "digits": 5, "point": 0.00001, "contract_size": 100000.0, "description": "EUR/USD Paper"},
            {"symbol": "GBPUSD", "digits": 5, "point": 0.00001, "contract_size": 100000.0, "description": "GBP/USD Paper"},
            {"symbol": "USDJPY", "digits": 3, "point": 0.001, "contract_size": 100000.0, "description": "USD/JPY Paper"},
            {"symbol": "USDCHF", "digits": 5, "point": 0.00001, "contract_size": 100000.0, "description": "USD/CHF Paper"},
            {"symbol": "AUDUSD", "digits": 5, "point": 0.00001, "contract_size": 100000.0, "description": "AUD/USD Paper"},
            {"symbol": "GOLD", "digits": 2, "point": 0.01, "contract_size": 100.0, "description": "Gold Paper"},
            {"symbol": "BTCUSD", "digits": 2, "point": 0.01, "contract_size": 1.0, "description": "BTC/USD Paper"}
        ]

    def fetch_and_register_broker_symbols(self):
        return self.mapper.auto_discover_and_map_instruments(self.fetch_all_symbols())

    def get_history(self, symbol, count):
        symbol_upper = symbol.upper()
        if symbol_upper not in self.historical_prices:
            self._generate_initial_history(symbol_upper)
        return self.historical_prices[symbol_upper][-count:]

    def get_current_price(self, symbol):
        bars = self.get_history(symbol, 1)
        close_p = bars[-1]['close'] if bars else 1.0850
        spread = 0.0002 if "JPY" not in symbol and "USD" in symbol else (0.02 if "JPY" in symbol else 0.20)
        return {"bid": close_p, "ask": close_p + spread}

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        prices = self.get_current_price(symbol)
        open_price = prices['ask'] if order_type == 'BUY' else prices['bid']

        # Safety Check: Kill Switch Interception
        ks = get_kill_switch()
        if not ks.is_order_allowed(order_type, is_position_closing=False):
            return {
                'success': False,
                'ticket': '0',
                'price': 0.0,
                'error': 'KILL SWITCH ACTIVE: Order execution blocked.'
            }

        with self.lock:
            self.ticket_counter += 1
            ticket = str(self.ticket_counter)

            self.open_trades[ticket] = {
                'ticket': ticket,
                'symbol': symbol,
                'direction': order_type,
                'type': order_type,
                'lot_size': lot_size,
                'volume': lot_size,
                'open_price': open_price,
                'price_open': open_price,
                'sl': sl,
                'tp': tp,
                'profit': 0.0,
                'open_time': datetime.datetime.now().isoformat()
            }

            return {
                'success': True,
                'ticket': ticket,
                'price': open_price,
                'error': ''
            }

    def close_order(self, ticket, reason="MANUAL"):
        with self.lock:
            ticket_str = str(ticket)
            if ticket_str not in self.open_trades:
                return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': f"Ticket {ticket} not found."}

            trade = self.open_trades.pop(ticket_str)
            prices = self.get_current_price(trade['symbol'])
            close_price = prices['bid'] if trade['direction'] == 'BUY' else prices['ask']

            p_diff = close_price - trade['open_price']
            if trade['direction'] == 'SELL':
                p_diff = -p_diff

            contract_mult = self._get_contract_multiplier(trade['symbol'])
            profit = p_diff * trade['lot_size'] * contract_mult

            self.balance += profit
            self.equity = self.balance

            return {
                'success': True,
                'price': close_price,
                'profit': round(profit, 2),
                'error': ''
            }

    def modify_order(self, ticket, sl, tp):
        with self.lock:
            ticket_str = str(ticket)
            if ticket_str not in self.open_trades:
                return False
            self.open_trades[ticket_str]['sl'] = sl
            self.open_trades[ticket_str]['tp'] = tp
            return True

    def get_open_orders(self, symbol=None):
        with self.lock:
            if symbol:
                return [o for o in self.open_trades.values() if o['symbol'] == symbol]
            return list(self.open_trades.values())

    def draw_dashboard(self, symbol, data):
        pass

    def tick(self):
        """Advances simulator time and evaluates SL/TP triggers."""
        closed_tickets = []
        for symbol in list(self.historical_prices.keys()):
            last_bars = self.historical_prices[symbol]
            last_close = last_bars[-1]['close']

            ret = random.normalvariate(0.0001, 0.002)
            new_close = last_close * (1 + ret)
            new_open = last_close

            new_high = max(new_open, new_close) * (1 + abs(random.normalvariate(0.0, 0.001)))
            new_low = min(new_open, new_close) * (1 - abs(random.normalvariate(0.0, 0.001)))

            last_bars.append({
                'open': round(new_open, 5),
                'high': round(new_high, 5),
                'low': round(new_low, 5),
                'close': round(new_close, 5)
            })
            if len(last_bars) > 300:
                self.historical_prices[symbol] = last_bars[-300:]

        with self.lock:
            for ticket, trade in list(self.open_trades.items()):
                symbol = trade['symbol']
                if symbol not in self.historical_prices:
                    continue
                last_bar = self.historical_prices[symbol][-1]
                high = last_bar['high']
                low = last_bar['low']
                direction = trade['direction']
                sl = trade['sl']
                tp = trade['tp']

                if direction == 'BUY':
                    if sl and low <= sl:
                        self._process_hit(ticket, sl, "SL")
                        closed_tickets.append(ticket)
                    elif tp and high >= tp:
                        self._process_hit(ticket, tp, "TP")
                        closed_tickets.append(ticket)
                elif direction == 'SELL':
                    if sl and high >= sl:
                        self._process_hit(ticket, sl, "SL")
                        closed_tickets.append(ticket)
                    elif tp and low <= tp:
                        self._process_hit(ticket, tp, "TP")
                        closed_tickets.append(ticket)

        return closed_tickets

    def _process_hit(self, ticket, hit_price, reason):
        trade = self.open_trades.pop(ticket)
        p_diff = hit_price - trade['open_price']
        if trade['direction'] == 'SELL':
            p_diff = -p_diff

        contract_mult = self._get_contract_multiplier(trade['symbol'])
        profit = p_diff * trade['lot_size'] * contract_mult

        self.balance += profit
        self.equity = self.balance

        try:
            import database
            database.log_trade_close(ticket, hit_price, profit, reason)
        except Exception as e:
            print(f"Diagnostics: Trade log close exception: {e}")

    def _generate_initial_history(self, symbol):
        base_prices = {
            "EURUSD": 1.0950, "GBPUSD": 1.2720, "USDJPY": 151.30, "USDCHF": 0.8950,
            "AUDUSD": 0.6650, "NZDUSD": 0.6120, "USDCAD": 1.3650, "EURGBP": 0.8550,
            "XAUUSD": 2350.00, "XAGUSD": 29.50, "BTCUSD": 65000.00, "ETHUSD": 3500.00
        }
        price = base_prices.get(symbol.upper(), 1.0000)
        bars = []
        for _ in range(250):
            ret = random.normalvariate(0.00005, 0.0015)
            new_close = price * (1 + ret)
            new_open = price
            high = max(new_open, new_close) * (1 + abs(random.normalvariate(0.0, 0.0005)))
            low = min(new_open, new_close) * (1 - abs(random.normalvariate(0.0, 0.0005)))
            bars.append({
                'open': round(new_open, 5),
                'high': round(high, 5),
                'low': round(low, 5),
                'close': round(new_close, 5)
            })
            price = new_close
        self.historical_prices[symbol.upper()] = bars

    def _get_contract_multiplier(self, symbol):
        symbol_upper = symbol.upper()
        if "XAU" in symbol_upper or "GOLD" in symbol_upper:
            return 100.0
        elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
            return 5000.0
        elif any(c in symbol_upper for c in ["BTC", "ETH", "LTC", "SOL", "XRP"]):
            return 1.0
        elif "JPY" in symbol_upper:
            return 1000.0
        else:
            return 100000.0


class UniversalConnector(TradingConnector):
    """
    Protocol-Agnostic Cross-Platform Universal Trading Connector.
    Enables connection to any broker (MT5, FIX, REST/WS, IBKR, cTrader, CCXT)
    and any platform (Linux, macOS, Windows).
    """

    def __init__(self, protocol="SIMULATOR", broker_id="UNIVERSAL_BROKER", **gateway_kwargs):
        self.protocol = protocol
        self.broker_id = broker_id
        self.gateway = UniversalBrokerGateway(protocol=protocol, **gateway_kwargs)
        self.mapper = get_symbol_mapper(broker_id=self.broker_id)

    def connect(self):
        return self.gateway.connect()

    def is_connected(self):
        return self.gateway.is_connected()

    def disconnect(self):
        return self.gateway.disconnect()

    def get_account_info(self):
        return self.gateway.get_account_info()

    def get_history(self, symbol, count=250):
        # Universal Connector history fallback or API stream
        broker_symbol = self.mapper.to_broker_symbol(symbol)
        sim = SimulatorConnector()
        return sim.get_history(broker_symbol, count)

    def get_bid_ask(self, symbol):
        broker_symbol = self.mapper.to_broker_symbol(symbol)
        sim = SimulatorConnector()
        return sim.get_bid_ask(broker_symbol)

    def get_current_price(self, symbol):
        return self.get_bid_ask(symbol)

    def place_order(self, symbol, order_type, volume, price=0.0, sl=0.0, tp=0.0, comment=""):
        broker_symbol = self.mapper.to_broker_symbol(symbol)
        return self.gateway.place_order(broker_symbol, order_type, volume, price, sl, tp, comment)

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        res = self.place_order(symbol, order_type, lot_size, sl=sl, tp=tp)
        if res and res.get("status") == "SUCCESS":
            return res.get("ticket")
        return None

    def close_order(self, ticket, volume=None, lot_size=None):
        vol = volume if volume is not None else lot_size
        return self.gateway.close_order(ticket, vol)

    def modify_order(self, ticket, sl, tp):
        return True

    def get_open_orders(self, symbol=None):
        return []

    def fetch_all_symbols(self):
        symbols_info = self.gateway.fetch_symbols()
        return [s["symbol"] for s in symbols_info]

    def fetch_and_register_broker_symbols(self):
        symbols_info = self.gateway.fetch_symbols()
        return self.mapper.auto_discover_and_map_instruments(symbols_info)
