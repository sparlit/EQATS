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


import grpc
import matchengine_pb2
import matchengine_pb2_grpc
import ordersigner_pb2
import ordersigner_pb2_grpc

uid = 11


signer_channel = grpc.insecure_channel("localhost:50061")
signer_stub = ordersigner_pb2_grpc.OrderSignerStub(signer_channel)


matchengine_channel = grpc.insecure_channel("localhost:50051")
matchengine_stub = matchengine_pb2_grpc.MatchengineStub(matchengine_channel)


def put_order():
    uid = 3
    order = ordersigner_pb2.SignOrderRequest(
        user_id=uid,
        market="ETH_USDT",
        order_side=ordersigner_pb2.OrderSide.BID,
        order_type=ordersigner_pb2.OrderType.LIMIT,
        amount="1",
        price="1000",
    )
    sig = signer_stub.SignOrder(order).signature
    order_final = matchengine_pb2.OrderPutRequest(
        user_id=uid,
        market="ETH_USDT",
        order_side=matchengine_pb2.OrderSide.BID,
        order_type=matchengine_pb2.OrderType.LIMIT,
        amount="1",
        price="1000",
        signature=sig,
    )
    res = matchengine_stub.OrderPut(order_final)
    print(res)


put_order()
