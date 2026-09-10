import datetime
from typing import Optional

import pytz


def is_ist_market_session_active(dt: Optional[datetime.datetime] = None) -> bool:
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


try:
    from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, create_engine
    from sqlalchemy.orm import declarative_base, relationship, sessionmaker
except ImportError:
    # Provide stub classes for type checking when sqlalchemy is not installed
    class _Column:
        def __init__(self, *args, **kwargs):
            pass
    class _Relationship:
        def __init__(self, *args, **kwargs):
            pass
    Boolean = Column = Date = DateTime = Float = ForeignKey = Integer = String = create_engine = _Column
    declarative_base = lambda: type('Base', (), {'__tablename__': ''})
    relationship = sessionmaker = _Relationship

Base = declarative_base()


class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, unique=True, nullable=False)
    name = Column(String)
    exchange = Column(String)  # NSE, BSE, etc.
    sector = Column(String)
    industry = Column(String)
    type = Column(String, nullable=False, default="equity")

    # Fundamental data fields
    market_cap = Column(Float)
    pe_ratio = Column(Float)
    forward_pe = Column(Float)
    eps = Column(Float)
    book_value = Column(Float)
    price_to_book = Column(Float)
    dividend_yield = Column(Float)
    dividend_rate = Column(Float)
    beta = Column(Float)
    profit_margin = Column(Float)
    operating_margin = Column(Float)
    return_on_equity = Column(Float)
    return_on_assets = Column(Float)
    total_revenue = Column(Float)
    total_debt = Column(Float)
    total_cash = Column(Float)
    debt_to_equity = Column(Float)
    shares_outstanding = Column(Float)
    float_shares = Column(Float)
    website = Column(String)
    country = Column(String)
    currency = Column(String)
    last_updated = Column(DateTime)  # timestamp of last data update

    prices = relationship("DailyPrice", back_populates="asset")
    suggestions = relationship("Suggestion", back_populates="asset")


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adj_close = Column(Float)
    volume = Column(Float)
    is_holiday = Column(Boolean, default=False)

    asset = relationship("Asset", back_populates="prices")


class Suggestion(Base):
    __tablename__ = "suggestions"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    action = Column(String, nullable=False)  # BUY, SELL, HOLD
    price = Column(Float)
    quantity = Column(Integer)
    reason = Column(String)
    status = Column(String, default="pending")  # pending, executed, cancelled
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    asset = relationship("Asset", back_populates="suggestions")