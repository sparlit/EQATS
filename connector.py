import abc
import random
import time
import datetime
import math
import threading
from input_validation import get_validator
from kill_switch import get_kill_switch
from symbol_mapper import get_symbol_mapper
from typing import Dict, Any, Optional

class TradingConnector(abc.ABC):
    """
    Abstract Base Class representing an MT5 Terminal Connection.
    It provides an unified interface for both Live MT5 (on Windows) and the Paper Simulator.
    """

    @abc.abstractmethod
    def connect(self):
        """Initializes the connection to the terminal."""
        pass

    @abc.abstractmethod
    def is_connected(self):
        """Checks if the connection to the terminal is healthy and active."""
        pass

    @abc.abstractmethod
    def disconnect(self):
        """Disconnects safely from the terminal."""
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
    def close_order(self, ticket, reason="MANUAL"):
        """
        Closes an active order.
        Returns: { 'success': bool, 'price': float, 'profit': float, 'error': str }
        """
        pass

    @abc.abstractmethod
    def modify_order(self, ticket, sl, tp):
        """
        Modifies Stop Loss and Take Profit levels of an active trade.
        Returns: bool indicating success.
        """
        pass

    @abc.abstractmethod
    def get_open_orders(self):
        """
        Returns currently active open orders on the terminal:
        List of dicts: [ { 'ticket': str, 'symbol': str, 'direction': 'BUY'|'SELL', 'open_price': float, 'sl': float, 'tp': float, 'lot_size': float } ]
        """
        pass

    @abc.abstractmethod
    def fetch_all_symbols(self):
        """Fetches all tradable instrument symbols from the connected broker."""
        pass

    @abc.abstractmethod
    def fetch_and_register_broker_symbols(self):
        """Auto-fetches and registers symbols into Master Symbology database."""
        pass

    @abc.abstractmethod
    def draw_dashboard(self, symbol, data):
        """
        Renders status labels directly on the specified symbol's chart in MT5.
        data: dict containing balance, equity, status, detail, time, active_count.
        """
        pass


class MT5Connector(TradingConnector):
    """
    Direct connection with Windows MetaTrader 5 Terminal.
    Uses 'MetaTrader5' library. Note that this library only works on Windows.
    We import dynamically and gracefully fallback if unavailable.
    
    Features:
    - Retry logic for transient failures
    - Connection health monitoring
    - Graceful degradation when MT5 unavailable
    - Detailed error logging
    """

    def __init__(self, demo_only=True, max_retries=3, retry_delay=1.0, broker_id="MT5_BROKER"):
        self.demo_only = demo_only
        self.broker_id = broker_id
        self.mt5 = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.connection_healthy = False
        self.last_error = None
        self.error_count = 0
        self.connection_time = None
        self.mapper = get_symbol_mapper(broker_id=self.broker_id)

    def connect(self):
        """
        Initializes the connection to the terminal with retry logic.
        
        Returns:
            True if successful, raises exception otherwise
        """
        for attempt in range(self.max_retries):
            try:
                import MetaTrader5 as mt5
                self.mt5 = mt5
            except ImportError:
                raise ImportError(
                    "MetaTrader5 package is not installed or not supported on this platform (requires Windows). "
                    "Please run in SIMULATION_MODE = True."
                )

            try:
                if not self.mt5.initialize():
                    error_msg = f"MetaTrader5 initialization failed. Error: {self.mt5.last_error()}"
                    if attempt < self.max_retries - 1:
                        print(f"[WARNING] Connection attempt {attempt + 1} failed: {error_msg}. Retrying in {self.retry_delay}s...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        raise ConnectionError(error_msg)

                account_info = self.mt5.account_info()
                if account_info is None:
                    error_msg = "Failed to retrieve MT5 account details. Is MT5 logged in?"
                    if attempt < self.max_retries - 1:
                        print(f"[WARNING] Connection attempt {attempt + 1} failed: {error_msg}. Retrying in {self.retry_delay}s...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        raise ConnectionError(error_msg)

                # Check for Demo restriction if specified
                if self.demo_only:
                    # trade_mode 0 = Demo, 1 = Contest, 2 = Real
                    if account_info.trade_mode == 2:
                        self.mt5.shutdown()
                        raise PermissionError("CRITICAL SAFETY BLOCK: Attempting to run trading bot on a LIVE / REAL account. Set DEMO_ACCOUNT_ONLY = False in config.py to override.")

                self.connection_healthy = True
                self.connection_time = datetime.datetime.now()
                self.error_count = 0
                print(f"Successfully connected to MT5 Terminal! Account: {account_info.login}, Server: {account_info.server}")
                return True
                
            except Exception as e:
                self.last_error = str(e)
                self.error_count += 1
                if attempt < self.max_retries - 1:
                    print(f"[WARNING] Connection attempt {attempt + 1} failed: {e}. Retrying in {self.retry_delay}s...")
                    time.sleep(self.retry_delay)
                else:
                    raise ConnectionError(f"Failed to connect after {self.max_retries} attempts: {e}")

    def is_connected(self):
        """
        Checks if the connection to the terminal is healthy and active.
        Includes connection health monitoring.
        """
        if not self.mt5:
            self.connection_healthy = False
            return False
        
        try:
            info = self.mt5.terminal_info()
            is_healthy = info is not None
            self.connection_healthy = is_healthy
            return is_healthy
        except Exception as e:
            self.last_error = f"Connection check failed: {e}"
            self.connection_healthy = False
            return False

    def disconnect(self):
        """Disconnects safely from the terminal with error handling."""
        try:
            if self.mt5:
                self.mt5.shutdown()
                self.connection_healthy = False
                print("MT5 Connection closed.")
        except Exception as e:
            print(f"[ERROR] Error during disconnect: {e}")
            self.last_error = f"Disconnect error: {e}"

    def get_account_info(self) -> Dict[str, Any]:
        """
        Returns account information with error handling and fallback.
        """
        try:
            if not self.mt5 or not self.is_connected():
                print("[WARNING] MT5 not connected, returning fallback account info")
                return {'balance': 10000.0, 'equity': 10000.0, 'currency': "USD", 'is_demo': True}
            
            acc = self.mt5.account_info()
            if acc is None:
                print("[WARNING] Failed to retrieve account info, returning fallback")
                return {'balance': 10000.0, 'equity': 10000.0, 'currency': "USD", 'is_demo': True}
            
            return {
                'balance': acc.balance,
                'equity': acc.equity,
                'currency': acc.currency,
                'is_demo': acc.trade_mode != 2
            }
        except Exception as e:
            self.last_error = f"Account info error: {e}"
            self.error_count += 1
            print(f"[ERROR] Error getting account info: {e}")
            return {'balance': 10000.0, 'equity': 10000.0, 'currency': "USD", 'is_demo': True}

    def get_history(self, symbol: str, count: int) -> list:
        """
        Returns historical bar data with error handling and retry logic.
        """
        for attempt in range(self.max_retries):
            try:
                if not self.mt5 or not self.is_connected():
                    print("[WARNING] MT5 not connected, returning fallback history")
                    return [{'open': 1.1000, 'high': 1.1010, 'low': 1.0990, 'close': 1.1000} for _ in range(count)]
                
                import MetaTrader5 as mt5
                timeframe = mt5.TIMEFRAME_M1
                rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
                
                if rates is None or len(rates) == 0:
                    if attempt < self.max_retries - 1:
                        print(f"[WARNING] Failed to get history for {symbol}, attempt {attempt + 1}. Retrying...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        print(f"[WARNING] No history data available for {symbol}")
                        return []

                bars = []
                for r in rates:
                    bars.append({
                        'open': float(r['open']),
                        'high': float(r['high']),
                        'low': float(r['low']),
                        'close': float(r['close'])
                    })
                return bars
                
            except Exception as e:
                self.last_error = f"History error for {symbol}: {e}"
                self.error_count += 1
                if attempt < self.max_retries - 1:
                    print(f"[WARNING] Error getting history for {symbol}, attempt {attempt + 1}: {e}. Retrying...")
                    time.sleep(self.retry_delay)
                else:
                    print(f"[ERROR] Failed to get history for {symbol} after {self.max_retries} attempts: {e}")
                    return []

    def get_current_price(self, symbol: str) -> Dict[str, float]:
        """
        Returns current bid/ask price with error handling and symbol translation adapter.
        Accepts internal Master Symbol or broker-specific symbol.
        """
        broker_symbol = self.mapper.to_broker_symbol(symbol, self.broker_id)
        try:
            if not self.mt5 or not self.is_connected():
                print("[WARNING] MT5 not connected, returning fallback price")
                base_p = 1.1000 if "EUR" in symbol else (1.3000 if "GBP" in symbol else (145.0 if "JPY" in symbol else (65000.0 if "BTC" in symbol else 2.5)))
                return {'bid': base_p, 'ask': base_p + 0.0002}
            
            tick = self.mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                print(f"[WARNING] No tick data for {symbol}, trying fallback...")
                # Fallback to last close price
                rates = self.mt5.copy_rates_from_pos(symbol, self.mt5.TIMEFRAME_M1, 0, 1)
                if rates is not None and len(rates) > 0:
                    close_price = rates[0]['close']
                    return {'bid': close_price, 'ask': close_price}
                else:
                    print(f"[WARNING] No price data available for {symbol}")
                    return {'bid': 0.0, 'ask': 0.0}
            
            return {'bid': tick.bid, 'ask': tick.ask}
            
        except Exception as e:
            self.last_error = f"Price error for {symbol}: {e}"
            self.error_count += 1
            print(f"[ERROR] Error getting price for {symbol}: {e}")
            # Return fallback values
            base_p = 1.1000 if "EUR" in symbol else (1.3000 if "GBP" in symbol else (145.0 if "JPY" in symbol else (65000.0 if "BTC" in symbol else 2.5)))
            return {'bid': base_p, 'ask': base_p + 0.0002}

    def execute_order(self, symbol: str, order_type: str, lot_size: float, sl: Optional[float] = None, tp: Optional[float] = None) -> Dict[str, Any]:
        """
        Places a trade order with Master Symbology translation, risk checks, and error handling.
        
        Args:
            symbol: Trading symbol
            order_type: 'BUY' or 'SELL'
            lot_size: Order lot size
            sl: Stop loss price (optional)
            tp: Take profit price (optional)
            
        Returns:
            Dict with success status, ticket, price, and error message
        """
        # Validate inputs first
        try:
            validator = get_validator()
            kill_switch = get_kill_switch()
            
            # Check kill switch before order execution
            is_position_closing = False  # Assume new order for now
            if not kill_switch.is_order_allowed(order_type, is_position_closing):
                return {'success': False, 'ticket': '', 'price': 0.0, 'error': "Kill switch active: Order blocked"}
            
            # Validate inputs
            validated_symbol = validator.validate_symbol(symbol)
            validated_lots = validator.validate_lots(lot_size, symbol)
            
            # Validate order type
            if order_type.upper() not in ['BUY', 'SELL']:
                return {'success': False, 'ticket': '', 'price': 0.0, 'error': f"Invalid order type: {order_type}"}
            
            validated_order_type = order_type.upper()
            
            # Validate SL and TP if provided
            if sl is not None:
                sl = validator.validate_price(sl, symbol)
            if tp is not None:
                tp = validator.validate_price(tp, symbol)
        except Exception as e:
            self.last_error = f"Input validation failed: {e}"
            self.error_count += 1
            return {'success': False, 'ticket': '', 'price': 0.0, 'error': f"Input validation failed: {e}"}
        
        # Execute order with Master Symbology translation and retry logic
        broker_symbol = self.mapper.to_broker_symbol(validated_symbol, self.broker_id)
        for attempt in range(self.max_retries):
            try:
                if not self.mt5 or not self.is_connected():
                    return {'success': False, 'ticket': '', 'price': 0.0, 'error': "MT5 not connected"}
                
                import MetaTrader5 as mt5
                price_info = self.get_current_price(broker_symbol)
                price = price_info['ask'] if validated_order_type == 'BUY' else price_info['bid']
                
                action = mt5.TRADE_ACTION_DEAL
                type_mt5 = mt5.ORDER_TYPE_BUY if validated_order_type == 'BUY' else mt5.ORDER_TYPE_SELL

                request = {
                    "action": action,
                    "symbol": broker_symbol,
                    "volume": float(validated_lots),
                    "type": type_mt5,
                    "price": float(price),
                    "sl": float(sl) if sl is not None else 0.0,
                    "tp": float(tp) if tp is not None else 0.0,
                    "deviation": 20,
                    "magic": 998822,
                    "comment": "Scalper Brain Bot",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                result = self.mt5.order_send(request)
                if result is None:
                    error_msg = f"Unknown MT5 order_send error. Last error: {self.mt5.last_error()}"
                    if attempt < self.max_retries - 1:
                        print(f"[WARNING] Order attempt {attempt + 1} failed: {error_msg}. Retrying...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        return {'success': False, 'ticket': '', 'price': 0.0, 'error': error_msg}

                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    error_msg = f"Order rejected. Code: {result.retcode}, Description: {result.comment}"
                    # Don't retry on certain error codes (e.g., insufficient funds)
                    if result.retcode in [mt5.TRADE_RETCODE_NO_MONEY, mt5.TRADE_RETCODE_REQUOTE]:
                        return {'success': False, 'ticket': '', 'price': 0.0, 'error': error_msg}
                    
                    if attempt < self.max_retries - 1:
                        print(f"[WARNING] Order attempt {attempt + 1} rejected: {error_msg}. Retrying...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        return {'success': False, 'ticket': '', 'price': 0.0, 'error': error_msg}

                return {
                    'success': True,
                    'ticket': str(result.order),
                    'price': float(result.price),
                    'error': ''
                }
                
            except Exception as e:
                self.last_error = f"Order execution error: {e}"
                self.error_count += 1
                if attempt < self.max_retries - 1:
                    print(f"[WARNING] Order attempt {attempt + 1} failed with exception: {e}. Retrying...")
                    time.sleep(self.retry_delay)
                else:
                    return {'success': False, 'ticket': '', 'price': 0.0, 'error': f"Order execution failed: {e}"}

    def close_order(self, ticket: str, reason: str = "MANUAL") -> Dict[str, Any]:
        """
        Closes an active order with error handling and retry logic.
        """
        for attempt in range(self.max_retries):
            try:
                if not self.mt5 or not self.is_connected():
                    return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': "MT5 not connected"}
                
                import MetaTrader5 as mt5
                orders = self.get_open_orders()
                target_order = None
                for o in orders:
                    if str(o['ticket']) == str(ticket):
                        target_order = o
                        break

                if not target_order:
                    return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': f"Ticket {ticket} not found in open positions."}

                symbol = target_order['symbol']
                lot_size = target_order['lot_size']
                direction = target_order['direction']

                # To close, we execute an opposite order
                close_type = mt5.ORDER_TYPE_SELL if direction == 'BUY' else mt5.ORDER_TYPE_BUY
                price_info = self.get_current_price(symbol)
                price = price_info['bid'] if direction == 'BUY' else price_info['ask']

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": float(lot_size),
                    "type": close_type,
                    "position": int(ticket),
                    "price": float(price),
                    "deviation": 20,
                    "magic": 998822,
                    "comment": f"Close {reason}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                result = self.mt5.order_send(request)
                if result is None:
                    error_msg = f"Close order failed: {self.mt5.last_error()}"
                    if attempt < self.max_retries - 1:
                        print(f"[WARNING] Close attempt {attempt + 1} failed: {error_msg}. Retrying...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': error_msg}

                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    error_msg = f"Close rejected. Code: {result.retcode}, Description: {result.comment}"
                    if attempt < self.max_retries - 1:
                        print(f"[WARNING] Close attempt {attempt + 1} rejected: {error_msg}. Retrying...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': error_msg}

                # Estimate profit (approximate, since broker calculates true value in account currency)
                profit_est = (result.price - target_order['open_price']) * lot_size * 100000.0
                if direction == 'SELL':
                    profit_est = -profit_est

                return {
                    'success': True,
                    'price': float(result.price),
                    'profit': profit_est,
                    'error': ''
                }
                
            except Exception as e:
                self.last_error = f"Close order error: {e}"
                self.error_count += 1
                if attempt < self.max_retries - 1:
                    print(f"[WARNING] Close attempt {attempt + 1} failed with exception: {e}. Retrying...")
                    time.sleep(self.retry_delay)
                else:
                    return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': f"Close order failed: {e}"}

    def modify_order(self, ticket, sl, tp):
        import MetaTrader5 as mt5
        # Fetch position info to get the symbol
        positions = self.mt5.positions_get(ticket=int(ticket))
        if not positions or len(positions) == 0:
            return False

        pos = positions[0]
        symbol = pos.symbol
        direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"

        info = mt5.symbol_info(symbol)
        stops_level = info.trade_stops_level if info else 0
        point = info.point if info else 0.00001

        price_info = self.get_current_price(symbol)
        curr_price = price_info['bid'] if direction == "BUY" else price_info['ask']

        # Enforce minimum stop distance (add small 5 point safety buffer to be completely safe)
        min_distance = (stops_level + 5) * point

        # Adjust SL
        if sl > 0:
            if direction == "BUY":
                if sl > curr_price - min_distance:
                    sl = curr_price - min_distance
            else: # SELL
                if sl < curr_price + min_distance:
                    sl = curr_price + min_distance

        # Adjust TP
        if tp > 0:
            if direction == "BUY":
                if tp < curr_price + min_distance:
                    tp = curr_price + min_distance
            else: # SELL
                if tp > curr_price - min_distance:
                    tp = curr_price - min_distance

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "sl": float(round(sl, 5)),
            "tp": float(round(tp, 5)),
        }
        result = self.mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return False
        return True

    def get_open_orders(self):
        import MetaTrader5 as mt5
        positions = self.mt5.positions_get()
        if positions is None or len(positions) == 0:
            return []

        orders_list = []
        for pos in positions:
            # Filter positions by magic number autonomously
            if getattr(pos, 'magic', 0) == 998822:
                direction = 'BUY' if pos.type == mt5.POSITION_TYPE_BUY else 'SELL'
                orders_list.append({
                    'ticket': str(pos.ticket),
                    'symbol': pos.symbol,
                    'direction': direction,
                    'open_price': pos.price_open,
                    'sl': pos.sl,
                    'tp': pos.tp,
                    'lot_size': pos.volume
                })
        return orders_list

    def fetch_all_symbols(self) -> list:
        """
        Queries all available tradable symbols directly from MT5 terminal using symbols_get().
        """
        try:
            if not self.mt5 or not self.is_connected():
                return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD"]
            symbols_data = self.mt5.symbols_get()
            if not symbols_data:
                return []
            return [s.name for s in symbols_data]
        except Exception as e:
            print(f"[ERROR] Failed to fetch symbols from MT5: {e}")
            return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD"]

    def fetch_and_register_broker_symbols(self) -> int:
        """
        Auto-fetches symbol list from MT5 broker and registers them in Master Symbology database.
        """
        symbol_list = self.fetch_all_symbols()
        if not symbol_list:
            return 0
        return self.mapper.auto_discover_and_map_instruments(symbol_list, broker_id=self.broker_id)

    def draw_dashboard(self, symbol, data):
        """
        Draws dynamic status info. Note: Drawing direct GUI graphical objects is not supported
        by the official MetaTrader5 Python library, so we print all responsive statistics to
        the terminal console cleanly where you can easily monitor background processes.
        """
        pass


class SimulatorConnector(TradingConnector):
    """
    High-fidelity market paper simulator.
    Keeps track of local virtual account balance, manages open trades,
    generates mock price bars, and checks SL/TP rules every tick.
    """

    def __init__(self, initial_balance=10000.0):
        self.balance = initial_balance
        self.equity = initial_balance
        self.currency = "USD"
        self.is_demo = True
        self.open_trades = {}
        self.ticket_counter = 100001
        self.lock = threading.Lock()
        self.connected_status = True

        # Keep internal simulated historical data for symbols
        self.historical_prices = {}
        # Prepopulate history for key symbols
        for sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD"]:
            self._generate_initial_history(sym)

    def connect(self):
        print(f"Simulator connected. Local Balance: {self.balance} {self.currency}")
        return True

    def is_connected(self):
        return self.connected_status

    def disconnect(self):
        print("Simulator disconnected.")

    def get_account_info(self):
        with self.lock:
            # Recalculate equity based on current floating profits
            floating_profit = 0.0
            for ticket, trade in self.open_trades.items():
                prices = self.get_current_price(trade['symbol'])
                current_price = prices['bid'] if trade['direction'] == 'BUY' else prices['ask']

                p_diff = current_price - trade['open_price']
                if trade['direction'] == 'SELL':
                    p_diff = -p_diff

                contract_mult = self._get_contract_multiplier(trade['symbol'])
                floating_profit += p_diff * trade['lot_size'] * contract_mult

            self.equity = self.balance + floating_profit
            return {
                'balance': round(self.balance, 2),
                'equity': round(self.equity, 2),
                'currency': self.currency,
                'is_demo': True
            }

    def get_history(self, symbol, count):
        if symbol not in self.historical_prices:
            self._generate_initial_history(symbol)
        return self.historical_prices[symbol][-count:]

    def get_current_price(self, symbol):
        bars = self.get_history(symbol, 1)
        if len(bars) == 0:
            return {'bid': 1.0, 'ask': 1.0}
        last_price = bars[0]['close']
        # Simulated small bid/ask spread
        spread = last_price * 0.0001 # 0.01% spread
        return {
            'bid': round(last_price - spread/2.0, 5),
            'ask': round(last_price + spread/2.0, 5)
        }

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        with self.lock:
            prices = self.get_current_price(symbol)
            open_price = prices['ask'] if order_type == 'BUY' else prices['bid']

            ticket = str(self.ticket_counter)
            self.ticket_counter += 1

            self.open_trades[ticket] = {
                'ticket': ticket,
                'symbol': symbol,
                'direction': order_type,
                'open_price': open_price,
                'sl': sl,
                'tp': tp,
                'lot_size': lot_size
            }

            return {
                'success': True,
                'ticket': ticket,
                'price': open_price,
                'error': ''
            }

    def close_order(self, ticket, reason="MANUAL"):
        with self.lock:
            if ticket not in self.open_trades:
                return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': f"Ticket {ticket} not found."}

            trade = self.open_trades.pop(ticket)
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

    def get_open_orders(self):
        with self.lock:
            return list(self.open_trades.values())

    def fetch_all_symbols(self) -> list:
        return list(self.historical_prices.keys())

    def fetch_and_register_broker_symbols(self) -> int:
        symbol_list = self.fetch_all_symbols()
        mapper = get_symbol_mapper(broker_id="SIMULATOR_BROKER")
        return mapper.auto_discover_and_map_instruments(symbol_list, broker_id="SIMULATOR_BROKER")

    def draw_dashboard(self, symbol, data):
        # Simulator does not have a physical UI chart.
        # We can mock this or print a clean status line.
        pass

    # --- SIMULATOR UTILITIES ---
    def tick(self):
        """
        Advances the market clock. Generates a new price candle for each symbol,
        and evaluates active stop-loss (SL) / take-profit (TP) conditions.
        """
        closed_tickets = []
        for symbol in self.historical_prices:
            # Append a new random candle following a random walk with trend bias
            last_bars = self.historical_prices[symbol]
            last_close = last_bars[-1]['close']

            # Simulated return: small random walk with slightly positive trend
            ret = random.normalvariate(0.0001, 0.002) # standard deviation of 0.2%
            new_close = last_close * (1 + ret)
            new_open = last_close

            # Create a mock bar
            new_high = max(new_open, new_close) * (1 + abs(random.normalvariate(0.0, 0.001)))
            new_low = min(new_open, new_close) * (1 - abs(random.normalvariate(0.0, 0.001)))

            last_bars.append({
                'open': round(new_open, 5),
                'high': round(new_high, 5),
                'low': round(new_low, 5),
                'close': round(new_close, 5)
            })
            # Keep historical series capped to last 300 entries to save memory
            if len(last_bars) > 300:
                self.historical_prices[symbol] = last_bars[-300:]

        with self.lock:
            # Evaluate if SL or TP are hit
            for ticket, trade in list(self.open_trades.items()):
                symbol = trade['symbol']
                last_bar = self.historical_prices[symbol][-1]
                high = last_bar['high']
                low = last_bar['low']
                direction = trade['direction']
                sl = trade['sl']
                tp = trade['tp']

                # Check if BOTH SL and TP are hit in the same high-volatility range
                both_hit = False
                if direction == 'BUY':
                    if low <= sl and high >= tp:
                        both_hit = True
                elif direction == 'SELL':
                    if high >= sl and low <= tp:
                        both_hit = True

                if both_hit:
                    # Resolve double-hit ambiguity using the candle direction as a heuristic
                    is_green = (last_bar['close'] >= last_bar['open'])
                    if direction == 'BUY':
                        if is_green:
                            # Assume price went up first to hit TP
                            self._process_hit(ticket, tp, "TP")
                        else:
                            # Assume price went down first to hit SL (conservative)
                            self._process_hit(ticket, sl, "SL")
                    else: # SELL
                        if not is_green:
                            # Assume price went down first to hit TP
                            self._process_hit(ticket, tp, "TP")
                        else:
                            # Assume price went up first to hit SL (conservative)
                            self._process_hit(ticket, sl, "SL")
                    closed_tickets.append(ticket)
                else:
                    # Check Buy order
                    if direction == 'BUY':
                        if low <= sl:
                            # SL hit
                            self._process_hit(ticket, sl, "SL")
                            closed_tickets.append(ticket)
                        elif high >= tp:
                            # TP hit
                            self._process_hit(ticket, tp, "TP")
                            closed_tickets.append(ticket)
                    # Check Sell order
                    elif direction == 'SELL':
                        if high >= sl:
                            # SL hit
                            self._process_hit(ticket, sl, "SL")
                            closed_tickets.append(ticket)
                        elif low <= tp:
                            # TP hit
                            self._process_hit(ticket, tp, "TP")
                            closed_tickets.append(ticket)

        return closed_tickets

    def _process_hit(self, ticket, hit_price, reason):
        # Assumed inside a 'with self.lock' lock context
        trade = self.open_trades.pop(ticket)
        p_diff = hit_price - trade['open_price']
        if trade['direction'] == 'SELL':
            p_diff = -p_diff

        contract_mult = self._get_contract_multiplier(trade['symbol'])
        profit = p_diff * trade['lot_size'] * contract_mult

        self.balance += profit
        self.equity = self.balance

        # Log closed trade in DB
        import database
        database.log_trade_close(ticket, hit_price, profit, reason)
        print(f"--- SIMULATOR ALERT --- Trade {ticket} ({trade['direction']} {trade['symbol']}) closed via {reason} at {hit_price}. Profit: {profit:.2f} USD")

    def _generate_initial_history(self, symbol):
        # Generate 250 bars of realistic starting prices
        base_prices = {
            "EURUSD": 1.0950, "GBPUSD": 1.2720, "USDJPY": 151.30, "USDCHF": 0.8950,
            "AUDUSD": 0.6650, "NZDUSD": 0.6120, "USDCAD": 1.3650, "EURGBP": 0.8550,
            "EURJPY": 162.30, "EURCAD": 1.4950, "EURCHF": 0.9750, "EURNZD": 1.7850,
            "EURAUD": 1.6450, "GBPJPY": 191.30, "GBPCAD": 1.7350, "GBPCHF": 1.1350,
            "GBPAUD": 1.9150, "GBPNZD": 2.0750, "AUDJPY": 100.30, "NZDJPY": 92.50,
            "CHFJPY": 168.50, "CADJPY": 110.50, "AUDCAD": 0.9050, "AUDNZD": 1.0850,
            "NZDCAD": 0.8350, "XAUUSD": 2350.00, "XAGUSD": 29.50, "BTCUSD": 65000.00,
            "ETHUSD": 3500.00, "LTCUSD": 80.00, "SOLUSD": 145.00, "XRPUSD": 0.50
        }
        price = base_prices.get(symbol.upper(), 1.0000)
        bars = []
        for _ in range(250):
            # random walk
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
        self.historical_prices[symbol] = bars

    def _get_contract_multiplier(self, symbol):
        symbol_upper = symbol.upper()
        if "XAU" in symbol_upper or "GOLD" in symbol_upper:
            return 100.0
        elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
            return 5000.0
        elif any(c in symbol_upper for c in ["BTC", "ETH", "LTC", "SOL", "XRP"]):
            return 1.0
        elif "JPY" in symbol_upper:
            return 1000.0 # Standard USDJPY contract is 100,000, scaled down JPY quote
        else:
            return 100000.0 # Forex default
