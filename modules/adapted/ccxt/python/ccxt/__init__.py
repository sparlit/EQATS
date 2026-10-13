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


# -*- coding: utf-8 -*-

"""CCXT: CryptoCurrency eXchange Trading Library"""

# MIT License
# Copyright (c) 2017 Igor Kroitor
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# ----------------------------------------------------------------------------

__version__ = "4.5.85"

# ----------------------------------------------------------------------------

from ccxt.alpaca import alpaca  # noqa: F401
from ccxt.apex import apex  # noqa: F401
from ccxt.aster import aster  # noqa: F401
from ccxt.backpack import backpack  # noqa: F401
from ccxt.base import errors
from ccxt.base.decimal_to_precision import (
    DECIMAL_PLACES,  # noqa: F401
    NO_PADDING,  # noqa: F401
    PAD_WITH_ZERO,  # noqa: F401
    ROUND,  # noqa: F401
    ROUND_DOWN,  # noqa: F401
    ROUND_UP,  # noqa: F401
    SIGNIFICANT_DIGITS,  # noqa: F401
    TICK_SIZE,  # noqa: F401
    TRUNCATE,  # noqa: F401
    decimal_to_precision,  # noqa: F401
)
from ccxt.base.errors import (
    AccountNotEnabled,  # noqa: F401
    AccountSuspended,  # noqa: F401
    AddressPending,  # noqa: F401
    ArgumentsRequired,  # noqa: F401
    AuthenticationError,  # noqa: F401
    BadRequest,  # noqa: F401
    BadResponse,  # noqa: F401
    BadSymbol,  # noqa: F401
    BaseError,  # noqa: F401
    CancelPending,  # noqa: F401
    ChecksumError,  # noqa: F401
    ContractUnavailable,  # noqa: F401
    DDoSProtection,  # noqa: F401
    DuplicateOrderId,  # noqa: F401
    ExchangeClosedByUser,  # noqa: F401
    ExchangeError,  # noqa: F401
    ExchangeNotAvailable,  # noqa: F401
    InsufficientFunds,  # noqa: F401
    InvalidAddress,  # noqa: F401
    InvalidNonce,  # noqa: F401
    InvalidOrder,  # noqa: F401
    InvalidProxySettings,  # noqa: F401
    ManualInteractionNeeded,  # noqa: F401
    MarginModeAlreadySet,  # noqa: F401
    MarketClosed,  # noqa: F401
    NetworkError,  # noqa: F401
    NoChange,  # noqa: F401
    NotSupported,  # noqa: F401
    NullResponse,  # noqa: F401
    OnMaintenance,  # noqa: F401
    OperationFailed,  # noqa: F401
    OperationRejected,  # noqa: F401
    OrderImmediatelyFillable,  # noqa: F401
    OrderNotCached,  # noqa: F401
    OrderNotFillable,  # noqa: F401
    OrderNotFound,  # noqa: F401
    PermissionDenied,  # noqa: F401
    RateLimitExceeded,  # noqa: F401
    RequestTimeout,  # noqa: F401
    RestrictedLocation,  # noqa: F401
    UnsubscribeError,  # noqa: F401
    error_hierarchy,  # noqa: F401
)
from ccxt.base.exchange import Exchange  # noqa: F401
from ccxt.base.order_router import OrderRouter  # noqa: F401
from ccxt.base.precise import Precise  # noqa: F401
from ccxt.bequant import bequant  # noqa: F401
from ccxt.bigone import bigone  # noqa: F401
from ccxt.binance import binance  # noqa: F401
from ccxt.binancecoinm import binancecoinm  # noqa: F401
from ccxt.binanceus import binanceus  # noqa: F401
from ccxt.binanceusdm import binanceusdm  # noqa: F401
from ccxt.bingx import bingx  # noqa: F401
from ccxt.bit2c import bit2c  # noqa: F401
from ccxt.bitbank import bitbank  # noqa: F401
from ccxt.bitbns import bitbns  # noqa: F401
from ccxt.bitfinex import bitfinex  # noqa: F401
from ccxt.bitflyer import bitflyer  # noqa: F401
from ccxt.bitget import bitget  # noqa: F401
from ccxt.bithumb import bithumb  # noqa: F401
from ccxt.bitopro import bitopro  # noqa: F401
from ccxt.bitrue import bitrue  # noqa: F401
from ccxt.bitso import bitso  # noqa: F401
from ccxt.bitstamp import bitstamp  # noqa: F401
from ccxt.bitteam import bitteam  # noqa: F401
from ccxt.bittrade import bittrade  # noqa: F401
from ccxt.bitvavo import bitvavo  # noqa: F401
from ccxt.blockchaincom import blockchaincom  # noqa: F401
from ccxt.blofin import blofin  # noqa: F401
from ccxt.btcbox import btcbox  # noqa: F401
from ccxt.btcmarkets import btcmarkets  # noqa: F401
from ccxt.btcturk import btcturk  # noqa: F401
from ccxt.btse import btse  # noqa: F401
from ccxt.bullish import bullish  # noqa: F401
from ccxt.bybit import bybit  # noqa: F401
from ccxt.bybiteu import bybiteu  # noqa: F401
from ccxt.bybitid import bybitid  # noqa: F401
from ccxt.bydfi import bydfi  # noqa: F401
from ccxt.cex import cex  # noqa: F401
from ccxt.coinbase import coinbase  # noqa: F401
from ccxt.coinbaseexchange import coinbaseexchange  # noqa: F401
from ccxt.coinbaseinternational import coinbaseinternational  # noqa: F401
from ccxt.coincheck import coincheck  # noqa: F401
from ccxt.coinmate import coinmate  # noqa: F401
from ccxt.coinone import coinone  # noqa: F401
from ccxt.coinsph import coinsph  # noqa: F401
from ccxt.coinspot import coinspot  # noqa: F401
from ccxt.cryptocom import cryptocom  # noqa: F401
from ccxt.cryptomus import cryptomus  # noqa: F401
from ccxt.deepcoin import deepcoin  # noqa: F401
from ccxt.delta import delta  # noqa: F401
from ccxt.deribit import deribit  # noqa: F401
from ccxt.derive import derive  # noqa: F401
from ccxt.digifinex import digifinex  # noqa: F401
from ccxt.dydx import dydx  # noqa: F401
from ccxt.extended import extended  # noqa: F401
from ccxt.fmfwio import fmfwio  # noqa: F401
from ccxt.foxbit import foxbit  # noqa: F401
from ccxt.gate import gate  # noqa: F401
from ccxt.gateeu import gateeu  # noqa: F401
from ccxt.gemini import gemini  # noqa: F401
from ccxt.grvt import grvt  # noqa: F401
from ccxt.hashkey import hashkey  # noqa: F401
from ccxt.hibachi import hibachi  # noqa: F401
from ccxt.hitbtc import hitbtc  # noqa: F401
from ccxt.hollaex import hollaex  # noqa: F401
from ccxt.htx import htx  # noqa: F401
from ccxt.hyperliquid import hyperliquid  # noqa: F401
from ccxt.independentreserve import independentreserve  # noqa: F401
from ccxt.indodax import indodax  # noqa: F401
from ccxt.kraken import kraken  # noqa: F401
from ccxt.krakenfutures import krakenfutures  # noqa: F401
from ccxt.kucoin import kucoin  # noqa: F401
from ccxt.kucoinfutures import kucoinfutures  # noqa: F401
from ccxt.latoken import latoken  # noqa: F401
from ccxt.lbank import lbank  # noqa: F401
from ccxt.lighter import lighter  # noqa: F401
from ccxt.luno import luno  # noqa: F401
from ccxt.mercado import mercado  # noqa: F401
from ccxt.mexc import mexc  # noqa: F401
from ccxt.modetrade import modetrade  # noqa: F401
from ccxt.mudrex import mudrex  # noqa: F401
from ccxt.myokx import myokx  # noqa: F401
from ccxt.nado import nado  # noqa: F401
from ccxt.ndax import ndax  # noqa: F401
from ccxt.okx import okx  # noqa: F401
from ccxt.okxus import okxus  # noqa: F401
from ccxt.onetrading import onetrading  # noqa: F401
from ccxt.p2b import p2b  # noqa: F401
from ccxt.pacifica import pacifica  # noqa: F401
from ccxt.paradex import paradex  # noqa: F401
from ccxt.paymium import paymium  # noqa: F401
from ccxt.phemex import phemex  # noqa: F401
from ccxt.poloniex import poloniex  # noqa: F401
from ccxt.revolutx import revolutx  # noqa: F401
from ccxt.tokocrypto import tokocrypto  # noqa: F401
from ccxt.toobit import toobit  # noqa: F401
from ccxt.upbit import upbit  # noqa: F401
from ccxt.weex import weex  # noqa: F401
from ccxt.whitebit import whitebit  # noqa: F401
from ccxt.woo import woo  # noqa: F401
from ccxt.woofipro import woofipro  # noqa: F401
from ccxt.xt import xt  # noqa: F401
from ccxt.zaif import zaif  # noqa: F401
from ccxt.zebpay import zebpay  # noqa: F401

exchanges = [
    "alpaca",
    "apex",
    "aster",
    "backpack",
    "bequant",
    "bigone",
    "binance",
    "binancecoinm",
    "binanceus",
    "binanceusdm",
    "bingx",
    "bit2c",
    "bitbank",
    "bitbns",
    "bitfinex",
    "bitflyer",
    "bitget",
    "bithumb",
    "bitopro",
    "bitrue",
    "bitso",
    "bitstamp",
    "bitteam",
    "bittrade",
    "bitvavo",
    "blockchaincom",
    "blofin",
    "btcbox",
    "btcmarkets",
    "btcturk",
    "btse",
    "bullish",
    "bybit",
    "bybiteu",
    "bybitid",
    "bydfi",
    "cex",
    "coinbase",
    "coinbaseexchange",
    "coinbaseinternational",
    "coincheck",
    "coinmate",
    "coinone",
    "coinsph",
    "coinspot",
    "cryptocom",
    "cryptomus",
    "deepcoin",
    "delta",
    "deribit",
    "derive",
    "digifinex",
    "dydx",
    "extended",
    "fmfwio",
    "foxbit",
    "gate",
    "gateeu",
    "gemini",
    "grvt",
    "hashkey",
    "hibachi",
    "hitbtc",
    "hollaex",
    "htx",
    "hyperliquid",
    "independentreserve",
    "indodax",
    "kraken",
    "krakenfutures",
    "kucoin",
    "kucoinfutures",
    "latoken",
    "lbank",
    "lighter",
    "luno",
    "mercado",
    "mexc",
    "modetrade",
    "mudrex",
    "myokx",
    "nado",
    "ndax",
    "okx",
    "okxus",
    "onetrading",
    "p2b",
    "pacifica",
    "paradex",
    "paymium",
    "phemex",
    "poloniex",
    "revolutx",
    "tokocrypto",
    "toobit",
    "upbit",
    "weex",
    "whitebit",
    "woo",
    "woofipro",
    "xt",
    "zaif",
    "zebpay",
]

base = [
    "Exchange",
    "Precise",
    "exchanges",
    "decimal_to_precision",
]

__all__ = base + errors.__all__ + exchanges
