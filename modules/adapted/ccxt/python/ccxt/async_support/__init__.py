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

# -----------------------------------------------------------------------------

__version__ = "4.5.85"

# -----------------------------------------------------------------------------

from ccxt.async_support.alpaca import alpaca  # noqa: F401
from ccxt.async_support.apex import apex  # noqa: F401
from ccxt.async_support.aster import aster  # noqa: F401
from ccxt.async_support.backpack import backpack  # noqa: F401
from ccxt.async_support.base.exchange import Exchange  # noqa: F401
from ccxt.async_support.bequant import bequant  # noqa: F401
from ccxt.async_support.bigone import bigone  # noqa: F401
from ccxt.async_support.binance import binance  # noqa: F401
from ccxt.async_support.binancecoinm import binancecoinm  # noqa: F401
from ccxt.async_support.binanceus import binanceus  # noqa: F401
from ccxt.async_support.binanceusdm import binanceusdm  # noqa: F401
from ccxt.async_support.bingx import bingx  # noqa: F401
from ccxt.async_support.bit2c import bit2c  # noqa: F401
from ccxt.async_support.bitbank import bitbank  # noqa: F401
from ccxt.async_support.bitbns import bitbns  # noqa: F401
from ccxt.async_support.bitfinex import bitfinex  # noqa: F401
from ccxt.async_support.bitflyer import bitflyer  # noqa: F401
from ccxt.async_support.bitget import bitget  # noqa: F401
from ccxt.async_support.bithumb import bithumb  # noqa: F401
from ccxt.async_support.bitopro import bitopro  # noqa: F401
from ccxt.async_support.bitrue import bitrue  # noqa: F401
from ccxt.async_support.bitso import bitso  # noqa: F401
from ccxt.async_support.bitstamp import bitstamp  # noqa: F401
from ccxt.async_support.bitteam import bitteam  # noqa: F401
from ccxt.async_support.bittrade import bittrade  # noqa: F401
from ccxt.async_support.bitvavo import bitvavo  # noqa: F401
from ccxt.async_support.blockchaincom import blockchaincom  # noqa: F401
from ccxt.async_support.blofin import blofin  # noqa: F401
from ccxt.async_support.btcbox import btcbox  # noqa: F401
from ccxt.async_support.btcmarkets import btcmarkets  # noqa: F401
from ccxt.async_support.btcturk import btcturk  # noqa: F401
from ccxt.async_support.btse import btse  # noqa: F401
from ccxt.async_support.bullish import bullish  # noqa: F401
from ccxt.async_support.bybit import bybit  # noqa: F401
from ccxt.async_support.bybiteu import bybiteu  # noqa: F401
from ccxt.async_support.bybitid import bybitid  # noqa: F401
from ccxt.async_support.bydfi import bydfi  # noqa: F401
from ccxt.async_support.cex import cex  # noqa: F401
from ccxt.async_support.coinbase import coinbase  # noqa: F401
from ccxt.async_support.coinbaseexchange import coinbaseexchange  # noqa: F401
from ccxt.async_support.coinbaseinternational import coinbaseinternational  # noqa: F401
from ccxt.async_support.coincheck import coincheck  # noqa: F401
from ccxt.async_support.coinmate import coinmate  # noqa: F401
from ccxt.async_support.coinone import coinone  # noqa: F401
from ccxt.async_support.coinsph import coinsph  # noqa: F401
from ccxt.async_support.coinspot import coinspot  # noqa: F401
from ccxt.async_support.cryptocom import cryptocom  # noqa: F401
from ccxt.async_support.cryptomus import cryptomus  # noqa: F401
from ccxt.async_support.deepcoin import deepcoin  # noqa: F401
from ccxt.async_support.delta import delta  # noqa: F401
from ccxt.async_support.deribit import deribit  # noqa: F401
from ccxt.async_support.derive import derive  # noqa: F401
from ccxt.async_support.digifinex import digifinex  # noqa: F401
from ccxt.async_support.dydx import dydx  # noqa: F401
from ccxt.async_support.extended import extended  # noqa: F401
from ccxt.async_support.fmfwio import fmfwio  # noqa: F401
from ccxt.async_support.foxbit import foxbit  # noqa: F401
from ccxt.async_support.gate import gate  # noqa: F401
from ccxt.async_support.gateeu import gateeu  # noqa: F401
from ccxt.async_support.gemini import gemini  # noqa: F401
from ccxt.async_support.grvt import grvt  # noqa: F401
from ccxt.async_support.hashkey import hashkey  # noqa: F401
from ccxt.async_support.hibachi import hibachi  # noqa: F401
from ccxt.async_support.hitbtc import hitbtc  # noqa: F401
from ccxt.async_support.hollaex import hollaex  # noqa: F401
from ccxt.async_support.htx import htx  # noqa: F401
from ccxt.async_support.hyperliquid import hyperliquid  # noqa: F401
from ccxt.async_support.independentreserve import independentreserve  # noqa: F401
from ccxt.async_support.indodax import indodax  # noqa: F401
from ccxt.async_support.kraken import kraken  # noqa: F401
from ccxt.async_support.krakenfutures import krakenfutures  # noqa: F401
from ccxt.async_support.kucoin import kucoin  # noqa: F401
from ccxt.async_support.kucoinfutures import kucoinfutures  # noqa: F401
from ccxt.async_support.latoken import latoken  # noqa: F401
from ccxt.async_support.lbank import lbank  # noqa: F401
from ccxt.async_support.lighter import lighter  # noqa: F401
from ccxt.async_support.luno import luno  # noqa: F401
from ccxt.async_support.mercado import mercado  # noqa: F401
from ccxt.async_support.mexc import mexc  # noqa: F401
from ccxt.async_support.modetrade import modetrade  # noqa: F401
from ccxt.async_support.mudrex import mudrex  # noqa: F401
from ccxt.async_support.myokx import myokx  # noqa: F401
from ccxt.async_support.nado import nado  # noqa: F401
from ccxt.async_support.ndax import ndax  # noqa: F401
from ccxt.async_support.okx import okx  # noqa: F401
from ccxt.async_support.okxus import okxus  # noqa: F401
from ccxt.async_support.onetrading import onetrading  # noqa: F401
from ccxt.async_support.p2b import p2b  # noqa: F401
from ccxt.async_support.pacifica import pacifica  # noqa: F401
from ccxt.async_support.paradex import paradex  # noqa: F401
from ccxt.async_support.paymium import paymium  # noqa: F401
from ccxt.async_support.phemex import phemex  # noqa: F401
from ccxt.async_support.poloniex import poloniex  # noqa: F401
from ccxt.async_support.revolutx import revolutx  # noqa: F401
from ccxt.async_support.tokocrypto import tokocrypto  # noqa: F401
from ccxt.async_support.toobit import toobit  # noqa: F401
from ccxt.async_support.upbit import upbit  # noqa: F401
from ccxt.async_support.weex import weex  # noqa: F401
from ccxt.async_support.whitebit import whitebit  # noqa: F401
from ccxt.async_support.woo import woo  # noqa: F401
from ccxt.async_support.woofipro import woofipro  # noqa: F401
from ccxt.async_support.xt import xt  # noqa: F401
from ccxt.async_support.zaif import zaif  # noqa: F401
from ccxt.async_support.zebpay import zebpay  # noqa: F401
from ccxt.base import errors  # noqa: F401
from ccxt.base.decimal_to_precision import (
    DECIMAL_PLACES,  # noqa: F401
    NO_PADDING,  # noqa: F401
    PAD_WITH_ZERO,  # noqa: F401
    ROUND,  # noqa: F401
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
    "exchanges",
    "decimal_to_precision",
]

__all__ = base + errors.__all__ + exchanges
