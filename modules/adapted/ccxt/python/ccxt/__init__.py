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

__version__ = "4.5.78"

# ----------------------------------------------------------------------------

from ccxt.alpaca import alpaca
from ccxt.apex import apex
from ccxt.aster import aster
from ccxt.backpack import backpack
from ccxt.base import errors
from ccxt.base.decimal_to_precision import (
    DECIMAL_PLACES,
    NO_PADDING,
    PAD_WITH_ZERO,
    ROUND,
    ROUND_DOWN,
    ROUND_UP,
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
from ccxt.base.exchange import Exchange
from ccxt.base.precise import Precise
from ccxt.bequant import bequant
from ccxt.bigone import bigone
from ccxt.binance import binance
from ccxt.binancecoinm import binancecoinm
from ccxt.binanceus import binanceus
from ccxt.binanceusdm import binanceusdm
from ccxt.bingx import bingx
from ccxt.bit2c import bit2c
from ccxt.bitbank import bitbank
from ccxt.bitbns import bitbns
from ccxt.bitfinex import bitfinex
from ccxt.bitflyer import bitflyer
from ccxt.bitget import bitget
from ccxt.bithumb import bithumb
from ccxt.bitmex import bitmex
from ccxt.bitopro import bitopro
from ccxt.bitrue import bitrue
from ccxt.bitso import bitso
from ccxt.bitstamp import bitstamp
from ccxt.bitteam import bitteam
from ccxt.bittrade import bittrade
from ccxt.bitvavo import bitvavo
from ccxt.blockchaincom import blockchaincom
from ccxt.blofin import blofin
from ccxt.btcbox import btcbox
from ccxt.btcmarkets import btcmarkets
from ccxt.btcturk import btcturk
from ccxt.btse import btse
from ccxt.bullish import bullish
from ccxt.bybit import bybit
from ccxt.bybiteu import bybiteu
from ccxt.bydfi import bydfi
from ccxt.cex import cex
from ccxt.coinbase import coinbase
from ccxt.coinbaseexchange import coinbaseexchange
from ccxt.coinbaseinternational import coinbaseinternational
from ccxt.coincheck import coincheck
from ccxt.coinex import coinex
from ccxt.coinmate import coinmate
from ccxt.coinone import coinone
from ccxt.coinsph import coinsph
from ccxt.coinspot import coinspot
from ccxt.cryptocom import cryptocom
from ccxt.cryptomus import cryptomus
from ccxt.deepcoin import deepcoin
from ccxt.delta import delta
from ccxt.deribit import deribit
from ccxt.derive import derive
from ccxt.digifinex import digifinex
from ccxt.dydx import dydx
from ccxt.extended import extended
from ccxt.fmfwio import fmfwio
from ccxt.foxbit import foxbit
from ccxt.gate import gate
from ccxt.gateeu import gateeu
from ccxt.gemini import gemini
from ccxt.grvt import grvt
from ccxt.hashkey import hashkey
from ccxt.hibachi import hibachi
from ccxt.hitbtc import hitbtc
from ccxt.hollaex import hollaex
from ccxt.htx import htx
from ccxt.hyperliquid import hyperliquid
from ccxt.independentreserve import independentreserve
from ccxt.indodax import indodax
from ccxt.kraken import kraken
from ccxt.krakenfutures import krakenfutures
from ccxt.kucoin import kucoin
from ccxt.kucoinfutures import kucoinfutures
from ccxt.latoken import latoken
from ccxt.lbank import lbank
from ccxt.lighter import lighter
from ccxt.luno import luno
from ccxt.mercado import mercado
from ccxt.mexc import mexc
from ccxt.modetrade import modetrade
from ccxt.mudrex import mudrex
from ccxt.myokx import myokx
from ccxt.nado import nado
from ccxt.ndax import ndax
from ccxt.okx import okx
from ccxt.okxus import okxus
from ccxt.onetrading import onetrading
from ccxt.p2b import p2b
from ccxt.pacifica import pacifica
from ccxt.paradex import paradex
from ccxt.paymium import paymium
from ccxt.phemex import phemex
from ccxt.poloniex import poloniex
from ccxt.revolutx import revolutx
from ccxt.tokocrypto import tokocrypto
from ccxt.toobit import toobit
from ccxt.upbit import upbit
from ccxt.weex import weex
from ccxt.whitebit import whitebit
from ccxt.woo import woo
from ccxt.woofipro import woofipro
from ccxt.xt import xt
from ccxt.zaif import zaif
from ccxt.zebpay import zebpay

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
    "Precise",
    "exchanges",
    "decimal_to_precision",
]

__all__ = base + errors.__all__ + exchanges
