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


from google.protobuf.any_pb2 import Any
from google.protobuf.json_format import ParseDict

from .cosmos.crypto.secp256k1.keys_pb2 import PubKey
from .dydxprotocol.accountplus.tx_pb2 import TxExtension
from .dydxprotocol.clob.tx_pb2 import (
    MsgBatchCancel,
    MsgCancelOrder,
    MsgPlaceOrder,
)
from .dydxprotocol.sending.transfer_pb2 import (
    MsgDepositToSubaccount,
    MsgWithdrawFromSubaccount,
)
from .dydxprotocol.sending.tx_pb2 import MsgCreateTransfer

registry = {
    "/dydxprotocol.clob.MsgPlaceOrder": MsgPlaceOrder,
    "/dydxprotocol.clob.MsgCancelOrder": MsgCancelOrder,
    "/dydxprotocol.clob.MsgBatchCancel": MsgBatchCancel,
    "/dydxprotocol.sending.MsgCreateTransfer": MsgCreateTransfer,
    "/dydxprotocol.sending.MsgWithdrawFromSubaccount": MsgWithdrawFromSubaccount,
    "/dydxprotocol.sending.MsgDepositToSubaccount": MsgDepositToSubaccount,
    "/dydxprotocol.accountplus.TxExtension": TxExtension,
    "/cosmos.crypto.secp256k1.PubKey": PubKey,
}


def encode_as_any(encodeObject):
    typeUrl = encodeObject["typeUrl"]
    value = encodeObject["value"]
    t = registry[typeUrl]
    message = ParseDict(value, t())
    return Any(type_url=typeUrl, value=message.SerializeToString())
