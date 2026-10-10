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


from src.option.cash_market_lib import get_close_prices
from src.option.future_lots_lib import get_future_data

# def main():
#     symbol_to_lot_map = get_future_data()
#     print(symbol_to_lot_map)
from src.option.max_pain_lib import get_max_pain

symbol_to_close = get_close_prices()

symbol_to_lot_map = get_future_data()
# print(symbol_to_lot_map)

symbol_to_pain_map = {}
csv_hdr = "symbol, lot, cm_close,max_pain,support,resist,call_close,range_pct,prem_pct,dist_pct"
print(
    "{:16s} | {:6s} | {:8s} | {:8s} | {:8s} | {:8s} | {:8s} | {:8s}| {:8s} | {:8s} |".format(
        "symbol",
        " lot",
        "cm_close",
        "  pain",
        " support",
        "resist",
        "om_close",
        "range_pct",
        " pre_pct",
        "dist_pct",
    )
)
for each_symbol in symbol_to_lot_map:
    lot = symbol_to_lot_map[each_symbol]
    max_pain, support, putt_close, resistance, call_close = get_max_pain(each_symbol, lot)
    # print(each_symbol, max_pain, support, resistance)
    close_price = float(symbol_to_close[each_symbol]) if each_symbol in symbol_to_close else 0
    pct = 0 if close_price == 0 else call_close / (close_price / 100)
    dist = 100 - close_price / (resistance / 100)
    op_range = resistance - support
    mid = (resistance + support) / 2
    range_pct = op_range / (mid / 100)
    print(
        f"{each_symbol:16s} | {lot:6.0f} | {close_price:8.2f} | {max_pain:8.2f} | {support:8.2f} | {resistance:8.2f} | {call_close:8.2f} | {range_pct:8.2f} | {pct:8.2f} | {dist:8.2f} |"
    )
    # csv_str = each_symbol + ',' + str(close_price) + ',' + str(max_pain) + ',' + str(support) + ',' + str(resistance) + ',' + str(call_close) + ',' + str(pct) + ',' + str(dist)
    # print(csv_str)
    symbol_to_pain_map[each_symbol] = max_pain

# print(symbol_to_pain_map)
