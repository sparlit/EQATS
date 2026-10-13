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


from numba import types
from numba.core import cgutils
from numba.core.extending import intrinsic


@intrinsic
def ptr_from_val(typingctx, src):
    def codegen(context, builder, signature, args):
        ptr = cgutils.alloca_once_value(builder, args[0])
        return ptr

    sig = types.CPointer(src)(src)
    return sig, codegen


@intrinsic
def val_from_ptr(typingctx, src):
    def codegen(context, builder, signature, args):
        val = builder.load(args[0])
        return val

    sig = src.dtype(src)
    return sig, codegen


@intrinsic
def address_as_void_pointer(typingctx, src):
    def codegen(context, builder, signature, args):
        return builder.inttoptr(args[0], cgutils.voidptr_t)

    sig = types.voidptr(src)
    return sig, codegen


@intrinsic
def is_null_ptr(typingctx, src):
    def codegen(context, builder, signature, args):
        return cgutils.is_null(builder, args[0])

    sig = types.boolean(src)
    return sig, codegen
