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


import ctypes
from typing import Any, Dict, List, Optional, Tuple, Union


class ApiKeyResponse(ctypes.Structure):
    _fields_ = [("privateKey", ctypes.c_void_p), ("publicKey", ctypes.c_void_p), ("err", ctypes.c_void_p)]


class CreateOrderTxReq(ctypes.Structure):
    _fields_ = [
        ("MarketIndex", ctypes.c_int),
        ("ClientOrderIndex", ctypes.c_longlong),
        ("BaseAmount", ctypes.c_longlong),
        ("Price", ctypes.c_uint32),
        ("IsAsk", ctypes.c_uint8),
        ("Type", ctypes.c_uint8),
        ("TimeInForce", ctypes.c_uint8),
        ("ReduceOnly", ctypes.c_uint8),
        ("TriggerPrice", ctypes.c_uint32),
        ("OrderExpiry", ctypes.c_longlong),
    ]


class StrOrErr(ctypes.Structure):
    _fields_ = [("str", ctypes.c_void_p), ("err", ctypes.c_void_p)]


class SignedTxResponse(ctypes.Structure):
    _fields_ = [
        ("txType", ctypes.c_uint8),
        ("txInfo", ctypes.c_void_p),
        ("txHash", ctypes.c_void_p),
        ("messageToSign", ctypes.c_void_p),
        ("err", ctypes.c_void_p),
    ]


lighterSigner = None


def load_lighter_library(path):
    global lighterSigner

    if lighterSigner is not None:
        return lighterSigner

    lighterSigner = ctypes.CDLL(path)
    lighterSigner.GenerateAPIKey.argtypes = []
    lighterSigner.GenerateAPIKey.restype = ApiKeyResponse

    lighterSigner.CreateClient.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.CreateClient.restype = ctypes.c_char_p

    lighterSigner.CheckClient.argtypes = [ctypes.c_int, ctypes.c_longlong]
    lighterSigner.CheckClient.restype = ctypes.c_void_p

    lighterSigner.SignChangePubKey.argtypes = [
        ctypes.c_char_p,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignChangePubKey.restype = SignedTxResponse

    lighterSigner.SignCreateOrder.argtypes = [
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignCreateOrder.restype = SignedTxResponse

    lighterSigner.SignCreateGroupedOrders.argtypes = [
        ctypes.c_uint8,
        ctypes.POINTER(CreateOrderTxReq),
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignCreateGroupedOrders.restype = SignedTxResponse

    lighterSigner.SignCancelOrder.argtypes = [
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignCancelOrder.restype = SignedTxResponse

    lighterSigner.SignWithdraw.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignWithdraw.restype = SignedTxResponse

    lighterSigner.SignCreateSubAccount.argtypes = [ctypes.c_uint8, ctypes.c_longlong, ctypes.c_int, ctypes.c_longlong]
    lighterSigner.SignCreateSubAccount.restype = SignedTxResponse

    lighterSigner.SignCancelAllOrders.argtypes = [
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignCancelAllOrders.restype = SignedTxResponse

    lighterSigner.SignModifyOrder.argtypes = [
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignModifyOrder.restype = SignedTxResponse

    lighterSigner.SignTransfer.argtypes = [
        ctypes.c_longlong,
        ctypes.c_int16,
        ctypes.c_int8,
        ctypes.c_int8,
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_char_p,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignTransfer.restype = SignedTxResponse

    lighterSigner.SignCreatePublicPool.argtypes = [
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignCreatePublicPool.restype = SignedTxResponse

    lighterSigner.SignUpdatePublicPool.argtypes = [
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignUpdatePublicPool.restype = SignedTxResponse

    lighterSigner.SignMintShares.argtypes = [
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignMintShares.restype = SignedTxResponse

    lighterSigner.SignBurnShares.argtypes = [
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignBurnShares.restype = SignedTxResponse

    lighterSigner.SignStakeAssets.argtypes = [
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignStakeAssets.restype = SignedTxResponse

    lighterSigner.SignUnstakeAssets.argtypes = [
        ctypes.c_longlong,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignUnstakeAssets.restype = SignedTxResponse

    lighterSigner.SignUpdateLeverage.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignUpdateLeverage.restype = SignedTxResponse

    lighterSigner.CreateAuthToken.argtypes = [ctypes.c_longlong, ctypes.c_int, ctypes.c_longlong]
    lighterSigner.CreateAuthToken.restype = StrOrErr

    # Note: SwitchAPIKey is no longer exported in the new binary
    # All functions now take api_key_index directly, so switching is handled via parameters

    lighterSigner.SignUpdateMargin.argtypes = [
        ctypes.c_int,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignUpdateMargin.restype = SignedTxResponse

    lighterSigner.SignApproveIntegrator.argtypes = [
        ctypes.c_longlong,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_longlong,
        ctypes.c_uint8,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    lighterSigner.SignApproveIntegrator.restype = SignedTxResponse

    lighterSigner.Free.argtypes = [ctypes.c_void_p]
    lighterSigner.Free.restype = None
    return lighterSigner


def decode_and_free(ptr: Any) -> str | None:
    if not ptr:
        return None
    try:
        # Read the string from the pointer
        c_str = ctypes.cast(ptr, ctypes.c_char_p).value
        if c_str is not None:
            return c_str.decode("utf-8")
        return None
    finally:
        # Free the memory using the signer's own Free function to ensure
        # the same C runtime that allocated the memory also frees it.
        # This is critical on Windows where different CRTs have separate heaps.
        lighterSigner.Free(ptr)


def decode_api_key(result: SignedTxResponse) -> tuple[str, str, None] | tuple[None, None, str]:
    private_key_str = decode_and_free(result.privateKey)
    public_key_str = decode_and_free(result.publicKey)
    error = decode_and_free(result.err)
    return private_key_str, public_key_str, error


def decode_tx_info(result: SignedTxResponse) -> tuple[str, str, str, None] | tuple[None, None, None, str]:
    tx_type = result.txType
    tx_info_str = decode_and_free(result.txInfo)
    tx_hash_str = decode_and_free(result.txHash)
    message_to_sign = decode_and_free(result.messageToSign)
    error = decode_and_free(result.err)

    return tx_type, tx_info_str, tx_hash_str, message_to_sign, error


def decode_auth(result: StrOrErr) -> tuple[str, None] | tuple[None, str]:
    token = decode_and_free(result.str)
    error = decode_and_free(result.err)
    return token, error
