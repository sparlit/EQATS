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


from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class TransactionBase(BaseModel):
    symbol: str
    type: str  # BUY or SELL
    quantity: int
    price: float


class TransactionCreate(TransactionBase):
    id: str


class Transaction(TransactionBase):
    id: str
    timestamp: datetime

    class Config:
        orm_mode = True


class PositionBase(BaseModel):
    symbol: str
    quantity: int
    average_price: float
    take_profit: float | None = None
    stop_loss: float | None = None


class PositionCreate(PositionBase):
    pass


class Position(PositionBase):
    id: int

    class Config:
        orm_mode = True


class UserBase(BaseModel):
    username: str | None = None
    email: str
    full_name: str | None = None
    is_pro: bool = False


class UserCreate(UserBase):
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class User(UserBase):
    id: int
    cash_balance: float
    positions: list[Position] = []
    transactions: list[Transaction] = []

    class Config:
        from_attributes = True
