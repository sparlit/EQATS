import abc
import random
import time
import datetime
import math

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
    def get_open_orders(self):
        """
        Returns currently active open orders on the terminal:
        List of dicts: [ { 'ticket': str, 'symbol': str, 'direction': 'BUY'|'SELL', 'open_price': float, 'sl': float, 'tp': float, 'lot_size': float } ]
        """
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
    """

    def __init__(self, demo_only=True):
        self.demo_only = demo_only
        self.mt5 = None

    def connect(self):
        try:
            import MetaTrader5 as mt5
            self.mt5 = mt5
        except ImportError:
            raise ImportError(
                "MetaTrader5 package is not installed or not supported on this platform (requires Windows). "
                "Please run in SIMULATION_MODE = True."
            )

        if not self.mt5.initialize():
            raise ConnectionError(f"MetaTrader5 initialization failed. Error: {self.mt5.last_error()}")

        account_info = self.mt5.account_info()
        if account_info is None:
            raise ConnectionError("Failed to retrieve MT5 account details. Is MT5 logged in?")

        # Check for Demo restriction if specified
        if self.demo_only:
            # trade_mode 0 = Demo, 1 = Contest, 2 = Real
            if account_info.trade_mode == 2:
                self.mt5.shutdown()
                raise PermissionError("CRITICAL SAFETY BLOCK: Attempting to run trading bot on a LIVE / REAL account. Set DEMO_ACCOUNT_ONLY = False in config.py to override.")

        print(f"Successfully connected to MT5 Terminal! Account: {account_info.login}, Server: {account_info.server}")
        return True

    def disconnect(self):
        if self.mt5:
            self.mt5.shutdown()
            print("MT5 Connection closed.")

    def get_account_info(self):
        acc = self.mt5.account_info()
        if acc is None:
            return {'balance': 0.0, 'equity': 0.0, 'currency': "USD", 'is_demo': True}
        return {
            'balance': acc.balance,
            'equity': acc.equity,
            'currency': acc.currency,
            'is_demo': acc.trade_mode != 2
        }

    def get_history(self, symbol, count):
        # We fetch M1 copy_rates
        import MetaTrader5 as mt5
        timeframe = mt5.TIMEFRAME_M1
        # copy_rates_from_pos gets bars starting from position 0 (the current candle) backwards
        rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
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

    def get_current_price(self, symbol):
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            # Fallback
            rates = self.mt5.copy_rates_from_pos(symbol, self.mt5.TIMEFRAME_M1, 0, 1)
            if rates is not None and len(rates) > 0:
                return {'bid': rates[0]['close'], 'ask': rates[0]['close']}
            return {'bid': 0.0, 'ask': 0.0}
        return {'bid': tick.bid, 'ask': tick.ask}

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        import MetaTrader5 as mt5
        price_info = self.get_current_price(symbol)
        price = price_info['ask'] if order_type == 'BUY' else price_info['bid']
        action = mt5.TRADE_ACTION_DEAL
        type_mt5 = mt5.ORDER_TYPE_BUY if order_type == 'BUY' else mt5.ORDER_TYPE_SELL

        request = {
            "action": action,
            "symbol": symbol,
            "volume": float(lot_size),
            "type": type_mt5,
            "price": float(price),
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": 998822,
            "comment": "Scalper Brain Bot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = self.mt5.order_send(request)
        if result is None:
            return {'success': False, 'ticket': '', 'price': 0.0, 'error': "Unknown MT5 order_send error."}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {'success': False, 'ticket': '', 'price': 0.0, 'error': f"Order rejected. Code: {result.retcode}, Description: {result.comment}"}

        return {
            'success': True,
            'ticket': str(result.order),
            'price': float(result.price),
            'error': ''
        }

    def close_order(self, ticket, reason="MANUAL"):
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
            return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': "Unknown error during position close."}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {'success': False, 'price': 0.0, 'profit': 0.0, 'error': f"Close request failed. Code: {result.retcode}"}

        # Estimate profit (approximate, since broker calculates true value in account currency)
        # For simplicity, we get standard profit from MT5 deal details later, or calculate it directly.
        profit_est = (result.price - target_order['open_price']) * lot_size * 100000.0
        if direction == 'SELL':
            profit_est = -profit_est

        return {
            'success': True,
            'price': float(result.price),
            'profit': profit_est,
            'error': ''
        }

    def get_open_orders(self):
        import MetaTrader5 as mt5
        positions = self.mt5.positions_get(magic=998822)
        if positions is None or len(positions) == 0:
            return []

        orders_list = []
        for pos in positions:
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

    def draw_dashboard(self, symbol, data):
        """
        Draws dynamic responsive visual text labels directly on the MT5 symbol's chart background.
        This provides a stunning real-time GUI on MT5!
        """
        if not self.mt5:
            return

        # MT5 allows custom object drawing using ObjectCreate and ObjectSetDouble/String/Integer.
        # We will render multiple distinct info lines on the chart.
        # Format of items: (Name, Text, Y-offset, Color)
        lines = [
            ("SC_TITLE", f"🤖 SCALPER BRAIN AUTONOMOUS BOT", 20, 0x00FF00), # Green
            ("SC_STATUS", f"Status: {data['status'].upper()}", 40, 0xFFFFFF), # White
            ("SC_DETAIL", f"Details: {data['detail']}", 60, 0x00FFFF), # Cyan
            ("SC_METRICS", f"Balance: {data['balance']:.2f} | Equity: {data['equity']:.2f} | Open: {data['active_count']}", 80, 0xFFFF00), # Yellow
            ("SC_TIME", f"Last Scan: {data['time']}", 100, 0x888888) # Gray
        ]

        # In MT5, 0xRRGGBB format is accepted by OBJPROP_COLOR.
        # We will issue orders to either update or create these text objects.
        # Safe drawing script:
        for name, text, y_offset, color in lines:
            obj_name = f"{symbol}_{name}"
            # Attempt to create label (OBJ_LABEL = 24)
            # Standard MT5 object creation
            created = self.mt5.object_create(symbol, obj_name, 24, 0, 0, 0)

            # Set properties (X=20px, Y=y_offset from top-left, Corner=0 (Top-Left))
            self.mt5.object_set_integer(symbol, obj_name, self.mt5.OBJPROP_CORNER, 0)
            self.mt5.object_set_integer(symbol, obj_name, self.mt5.OBJPROP_XDISTANCE, 20)
            self.mt5.object_set_integer(symbol, obj_name, self.mt5.OBJPROP_YDISTANCE, y_offset)
            self.mt5.object_set_string(symbol, obj_name, self.mt5.OBJPROP_TEXT, text)
            self.mt5.object_set_integer(symbol, obj_name, self.mt5.OBJPROP_COLOR, color)
            self.mt5.object_set_integer(symbol, obj_name, self.mt5.OBJPROP_FONTSIZE, 11)
            self.mt5.object_set_string(symbol, obj_name, self.mt5.OBJPROP_FONT, "Segoe UI")


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

        # Keep internal simulated historical data for symbols
        self.historical_prices = {}
        # Prepopulate history for key symbols
        for sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD"]:
            self._generate_initial_history(sym)

    def connect(self):
        print(f"Simulator connected. Local Balance: {self.balance} {self.currency}")
        return True

    def disconnect(self):
        print("Simulator disconnected.")

    def get_account_info(self):
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

    def get_open_orders(self):
        return list(self.open_trades.values())

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

        # Evaluate if SL or TP are hit
        for ticket, trade in list(self.open_trades.items()):
            symbol = trade['symbol']
            last_bar = self.historical_prices[symbol][-1]
            high = last_bar['high']
            low = last_bar['low']
            direction = trade['direction']
            sl = trade['sl']
            tp = trade['tp']

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
            "EURUSD": 1.0950,
            "GBPUSD": 1.2720,
            "USDJPY": 151.30,
            "XAUUSD": 2150.00,
            "BTCUSD": 65000.00,
            "ETHUSD": 3500.00
        }
        price = base_prices.get(symbol, 100.0)
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
        elif "BTC" in symbol_upper or "ETH" in symbol_upper:
            return 1.0
        elif "JPY" in symbol_upper:
            return 1000.0 # Standard USDJPY contract is 100,000, scaled down JPY quote
        else:
            return 100000.0 # Forex default
