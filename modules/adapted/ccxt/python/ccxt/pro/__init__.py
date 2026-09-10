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

"""CCXT: CryptoCurrency eXchange Trading Library (Async)"""

# ----------------------------------------------------------------------------

__version__ = "4.5.78"

# ----------------------------------------------------------------------------

from ccxt.async_support.base.exchange import Exchange

# CCXT Pro exchanges (now this is mainly used for importing exchanges in WS tests)
# DO_NOT_REMOVE__ERROR_IMPORTS_START
from ccxt.base.errors import (
    AccountNotEnabled,
    AccountSuspended,
    AddressPending,
    ArgumentsRequired,
    AuthenticationError,
    BadRequest,
    BadResponse,
    BadSymbol,
    BaseError,
    CancelPending,
    ChecksumError,
    ContractUnavailable,
    DDoSProtection,
    DuplicateOrderId,
    ExchangeClosedByUser,
    ExchangeError,
    ExchangeNotAvailable,
    InsufficientFunds,
    InvalidAddress,
    InvalidNonce,
    InvalidOrder,
    InvalidProxySettings,
    ManualInteractionNeeded,
    MarginModeAlreadySet,
    MarketClosed,
    NetworkError,
    NoChange,
    NotSupported,
    NullResponse,
    OnMaintenance,
    OperationFailed,
    OperationRejected,
    OrderImmediatelyFillable,
    OrderNotCached,
    OrderNotFillable,
    OrderNotFound,
    PermissionDenied,
    RateLimitExceeded,
    RequestTimeout,
    RestrictedLocation,
    UnsubscribeError,
    error_hierarchy,
)

# DO_NOT_REMOVE__ERROR_IMPORTS_END
from ccxt.pro.alpaca import alpaca
from ccxt.pro.apex import apex
from ccxt.pro.aster import aster
from ccxt.pro.backpack import backpack
from ccxt.pro.bequant import bequant
from ccxt.pro.binance import binance
from ccxt.pro.binancecoinm import binancecoinm
from ccxt.pro.binanceus import binanceus
from ccxt.pro.binanceusdm import binanceusdm
from ccxt.pro.bingx import bingx
from ccxt.pro.bitfinex import bitfinex
from ccxt.pro.bitget import bitget
from ccxt.pro.bithumb import bithumb
from ccxt.pro.bitmex import bitmex
from ccxt.pro.bitopro import bitopro
from ccxt.pro.bitrue import bitrue
from ccxt.pro.bitstamp import bitstamp
from ccxt.pro.bittrade import bittrade
from ccxt.pro.bitvavo import bitvavo
from ccxt.pro.blockchaincom import blockchaincom
from ccxt.pro.blofin import blofin
from ccxt.pro.bullish import bullish
from ccxt.pro.bybit import bybit
from ccxt.pro.bybiteu import bybiteu
from ccxt.pro.bydfi import bydfi
from ccxt.pro.cex import cex
from ccxt.pro.coinbase import coinbase
from ccxt.pro.coinbaseexchange import coinbaseexchange
from ccxt.pro.coinbaseinternational import coinbaseinternational
from ccxt.pro.coincheck import coincheck
from ccxt.pro.coinex import coinex
from ccxt.pro.coinone import coinone
from ccxt.pro.cryptocom import cryptocom
from ccxt.pro.deepcoin import deepcoin
from ccxt.pro.deribit import deribit
from ccxt.pro.derive import derive
from ccxt.pro.dydx import dydx
from ccxt.pro.extended import extended
from ccxt.pro.gate import gate
from ccxt.pro.gateeu import gateeu
from ccxt.pro.gemini import gemini
from ccxt.pro.grvt import grvt
from ccxt.pro.hashkey import hashkey
from ccxt.pro.hitbtc import hitbtc
from ccxt.pro.hollaex import hollaex
from ccxt.pro.htx import htx
from ccxt.pro.hyperliquid import hyperliquid
from ccxt.pro.independentreserve import independentreserve
from ccxt.pro.kraken import kraken
from ccxt.pro.krakenfutures import krakenfutures
from ccxt.pro.kucoin import kucoin
from ccxt.pro.kucoinfutures import kucoinfutures
from ccxt.pro.lbank import lbank
from ccxt.pro.lighter import lighter
from ccxt.pro.luno import luno
from ccxt.pro.mexc import mexc
from ccxt.pro.modetrade import modetrade
from ccxt.pro.mudrex import mudrex
from ccxt.pro.myokx import myokx
from ccxt.pro.nado import nado
from ccxt.pro.ndax import ndax
from ccxt.pro.okx import okx
from ccxt.pro.okxus import okxus
from ccxt.pro.onetrading import onetrading
from ccxt.pro.p2b import p2b
from ccxt.pro.pacifica import pacifica
from ccxt.pro.paradex import paradex
from ccxt.pro.phemex import phemex
from ccxt.pro.poloniex import poloniex
from ccxt.pro.toobit import toobit
from ccxt.pro.upbit import upbit
from ccxt.pro.weex import weex
from ccxt.pro.whitebit import whitebit
from ccxt.pro.woo import woo
from ccxt.pro.woofipro import woofipro
from ccxt.pro.xt import xt

exchanges = [
    "alpaca",
    "apex",
    "aster",
    "backpack",
    "bequant",
    "binance",
    "binancecoinm",
    "binanceus",
    "binanceusdm",
    "bingx",
    "bitfinex",
    "bitget",
    "bithumb",
    "bitmex",
    "bitopro",
    "bitrue",
    "bitstamp",
    "bittrade",
    "bitvavo",
    "blockchaincom",
    "blofin",
    "bullish",
    "bybit",
    "bybiteu",
    "bydfi",
    "cex",
    "coinbase",
    "coinbaseexchange",
    "coinbaseinternational",
    "coincheck",
    "coinex",
    "coinone",
    "cryptocom",
    "deepcoin",
    "deribit",
    "derive",
    "dydx",
    "extended",
    "gate",
    "gateeu",
    "gemini",
    "grvt",
    "hashkey",
    "hitbtc",
    "hollaex",
    "htx",
    "hyperliquid",
    "independentreserve",
    "kraken",
    "krakenfutures",
    "kucoin",
    "kucoinfutures",
    "lbank",
    "lighter",
    "luno",
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
    "phemex",
    "poloniex",
    "toobit",
    "upbit",
    "weex",
    "whitebit",
    "woo",
    "woofipro",
    "xt",
]
