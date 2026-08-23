import abc
import concurrent.futures
import logging
import math
import random
import threading

import config
import database
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway

_log = logging.getLogger("connector")


class TradingConnector(abc.ABC):
    """
    Abstract Base Class representing an MT5 Terminal Connection.
    It provides an unified interface for both Live MT5 (on Windows) and the Paper Simulator.
    """

    @abc.abstractmethod
    def connect(self):
        """Initializes the connection to the terminal."""
        raise NotImplementedError("Subclasses must implement connect()")

    @abc.abstractmethod
    def is_connected(self):
        """Checks if the connection to the terminal is healthy and active."""
        raise NotImplementedError("Subclasses must implement is_connected()")

    @abc.abstractmethod
    def disconnect(self):
        """Disconnects safely from the terminal."""
        raise NotImplementedError("Subclasses must implement disconnect()")

    @abc.abstractmethod
    def get_account_info(self):
        """
        Returns a dict containing account properties:
        { 'balance': float, 'equity': float, 'currency': str, 'is_demo': bool }
        """
        raise NotImplementedError("Subclasses must implement get_account_info()")

    @abc.abstractmethod
    def get_history(self, symbol, count):
        """
        Returns list of dicts representing historical bar data, where each has:
        { 'open': float, 'high': float, 'low': float, 'close': float }
        """
        raise NotImplementedError("Subclasses must implement get_history()")

    @abc.abstractmethod
    def get_current_price(self, symbol):
        """Returns the current bid/ask price dict: { 'bid': float, 'ask': float }"""
        raise NotImplementedError("Subclasses must implement get_current_price()")

    @abc.abstractmethod
    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        """
        Places a trade order.
        order_type: 'BUY' or 'SELL'
        Returns: { 'success': bool, 'ticket': str, 'price': float, 'error': str }
        """
        raise NotImplementedError("Subclasses must implement execute_order()")

    @abc.abstractmethod
    def close_order(self, ticket, reason="MANUAL"):
        """
        Closes an active order.
        Returns: { 'success': bool, 'price': float, 'profit': float, 'error': str }
        """
        raise NotImplementedError("Subclasses must implement close_order()")

    @abc.abstractmethod
    def modify_order(self, ticket, sl, tp):
        """
        Modifies Stop Loss and Take Profit levels of an active trade.
        Returns: bool indicating success.
        """
        raise NotImplementedError("Subclasses must implement modify_order()")

    @abc.abstractmethod
    def get_open_orders(self):
        """
        Returns currently active open orders on the terminal:
        List of dicts: [ { 'ticket': str, 'symbol': str, 'direction': 'BUY'|'SELL', 'open_price': float, 'sl': float, 'tp': float, 'lot_size': float } ]
        """
        raise NotImplementedError("Subclasses must implement get_open_orders()")

    @abc.abstractmethod
    def draw_dashboard(self, symbol, data):
        """
        Renders status labels directly on the specified symbol's chart in MT5.
        data: dict containing balance, equity, status, detail, time, active_count.
        """
        raise NotImplementedError("Subclasses must implement draw_dashboard()")


class UniversalConnector(TradingConnector):
    """
    Universal Multi-Broker Connector wrapping UniversalBrokerGateway.
    Delegates commands dynamically to any broker or platform (MT5, FIX, REST/WS, IBKR, cTrader, CCXT, SIMULATOR).
    """

    def __init__(self, protocol="MT5", broker_config=None, initial_balance=10000.0):
        self.protocol = protocol
        self.broker_config = broker_config or database.get_broker_credentials()
        self.gateway = UniversalBrokerGateway(
            protocol=self.protocol, broker_config=self.broker_config
        )
        self.sim_fallback = SimulatorConnector(initial_balance=initial_balance)

    def connect(self):
        try:
            res = self.gateway.connect()
            if res:
                return True
        except Exception as e:
            print(f"UniversalConnector error on gateway connect: {e}")
        print("UniversalConnector: Falling back to Simulator mode.")
        return self.sim_fallback.connect()

    def is_connected(self):
        return self.gateway.is_connected() or self.sim_fallback.is_connected()

    def disconnect(self):
        self.gateway.disconnect()
        self.sim_fallback.disconnect()

    def get_account_info(self):
        if self.gateway.is_connected():
            return self.gateway.get_account_info()
        return self.sim_fallback.get_account_info()

    def get_history(self, symbol, count):
        return self.sim_fallback.get_history(symbol, count)

    def get_current_price(self, symbol):
        return self.sim_fallback.get_current_price(symbol)

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        if self.gateway.is_connected() and self.protocol != "SIMULATOR":
            gw_res = self.gateway.execute_order(symbol, order_type, lot_size, sl, tp)
            if gw_res.get("success"):
                # Sync into internal trade tracker
                self.sim_fallback.execute_order(symbol, order_type, lot_size, sl, tp)
                return gw_res
        return self.sim_fallback.execute_order(symbol, order_type, lot_size, sl, tp)

    def close_order(self, ticket, reason="MANUAL"):
        return self.sim_fallback.close_order(ticket, reason)

    def modify_order(self, ticket, sl, tp):
        return self.sim_fallback.modify_order(ticket, sl, tp)

    def get_open_orders(self):
        return self.sim_fallback.get_open_orders()

    def draw_dashboard(self, symbol, data):
        self.sim_fallback.draw_dashboard(symbol, data)


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

        creds = database.get_broker_credentials()
        path = creds.get("terminal_path") or getattr(config, "MT5_TERMINAL_PATH", None)
        server = creds.get("server")
        login = creds.get("account_id")
        password = creds.get("password")

        init_kwargs = {}
        if path and str(path).strip():
            init_kwargs["path"] = str(path).strip()
        if login and str(login).strip() and str(login).isdigit():
            init_kwargs["login"] = int(str(login).strip())
        if password and str(password).strip():
            init_kwargs["password"] = str(password).strip()
        if server and str(server).strip() and server != "EAQTS-Demo-Server":
            init_kwargs["server"] = str(server).strip()

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._connect_impl, init_kwargs, login, password, server)
            return future.result(timeout=5.0)
        except concurrent.futures.TimeoutError:
            raise ConnectionError(
                "MetaTrader5 connection timed out (5s). Please ensure MetaTrader 5 application is open and running."
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _connect_impl(self, init_kwargs, login, password, server):
        initialized = False
        if init_kwargs:
            try:
                initialized = self.mt5.initialize(**init_kwargs)
            except Exception as e:
                _log.warning("mt5.initialize with credentials failed (%s), attempting default initialize()", e)

        if not initialized:
            initialized = self.mt5.initialize()

        if not initialized:
            last_err = self.mt5.last_error() if hasattr(self.mt5, "last_error") else "Terminal not open or unresponsive"
            raise ConnectionError(
                f"MetaTrader5 initialization failed. Error: {last_err}"
            )

        if login and str(login).isdigit() and password and str(password).strip():
            try:
                login_id = int(str(login).strip())
                self.mt5.login(
                    login=login_id,
                    password=str(password).strip(),
                    server=str(server).strip() if server else "",
                )
            except Exception as e:
                _log.warning("MT5 login attempt failed (will probe anyway): %s", e)

        account_info = self.mt5.account_info()
        if account_info is None:
            raise ConnectionError(
                "Failed to retrieve MT5 account details. Is MT5 logged in?"
            )

        if self.demo_only:
            if account_info.trade_mode == 2:
                self.mt5.shutdown()
                raise PermissionError(
                    "CRITICAL SAFETY BLOCK: Attempting to run trading bot on a LIVE / REAL account. Set DEMO_ACCOUNT_ONLY = False in config.py to override."
                )

        print(
            f"Successfully connected to MT5 Terminal! Account: {account_info.login}, Server: {account_info.server}"
        )
        return True

    def is_connected(self):
        if not self.mt5:
            return False
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self.mt5.terminal_info)
            info = future.result(timeout=2.0)
            return info is not None
        except Exception:
            return False
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def disconnect(self):
        if self.mt5:
            try:
                self.mt5.shutdown()
            except Exception as e:
                _log.warning("MT5 shutdown error: %s", e)
            print("MT5 Connection closed.")

        try:
            import os
            import subprocess
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "terminal64.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                subprocess.run(
                    ["taskkill", "/F", "/IM", "terminal.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                subprocess.run(
                    ["pkill", "-9", "-f", "terminal64.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                subprocess.run(
                    ["pkill", "-9", "-f", "terminal.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        except Exception as e:
            _log.debug("Notice: MT5 process termination attempted: %s", e)

    def get_account_info(self):
        if not self.mt5:
            return {
                "balance": 10000.0,
                "equity": 10000.0,
                "currency": "USD",
                "is_demo": True,
            }
        acc = self.mt5.account_info()
        if acc is None:
            return {
                "balance": 10000.0,
                "equity": 10000.0,
                "currency": "USD",
                "is_demo": True,
            }
        return {
            "balance": acc.balance,
            "equity": acc.equity,
            "currency": acc.currency,
            "is_demo": acc.trade_mode != 2,
        }

    def get_history(self, symbol, count):
        if not self.mt5:
            return [
                {"open": 1.1000, "high": 1.1010, "low": 1.0990, "close": 1.1000}
                for _ in range(count)
            ]
        import MetaTrader5 as mt5

        timeframe = mt5.TIMEFRAME_M1
        rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return []

        bars = []
        for r in rates:
            bars.append(
                {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
            )
        return bars

    def get_current_price(self, symbol):
        if not self.mt5:
            base_p = (
                1.1000
                if "EUR" in symbol
                else (
                    1.3000
                    if "GBP" in symbol
                    else (
                        145.0
                        if "JPY" in symbol
                        else (65000.0 if "BTC" in symbol else 2.5)
                    )
                )
            )
            return {"bid": base_p, "ask": base_p + 0.0002}
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            rates = self.mt5.copy_rates_from_pos(symbol, self.mt5.TIMEFRAME_M1, 0, 1)
            if rates is not None and len(rates) > 0:
                return {"bid": rates[0]["close"], "ask": rates[0]["close"]}
            return {"bid": 0.0, "ask": 0.0}
        return {"bid": tick.bid, "ask": tick.ask}

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        if not self.mt5:
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": "MT5 not connected.",
            }
        import MetaTrader5 as mt5

        price_info = self.get_current_price(symbol)
        price = price_info["ask"] if order_type == "BUY" else price_info["bid"]
        action = mt5.TRADE_ACTION_DEAL
        type_mt5 = mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL

        # Query live broker volume constraints to avoid [Invalid volume] errors
        info = self.mt5.symbol_info(symbol)
        if info is not None:
            vol_min = getattr(info, "volume_min", 0.01) or 0.01
            vol_max = getattr(info, "volume_max", 500.0) or 500.0
            vol_step = getattr(info, "volume_step", 0.01) or 0.01
        else:
            vol_min, vol_max, vol_step = 0.01, 500.0, 0.01

        volume = float(lot_size)
        if vol_step > 0:
            steps = math.floor((volume - vol_min) / vol_step + 1e-9) if volume >= vol_min else 0
            volume = vol_min + (steps * vol_step)

        volume = max(vol_min, min(vol_max, round(volume, 4)))

        request = {
            "action": action,
            "symbol": symbol,
            "volume": float(volume),
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
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": "Unknown MT5 order_send error.",
            }

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": f"Order rejected. Code: {result.retcode}, Description: {result.comment}",
            }

        return {
            "success": True,
            "ticket": str(result.order),
            "price": float(result.price),
            "error": "",
        }

    def close_order(self, ticket, reason="MANUAL"):
        if not self.mt5:
            return {
                "success": False,
                "price": 0.0,
                "profit": 0.0,
                "error": "MT5 not connected.",
            }
        import MetaTrader5 as mt5

        orders = self.get_open_orders()
        target_order = None
        for o in orders:
            if str(o["ticket"]) == str(ticket):
                target_order = o
                break

        if not target_order:
            return {
                "success": False,
                "price": 0.0,
                "profit": 0.0,
                "error": f"Ticket {ticket} not found in open positions.",
            }

        symbol = target_order["symbol"]
        lot_size = target_order["lot_size"]
        direction = target_order["direction"]

        close_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
        price_info = self.get_current_price(symbol)
        price = price_info["bid"] if direction == "BUY" else price_info["ask"]

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
            return {
                "success": False,
                "price": 0.0,
                "profit": 0.0,
                "error": "Unknown error during position close.",
            }

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "price": 0.0,
                "profit": 0.0,
                "error": f"Close request failed. Code: {result.retcode}",
            }

        profit_est = (result.price - target_order["open_price"]) * lot_size * 100000.0
        if direction == "SELL":
            profit_est = -profit_est

        return {
            "success": True,
            "price": float(result.price),
            "profit": profit_est,
            "error": "",
        }

    def modify_order(self, ticket, sl, tp):
        if not self.mt5:
            return False
        import MetaTrader5 as mt5

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
        curr_price = price_info["bid"] if direction == "BUY" else price_info["ask"]

        min_distance = (stops_level + 5) * point

        if sl > 0:
            if direction == "BUY":
                if sl > curr_price - min_distance:
                    sl = curr_price - min_distance
            else:
                if sl < curr_price + min_distance:
                    sl = curr_price + min_distance

        if tp > 0:
            if direction == "BUY":
                if tp < curr_price + min_distance:
                    tp = curr_price + min_distance
            else:
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
        if not self.mt5:
            return []
        import MetaTrader5 as mt5

        positions = self.mt5.positions_get()
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
                    }
                )
        return orders_list

    def draw_dashboard(self, symbol, data):
        if data:
            bal = data.get("balance", 0.0)
            eq = data.get("equity", 0.0)
            status = data.get("status", "OK")
            detail = data.get("detail", "N/A")
            print(
                f"📊 [MT5 DASHBOARD] {symbol} | Status: {status} | Equity: ${eq:,.2f} | Bal: ${bal:,.2f} | Detail: {detail}"
            )


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

        self.historical_prices = {}
        for sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD"]:
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
            floating_profit = 0.0
            for ticket, trade in self.open_trades.items():
                prices = self.get_current_price(trade["symbol"])
                current_price = (
                    prices["bid"] if trade["direction"] == "BUY" else prices["ask"]
                )

                p_diff = current_price - trade["open_price"]
                if trade["direction"] == "SELL":
                    p_diff = -p_diff

                contract_mult = self._get_contract_multiplier(trade["symbol"])
                floating_profit += p_diff * trade["lot_size"] * contract_mult

            self.equity = self.balance + floating_profit
            return {
                "balance": round(self.balance, 2),
                "equity": round(self.equity, 2),
                "currency": self.currency,
                "is_demo": True,
            }

    def get_history(self, symbol, count):
        if symbol not in self.historical_prices:
            self._generate_initial_history(symbol)
        return self.historical_prices[symbol][-count:]

    def get_current_price(self, symbol):
        bars = self.get_history(symbol, 1)
        if len(bars) == 0:
            return {"bid": 1.0, "ask": 1.0}
        last_price = bars[0]["close"]
        spread = last_price * 0.0001
        return {
            "bid": round(last_price - spread / 2.0, 5),
            "ask": round(last_price + spread / 2.0, 5),
        }

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        with self.lock:
            prices = self.get_current_price(symbol)
            open_price = prices["ask"] if order_type == "BUY" else prices["bid"]

            ticket = str(self.ticket_counter)
            self.ticket_counter += 1

            self.open_trades[ticket] = {
                "ticket": ticket,
                "symbol": symbol,
                "direction": order_type,
                "open_price": open_price,
                "sl": sl,
                "tp": tp,
                "lot_size": lot_size,
            }

            return {"success": True, "ticket": ticket, "price": open_price, "error": ""}

    def close_order(self, ticket, reason="MANUAL"):
        with self.lock:
            if ticket not in self.open_trades:
                return {
                    "success": False,
                    "price": 0.0,
                    "profit": 0.0,
                    "error": f"Ticket {ticket} not found.",
                }

            trade = self.open_trades.pop(ticket)
            prices = self.get_current_price(trade["symbol"])
            close_price = (
                prices["bid"] if trade["direction"] == "BUY" else prices["ask"]
            )

            p_diff = close_price - trade["open_price"]
            if trade["direction"] == "SELL":
                p_diff = -p_diff

            contract_mult = self._get_contract_multiplier(trade["symbol"])
            profit = p_diff * trade["lot_size"] * contract_mult

            self.balance += profit
            self.equity = self.balance

            return {
                "success": True,
                "price": close_price,
                "profit": round(profit, 2),
                "error": "",
            }

    def modify_order(self, ticket, sl, tp):
        with self.lock:
            ticket_str = str(ticket)
            if ticket_str not in self.open_trades:
                return False
            self.open_trades[ticket_str]["sl"] = sl
            self.open_trades[ticket_str]["tp"] = tp
            return True

    def get_open_orders(self):
        with self.lock:
            return list(self.open_trades.values())

    def draw_dashboard(self, symbol, data):
        if data:
            eq = data.get("equity", 0.0)
            status = data.get("status", "OK")
            print(
                f"🎮 [SIM DASHBOARD] {symbol} | Status: {status} | Equity: ${eq:,.2f}"
            )

    def tick(self):
        closed_tickets = []
        for symbol in self.historical_prices:
            last_bars = self.historical_prices[symbol]
            if not last_bars:
                continue
            last_close = last_bars[-1]["close"]

            ret = random.normalvariate(0.0001, 0.002)
            new_close = last_close * (1 + ret)
            new_open = last_close

            new_high = max(new_open, new_close) * (
                1 + abs(random.normalvariate(0.0, 0.001))
            )
            new_low = min(new_open, new_close) * (
                1 - abs(random.normalvariate(0.0, 0.001))
            )

            last_bars.append(
                {
                    "open": round(new_open, 5),
                    "high": round(new_high, 5),
                    "low": round(new_low, 5),
                    "close": round(new_close, 5),
                }
            )
            if len(last_bars) > 300:
                self.historical_prices[symbol] = last_bars[-300:]

        with self.lock:
            for ticket, trade in list(self.open_trades.items()):
                symbol = trade["symbol"]
                last_bar = self.historical_prices[symbol][-1]
                high = last_bar["high"]
                low = last_bar["low"]
                direction = trade["direction"]
                sl = trade["sl"]
                tp = trade["tp"]

                both_hit = False
                if direction == "BUY":
                    if low <= sl and high >= tp:
                        both_hit = True
                elif direction == "SELL":
                    if high >= sl and low <= tp:
                        both_hit = True

                if both_hit:
                    is_green = last_bar["close"] >= last_bar["open"]
                    if direction == "BUY":
                        if is_green:
                            self._process_hit(ticket, tp, "TP")
                        else:
                            self._process_hit(ticket, sl, "SL")
                    else:
                        if not is_green:
                            self._process_hit(ticket, tp, "TP")
                        else:
                            self._process_hit(ticket, sl, "SL")
                    closed_tickets.append(ticket)
                else:
                    if direction == "BUY":
                        if low <= sl:
                            self._process_hit(ticket, sl, "SL")
                            closed_tickets.append(ticket)
                        elif high >= tp:
                            self._process_hit(ticket, tp, "TP")
                            closed_tickets.append(ticket)
                    elif direction == "SELL":
                        if high >= sl:
                            self._process_hit(ticket, sl, "SL")
                            closed_tickets.append(ticket)
                        elif low <= tp:
                            self._process_hit(ticket, tp, "TP")
                            closed_tickets.append(ticket)

        return closed_tickets

    def _process_hit(self, ticket, hit_price, reason):
        trade = self.open_trades.pop(ticket)
        p_diff = hit_price - trade["open_price"]
        if trade["direction"] == "SELL":
            p_diff = -p_diff

        contract_mult = self._get_contract_multiplier(trade["symbol"])
        profit = p_diff * trade["lot_size"] * contract_mult

        self.balance += profit
        self.equity = self.balance

        import database

        database.log_trade_close(ticket, hit_price, profit, reason)
        print(
            f"--- SIMULATOR ALERT --- Trade {ticket} ({trade['direction']} {trade['symbol']}) closed via {reason} at {hit_price}. Profit: {profit:.2f} USD"
        )

    def _generate_initial_history(self, symbol):
        base_prices = {
            "EURUSD": 1.0950,
            "GBPUSD": 1.2720,
            "USDJPY": 151.30,
            "USDCHF": 0.8950,
            "AUDUSD": 0.6650,
            "NZDUSD": 0.6120,
            "USDCAD": 1.3650,
            "EURGBP": 0.8550,
            "EURJPY": 162.30,
            "EURCAD": 1.4950,
            "EURCHF": 0.9750,
            "EURNZD": 1.7850,
            "EURAUD": 1.6450,
            "GBPJPY": 191.30,
            "GBPCAD": 1.7350,
            "GBPCHF": 1.1350,
            "GBPAUD": 1.9150,
            "GBPNZD": 2.0750,
            "AUDJPY": 100.30,
            "NZDJPY": 92.50,
            "CHFJPY": 168.50,
            "CADJPY": 110.50,
            "AUDCAD": 0.9050,
            "AUDNZD": 1.0850,
            "NZDCAD": 0.8350,
            "XAUUSD": 2350.00,
            "XAGUSD": 29.50,
            "BTCUSD": 65000.00,
            "ETHUSD": 3500.00,
            "LTCUSD": 80.00,
            "SOLUSD": 145.00,
            "XRPUSD": 0.50,
        }
        price = base_prices.get(symbol.upper(), 1.0000)
        bars = []
        for _ in range(250):
            ret = random.normalvariate(0.00005, 0.0015)
            new_close = price * (1 + ret)
            new_open = price
            high = max(new_open, new_close) * (
                1 + abs(random.normalvariate(0.0, 0.0005))
            )
            low = min(new_open, new_close) * (
                1 - abs(random.normalvariate(0.0, 0.0005))
            )
            bars.append(
                {
                    "open": round(price, 5),
                    "high": round(price, 5),
                    "low": round(price, 5),
                    "close": round(price, 5),
                }
            )
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
            return 1000.0
        else:
            return 100000.0
