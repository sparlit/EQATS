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

__version__ = "4.5.78"

# -----------------------------------------------------------------------------

from ccxt.async_support.alpaca import alpaca
from ccxt.async_support.apex import apex
from ccxt.async_support.aster import aster
from ccxt.async_support.backpack import backpack
from ccxt.async_support.base.exchange import Exchange
from ccxt.async_support.bequant import bequant
from ccxt.async_support.bigone import bigone
from ccxt.async_support.binance import binance
from ccxt.async_support.binancecoinm import binancecoinm
from ccxt.async_support.binanceus import binanceus
from ccxt.async_support.binanceusdm import binanceusdm
from ccxt.async_support.bingx import bingx
from ccxt.async_support.bit2c import bit2c
from ccxt.async_support.bitbank import bitbank
from ccxt.async_support.bitbns import bitbns
from ccxt.async_support.bitfinex import bitfinex
from ccxt.async_support.bitflyer import bitflyer
from ccxt.async_support.bitget import bitget
from ccxt.async_support.bithumb import bithumb
from ccxt.async_support.bitmex import bitmex
from ccxt.async_support.bitopro import bitopro
from ccxt.async_support.bitrue import bitrue
from ccxt.async_support.bitso import bitso
from ccxt.async_support.bitstamp import bitstamp
from ccxt.async_support.bitteam import bitteam
from ccxt.async_support.bittrade import bittrade
from ccxt.async_support.bitvavo import bitvavo
from ccxt.async_support.blockchaincom import blockchaincom
from ccxt.async_support.blofin import blofin
from ccxt.async_support.btcbox import btcbox
from ccxt.async_support.btcmarkets import btcmarkets
from ccxt.async_support.btcturk import btcturk
from ccxt.async_support.btse import btse
from ccxt.async_support.bullish import bullish
from ccxt.async_support.bybit import bybit
from ccxt.async_support.bybiteu import bybiteu
from ccxt.async_support.bydfi import bydfi
from ccxt.async_support.cex import cex
from ccxt.async_support.coinbase import coinbase
from ccxt.async_support.coinbaseexchange import coinbaseexchange
from ccxt.async_support.coinbaseinternational import coinbaseinternational
from ccxt.async_support.coincheck import coincheck
from ccxt.async_support.coinex import coinex
from ccxt.async_support.coinmate import coinmate
from ccxt.async_support.coinone import coinone
from ccxt.async_support.coinsph import coinsph
from ccxt.async_support.coinspot import coinspot
from ccxt.async_support.cryptocom import cryptocom
from ccxt.async_support.cryptomus import cryptomus
from ccxt.async_support.deepcoin import deepcoin
from ccxt.async_support.delta import delta
from ccxt.async_support.deribit import deribit
from ccxt.async_support.derive import derive
from ccxt.async_support.digifinex import digifinex
from ccxt.async_support.dydx import dydx
from ccxt.async_support.extended import extended
from ccxt.async_support.fmfwio import fmfwio
from ccxt.async_support.foxbit import foxbit
from ccxt.async_support.gate import gate
from ccxt.async_support.gateeu import gateeu
from ccxt.async_support.gemini import gemini
from ccxt.async_support.grvt import grvt
from ccxt.async_support.hashkey import hashkey
from ccxt.async_support.hibachi import hibachi
from ccxt.async_support.hitbtc import hitbtc
from ccxt.async_support.hollaex import hollaex
from ccxt.async_support.htx import htx
from ccxt.async_support.hyperliquid import hyperliquid
from ccxt.async_support.independentreserve import independentreserve
from ccxt.async_support.indodax import indodax
from ccxt.async_support.kraken import kraken
from ccxt.async_support.krakenfutures import krakenfutures
from ccxt.async_support.kucoin import kucoin
from ccxt.async_support.kucoinfutures import kucoinfutures
from ccxt.async_support.latoken import latoken
from ccxt.async_support.lbank import lbank
from ccxt.async_support.lighter import lighter
from ccxt.async_support.luno import luno
from ccxt.async_support.mercado import mercado
from ccxt.async_support.mexc import mexc
from ccxt.async_support.modetrade import modetrade
from ccxt.async_support.mudrex import mudrex
from ccxt.async_support.myokx import myokx
from ccxt.async_support.nado import nado
from ccxt.async_support.ndax import ndax
from ccxt.async_support.okx import okx
from ccxt.async_support.okxus import okxus
from ccxt.async_support.onetrading import onetrading
from ccxt.async_support.p2b import p2b
from ccxt.async_support.pacifica import pacifica
from ccxt.async_support.paradex import paradex
from ccxt.async_support.paymium import paymium
from ccxt.async_support.phemex import phemex
from ccxt.async_support.poloniex import poloniex
from ccxt.async_support.revolutx import revolutx
from ccxt.async_support.tokocrypto import tokocrypto
from ccxt.async_support.toobit import toobit
from ccxt.async_support.upbit import upbit
from ccxt.async_support.weex import weex
from ccxt.async_support.whitebit import whitebit
from ccxt.async_support.woo import woo
from ccxt.async_support.woofipro import woofipro
from ccxt.async_support.xt import xt
from ccxt.async_support.zaif import zaif
from ccxt.async_support.zebpay import zebpay
from ccxt.base import errors
from ccxt.base.decimal_to_precision import (
    DECIMAL_PLACES,
    NO_PADDING,
    PAD_WITH_ZERO,
    ROUND,
    SIGNIFICANT_DIGITS,
    TICK_SIZE,
    TRUNCATE,
    decimal_to_precision,
)
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
    "bitmex",
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
    "bydfi",
    "cex",
    "coinbase",
    "coinbaseexchange",
    "coinbaseinternational",
    "coincheck",
    "coinex",
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
