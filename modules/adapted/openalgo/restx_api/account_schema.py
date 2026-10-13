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


from marshmallow import INCLUDE, Schema, fields, validate


class FundsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class OrderbookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class TradebookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class PositionbookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class HoldingsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class OrderStatusSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy = fields.Str(required=True)
    orderid = fields.Str(required=True)


class OpenPositionSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy = fields.Str(required=True)
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)
    product = fields.Str(required=True, validate=validate.OneOf(["MIS", "NRML", "CNC"]))


class AnalyzerSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class AnalyzerToggleSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    mode = fields.Bool(required=True)


class PingSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class ChartSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))

    class Meta:
        # Allow unknown fields - chart preferences can have any key-value pairs
        unknown = INCLUDE


class PnlSymbolsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
