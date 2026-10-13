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


from abc import ABCMeta, abstractmethod

import numpy as np
import pandas as pd


class Strategy:
    __metaclass__ = ABCMeta

    @abstractmethod
    def generate_signals(self):
        raise NotImplementedError("Should implement generate_signals()!")


class Portfolio:
    __metaclass__ = ABCMeta

    @abstractmethod
    def generate_positions(self):
        raise NotImplementedError("Should implement generate_positions()!")

    @abstractmethod
    def backtest_portfolio(self):
        raise NotImplementedError("Should implement backtest_portfolio()!")


class RandomForecastingStrategy(Strategy):
    def __init__(self, symbol, bars):
        self.symbol = symbol
        self.bars = bars

    def generate_signals(self):
        signals = pd.DataFrame(index=self.bars.index)
        signals["signal"] = np.sign(np.random.randn(len(signals)))
        return signals


class MarketIntradayPortfolio(Portfolio):
    def __init__(self, symbol, bars, signals, initial_capital=100000.0, trading_sum=100):
        self.symbol = symbol
        self.bars = bars
        self.signals = signals
        self.initial_capital = float(initial_capital)
        self.trading_sum = float(trading_sum)
        self.positions = self.generate_positions()

    def generate_positions(self):
        positions = pd.DataFrame(index=self.signals.index).fillna(0.0)
        positions[self.symbol] = self.trading_sum * self.signals["signal"]
        return positions

    def backtest_portfolio(self):
        portfolio = pd.DataFrame(index=self.positions.index)
        self.positions.diff()

        portfolio["price_diff"] = self.bars["Close"] - self.bars["Open"]
        portfolio["profit"] = self.positions[self.symbol] * portfolio["price_diff"]

        portfolio["total"] = self.initial_capital + portfolio["profit"].cumsum()
        portfolio["returns"] = portfolio["total"].pct_change()
        return portfolio
