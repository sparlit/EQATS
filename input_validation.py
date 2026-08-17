"""
Input Validation Module
Provides comprehensive input validation using Pydantic models for all trading system inputs.
"""

from pydantic import BaseModel, Field, validator, ValidationError as PydanticValidationError
from typing import Optional, List, Dict, Any, Union
from decimal import Decimal
from datetime import datetime
import re


class ValidationError(Exception):
    """Custom validation error."""
    pass


class TradingSymbol(BaseModel):
    """Validated trading symbol."""
    symbol: str = Field(..., min_length=1, max_length=20, description="Trading symbol (e.g., EURUSD)")
    
    @validator('symbol')
    def validate_symbol_format(cls, v):
        """Validate symbol format (e.g., EURUSD, XAUUSD)."""
        v = v.upper()
        if not re.match(r'^[A-Z]{6,10}$', v):
            raise ValueError(f"Invalid symbol format: {v}. Expected format like EURUSD or XAUUSD")
        return v


class PriceValidation(BaseModel):
    """Validated price data."""
    price: Decimal = Field(..., gt=0, description="Price must be positive")
    symbol: TradingSymbol
    timestamp: Optional[datetime] = None
    
    @validator('price')
    def validate_price_range(cls, v):
        """Validate price is within reasonable range."""
        if v < Decimal('0.0001'):
            raise ValueError("Price too small (minimum 0.0001)")
        if v > Decimal('1000000'):
            raise ValueError("Price too large (maximum 1,000,000)")
        return v


class LotSizeValidation(BaseModel):
    """Validated lot size for trading."""
    lots: Decimal = Field(..., gt=0, description="Lot size must be positive")
    symbol: TradingSymbol
    
    @validator('lots')
    def validate_lot_size(cls, v):
        """Validate lot size is within reasonable range."""
        if v < Decimal('0.01'):
            raise ValueError("Minimum lot size is 0.01")
        if v > Decimal('100'):
            raise ValueError("Maximum lot size is 100")
        return v


class StopLossTakeProfitValidation(BaseModel):
    """Validated stop loss and take profit levels."""
    stop_loss: Optional[Decimal] = Field(None, gt=0, description="Stop loss price")
    take_profit: Optional[Decimal] = Field(None, gt=0, description="Take profit price")
    entry_price: Decimal = Field(..., gt=0, description="Entry price")
    symbol: TradingSymbol
    
    @validator('stop_loss')
    def validate_stop_loss(cls, v, values):
        """Validate stop loss is reasonable relative to entry price."""
        if v is None:
            return v
        entry_price = values.get('entry_price')
        if entry_price:
            # Stop loss should not be more than 50% away from entry
            distance = abs(v - entry_price) / entry_price
            if distance > Decimal('0.5'):
                raise ValueError("Stop loss too far from entry price (max 50%)")
        return v
    
    @validator('take_profit')
    def validate_take_profit(cls, v, values):
        """Validate take profit is reasonable relative to entry price."""
        if v is None:
            return v
        entry_price = values.get('entry_price')
        if entry_price:
            # Take profit should not be more than 100% away from entry
            distance = abs(v - entry_price) / entry_price
            if distance > Decimal('1.0'):
                raise ValueError("Take profit too far from entry price (max 100%)")
        return v


class OrderValidation(BaseModel):
    """Comprehensive order validation."""
    symbol: str = Field(..., description="Trading symbol")
    order_type: str = Field(..., description="Order type: BUY, SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP")
    lots: Decimal = Field(..., gt=0, description="Lot size")
    price: Optional[Decimal] = Field(None, gt=0, description="Price for limit/stop orders")
    stop_loss: Optional[Decimal] = Field(None, gt=0, description="Stop loss")
    take_profit: Optional[Decimal] = Field(None, gt=0, description="Take profit")
    comment: Optional[str] = Field(None, max_length=100, description="Order comment")
    
    @validator('order_type')
    def validate_order_type(cls, v):
        """Validate order type is one of the allowed values."""
        valid_types = ['BUY', 'SELL', 'BUY_LIMIT', 'SELL_LIMIT', 'BUY_STOP', 'SELL_STOP']
        if v.upper() not in valid_types:
            raise ValueError(f"Invalid order type: {v}. Must be one of {valid_types}")
        return v.upper()
    
    @validator('lots')
    def validate_lots(cls, v):
        """Validate lot size."""
        if v < Decimal('0.01'):
            raise ValueError("Minimum lot size is 0.01")
        if v > Decimal('100'):
            raise ValueError("Maximum lot size is 100")
        return v
    
    @validator('price')
    def validate_price(cls, v, values):
        """Validate price is required for limit/stop orders."""
        order_type = values.get('order_type')
        if order_type in ['BUY_LIMIT', 'SELL_LIMIT', 'BUY_STOP', 'SELL_STOP'] and v is None:
            raise ValueError(f"Price is required for {order_type} orders")
        return v


class UsernameValidation(BaseModel):
    """Validated username."""
    username: str = Field(..., min_length=3, max_length=50, description="Username")
    
    @validator('username')
    def validate_username_format(cls, v):
        """Validate username format (alphanumeric and underscore only)."""
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("Username can only contain letters, numbers, and underscores")
        if v.startswith('_') or v.endswith('_'):
            raise ValueError("Username cannot start or end with underscore")
        return v.lower()


class PasswordValidation(BaseModel):
    """Validated password."""
    password: str = Field(..., min_length=8, max_length=128, description="Password")
    
    @validator('password')
    def validate_password_strength(cls, v):
        """Validate password strength."""
        if not re.search(r'[A-Z]', v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r'[a-z]', v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r'[0-9]', v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError("Password must contain at least one special character")
        return v


class PINValidation(BaseModel):
    """Validated PIN."""
    pin: str = Field(..., min_length=4, max_length=8, description="PIN")
    
    @validator('pin')
    def validate_pin_format(cls, v):
        """Validate PIN is numeric only."""
        if not v.isdigit():
            raise ValueError("PIN must contain only digits")
        return v


class MFATokenValidation(BaseModel):
    """Validated MFA token."""
    token: str = Field(..., min_length=6, max_length=6, description="MFA token")
    
    @validator('token')
    def validate_token_format(cls, v):
        """Validate token is 6-digit numeric."""
        if not v.isdigit():
            raise ValueError("MFA token must be 6 digits")
        return v


class BackupCodeValidation(BaseModel):
    """Validated backup code."""
    code: str = Field(..., min_length=8, max_length=8, description="Backup code")
    
    @validator('code')
    def validate_code_format(cls, v):
        """Validate backup code format (8 alphanumeric characters)."""
        if not re.match(r'^[A-Z0-9]{8}$', v):
            raise ValueError("Backup code must be 8 alphanumeric characters")
        return v.upper()


class ConfigurationValidation(BaseModel):
    """Validated configuration parameters."""
    key: str = Field(..., min_length=1, max_length=100, description="Configuration key")
    value: str = Field(..., description="Configuration value")
    
    @validator('key')
    def validate_key_format(cls, v):
        """Validate configuration key format."""
        if not re.match(r'^[a-zA-Z0-9_.-]+$', v):
            raise ValueError("Configuration key can only contain letters, numbers, underscores, hyphens, and dots")
        return v


class APICredentialValidation(BaseModel):
    """Validated API credentials."""
    api_key: str = Field(..., min_length=16, max_length=256, description="API key")
    api_secret: str = Field(..., min_length=16, max_length=256, description="API secret")
    
    @validator('api_key')
    def validate_api_key(cls, v):
        """Validate API key format."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("API key can only contain letters, numbers, underscores, and hyphens")
        return v
    
    @validator('api_secret')
    def validate_api_secret(cls, v):
        """Validate API secret format."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("API secret can only contain letters, numbers, underscores, and hyphens")
        return v


class DateTimeValidation(BaseModel):
    """Validated datetime."""
    datetime_str: str = Field(..., description="DateTime string")
    
    @validator('datetime_str')
    def validate_datetime(cls, v):
        """Validate datetime format."""
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Invalid datetime format: {v}. Expected ISO format (YYYY-MM-DD HH:MM:SS)")
        return v


class EmailValidation(BaseModel):
    """Validated email address."""
    email: str = Field(..., description="Email address")
    
    @validator('email')
    def validate_email_format(cls, v):
        """Validate email format."""
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError(f"Invalid email format: {v}")
        return v.lower()


class URLValidation(BaseModel):
    """Validated URL."""
    url: str = Field(..., description="URL")
    
    @validator('url')
    def validate_url_format(cls, v):
        """Validate URL format."""
        if not re.match(r'^https?://[a-zA-Z0-9.-]+(?:\.[a-zA-Z]{2,})?(?:/[^\s]*)?$', v):
            raise ValueError(f"Invalid URL format: {v}")
        return v


class PositiveIntegerValidation(BaseModel):
    """Validated positive integer."""
    value: int = Field(..., gt=0, description="Positive integer")
    
    @validator('value')
    def validate_positive(cls, v):
        """Validate value is positive."""
        if v <= 0:
            raise ValueError("Value must be positive")
        return v


class PercentageValidation(BaseModel):
    """Validated percentage."""
    percentage: Decimal = Field(..., ge=0, le=100, description="Percentage (0-100)")
    
    @validator('percentage')
    def validate_percentage(cls, v):
        """Validate percentage is between 0 and 100."""
        if v < 0 or v > 100:
            raise ValueError("Percentage must be between 0 and 100")
        return v


class InputValidator:
    """
    Central input validation manager.
    Provides validation methods for all common input types.
    """
    
    @staticmethod
    def validate_symbol(symbol: str) -> str:
        """Validate trading symbol."""
        try:
            validated = TradingSymbol(symbol=symbol)
            return validated.symbol
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid symbol: {e}")
    
    @staticmethod
    def validate_price(price: Union[str, Decimal, float], symbol: str) -> Decimal:
        """Validate price."""
        try:
            if isinstance(price, str):
                price = Decimal(price)
            elif isinstance(price, float):
                price = Decimal(str(price))
            
            validated = PriceValidation(
                price=price,
                symbol=TradingSymbol(symbol=symbol)
            )
            return validated.price
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid price: {e}")
    
    @staticmethod
    def validate_lots(lots: Union[str, Decimal, float], symbol: str) -> Decimal:
        """Validate lot size."""
        try:
            if isinstance(lots, str):
                lots = Decimal(lots)
            elif isinstance(lots, float):
                lots = Decimal(str(lots))
            
            validated = LotSizeValidation(
                lots=lots,
                symbol=TradingSymbol(symbol=symbol)
            )
            return validated.lots
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid lot size: {e}")
    
    @staticmethod
    def validate_order(order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate order data."""
        try:
            # Validate symbol separately first
            if 'symbol' in order_data:
                order_data['symbol'] = InputValidator.validate_symbol(order_data['symbol'])
            
            # Validate lots
            if 'lots' in order_data:
                if isinstance(order_data['lots'], str):
                    order_data['lots'] = Decimal(order_data['lots'])
                elif isinstance(order_data['lots'], float):
                    order_data['lots'] = Decimal(str(order_data['lots']))
            
            # Validate price fields
            for field in ['price', 'stop_loss', 'take_profit']:
                if field in order_data and order_data[field] is not None:
                    if isinstance(order_data[field], str):
                        order_data[field] = Decimal(order_data[field])
                    elif isinstance(order_data[field], float):
                        order_data[field] = Decimal(str(order_data[field]))
            
            validated = OrderValidation(**order_data)
            return validated.dict()
        except Exception as e:
            raise ValidationError(f"Invalid order: {e}")
    
    @staticmethod
    def validate_username(username: str) -> str:
        """Validate username."""
        try:
            validated = UsernameValidation(username=username)
            return validated.username
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid username: {e}")
    
    @staticmethod
    def validate_password(password: str) -> str:
        """Validate password."""
        try:
            validated = PasswordValidation(password=password)
            return validated.password
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid password: {e}")
    
    @staticmethod
    def validate_pin(pin: str) -> str:
        """Validate PIN."""
        try:
            validated = PINValidation(pin=pin)
            return validated.pin
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid PIN: {e}")
    
    @staticmethod
    def validate_mfa_token(token: str) -> str:
        """Validate MFA token."""
        try:
            validated = MFATokenValidation(token=token)
            return validated.token
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid MFA token: {e}")
    
    @staticmethod
    def validate_backup_code(code: str) -> str:
        """Validate backup code."""
        try:
            validated = BackupCodeValidation(code=code)
            return validated.code
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid backup code: {e}")
    
    @staticmethod
    def validate_config(key: str, value: str) -> tuple:
        """Validate configuration key-value pair."""
        try:
            validated = ConfigurationValidation(key=key, value=value)
            return validated.key, validated.value
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid configuration: {e}")
    
    @staticmethod
    def validate_api_credentials(api_key: str, api_secret: str) -> tuple:
        """Validate API credentials."""
        try:
            validated = APICredentialValidation(api_key=api_key, api_secret=api_secret)
            return validated.api_key, validated.api_secret
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid API credentials: {e}")
    
    @staticmethod
    def validate_datetime(datetime_str: str) -> str:
        """Validate datetime string."""
        try:
            validated = DateTimeValidation(datetime_str=datetime_str)
            return validated.datetime_str
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid datetime: {e}")
    
    @staticmethod
    def validate_email(email: str) -> str:
        """Validate email address."""
        try:
            validated = EmailValidation(email=email)
            return validated.email
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid email: {e}")
    
    @staticmethod
    def validate_url(url: str) -> str:
        """Validate URL."""
        try:
            validated = URLValidation(url=url)
            return validated.url
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid URL: {e}")
    
    @staticmethod
    def validate_positive_integer(value: int) -> int:
        """Validate positive integer."""
        try:
            validated = PositiveIntegerValidation(value=value)
            return validated.value
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid positive integer: {e}")
    
    @staticmethod
    def validate_percentage(percentage: Union[str, Decimal, float]) -> Decimal:
        """Validate percentage."""
        try:
            if isinstance(percentage, str):
                percentage = Decimal(percentage)
            elif isinstance(percentage, float):
                percentage = Decimal(str(percentage))
            
            validated = PercentageValidation(percentage=percentage)
            return validated.percentage
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid percentage: {e}")


# Global validator instance
_global_validator = InputValidator()


def get_validator() -> InputValidator:
    """Get the global input validator instance."""
    return _global_validator
