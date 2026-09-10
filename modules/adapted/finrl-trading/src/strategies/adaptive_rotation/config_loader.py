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


"""
Configuration Loader for Adaptive Multi-Asset Rotation Strategy
================================================================

This module loads and validates the YAML configuration file using Pydantic.
All configuration parameters are validated at load time to ensure correctness.

Author: Adaptive Rotation Strategy Team
Version: 1.2.1
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# ============================================================================
# Pydantic Models for Configuration Sections
# ============================================================================


class StrategyConfig(BaseModel):
    """Strategy metadata"""

    name: str
    version: str
    base_frequency: Literal["daily", "weekly", "monthly"] = "daily"
    rebalance_frequency: Literal["daily", "weekly", "monthly"] = "weekly"


class PathsConfig(BaseModel):
    """File paths configuration"""

    data_root: str
    output_root: str = "./output"
    state_dir: str = "./output/state/adaptive_rotation"
    audit_dir: str = "./output/audit/adaptive_rotation"
    weights_dir: str = "./output/weights/adaptive_rotation"


class DatesConfig(BaseModel):
    """Date range configuration"""

    start_date: str
    end_date: str | None = None

    @field_validator("start_date", mode="before")
    @classmethod
    def validate_start_date(cls, v):
        """Validate start date format and convert date objects to strings"""
        # Handle date objects from YAML parser
        if hasattr(v, "strftime"):  # datetime.date or datetime.datetime
            return v.strftime("%Y-%m-%d")

        # Validate string format
        if isinstance(v, str):
            try:
                datetime.strptime(v, "%Y-%m-%d")
                return v
            except ValueError:
                msg = f"start_date must be in YYYY-MM-DD format, got {v}"
                raise ValueError(msg)

        msg = f"start_date must be a string or date object, got {type(v)}"
        raise ValueError(msg)

    @field_validator("end_date", mode="before")
    @classmethod
    def validate_end_date(cls, v):
        """Validate end date format and convert date objects to strings"""
        if v is None:
            return v

        # Handle date objects from YAML parser
        if hasattr(v, "strftime"):  # datetime.date or datetime.datetime
            return v.strftime("%Y-%m-%d")

        # Validate string format
        if isinstance(v, str):
            try:
                datetime.strptime(v, "%Y-%m-%d")
                return v
            except ValueError:
                msg = f"end_date must be in YYYY-MM-DD format or null, got {v}"
                raise ValueError(msg)

        msg = f"end_date must be a string or date object, got {type(v)}"
        raise ValueError(msg)


class HistoryConfig(BaseModel):
    """Historical data requirements"""

    minimum_history_weeks: int = Field(ge=1, le=260)  # 1 week to 5 years


class BenchmarkConfig(BaseModel):
    """Benchmark configuration"""

    excess_return_benchmark: str = "QQQ"


class AssetGroupConfig(BaseModel):
    """Single asset group configuration"""

    max_assets: int = Field(ge=1, le=10)
    symbols: list[str] = Field(min_length=1)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v):
        """Validate symbols are non-empty and unique"""
        if not v:
            msg = "Asset group must have at least one symbol"
            raise ValueError(msg)
        if len(v) != len(set(v)):
            msg = "Duplicate symbols in asset group"
            raise ValueError(msg)
        return v


class VolatilityConfig(BaseModel):
    """Volatility threshold configuration"""

    vix_lookback_years: int = Field(ge=1, le=10)
    vix_z_threshold: float = Field(ge=1.0, le=5.0)


class RegimeMappingConfig(BaseModel):
    """Single regime mapping"""

    risk_score: int = Field(ge=0, le=3)
    group_cap: float = Field(ge=0.0, le=1.0)
    cash_floor: float = Field(ge=0.0, le=1.0)


class RegimeMappingsConfig(BaseModel):
    """All regime mappings"""

    risk_on: RegimeMappingConfig
    neutral: RegimeMappingConfig
    risk_off: RegimeMappingConfig


class SlowRegimeConfig(BaseModel):
    """Slow regime detection configuration"""

    trend_ma_weeks: int = Field(ge=10, le=52)
    drawdown_weeks: int = Field(ge=4, le=26)
    drawdown_threshold: float = Field(ge=0.01, le=0.5)
    volatility: VolatilityConfig
    persistence_weeks: int = Field(ge=1, le=8)
    mapping: RegimeMappingsConfig


class MarketRegimeConfig(BaseModel):
    """Market regime configuration"""

    slow_regime: SlowRegimeConfig


class PriceShockConfig(BaseModel):
    """Price shock detection"""

    lookback_days: int = Field(ge=1, le=10)
    drawdown_threshold: float = Field(ge=-0.20, le=-0.01)


class VolatilityShockConfig(BaseModel):
    """Volatility shock detection"""

    vix_z_threshold: float = Field(ge=1.0, le=5.0)
    delta_vix_z_threshold: float = Field(ge=1.0, le=10.0)


class FastRiskOffBehaviorConfig(BaseModel):
    """Fast risk-off behavior"""

    group_cap: float = Field(ge=0.0, le=1.0)
    cash_floor: float = Field(ge=0.0, le=1.0)
    duration_days: int = Field(ge=1, le=20)


class FastRiskOffConfig(BaseModel):
    """Fast risk-off overlay configuration"""

    price_shock: PriceShockConfig
    volatility_shock: VolatilityShockConfig
    behavior: FastRiskOffBehaviorConfig
    stop_loss_multiplier: float = Field(ge=0.1, le=1.0)


class GroupStrengthConfig(BaseModel):
    """Group strength computation"""

    metric: Literal["risk_adjusted_return", "return", "sharpe"]
    lookback_weeks: int = Field(ge=4, le=52)
    trend_filter: bool = True


class RankingConfig(BaseModel):
    """Asset ranking configuration"""

    method: Literal["zscore", "percentile", "raw"]
    robust: bool = True
    top_n_per_group: int = Field(ge=1, le=10)

    # Z-score calculation parameters (optional, with defaults)
    zscore_window: int | None = Field(default=12, ge=4, le=52)
    max_zscore: float | None = Field(default=20.0, ge=5.0, le=100.0)
    min_mad_threshold: float | None = Field(default=1e-6, ge=1e-10, le=1e-3)


class ExceptionReentryConfig(BaseModel):
    """Exception re-entry rules"""

    cooldown_weeks: int = Field(ge=1, le=26)
    stricter_threshold_multiplier: float = Field(ge=1.0, le=3.0)


class StrongSignalConfig(BaseModel):
    """Strong signal exception rule configuration"""

    enabled: bool = False
    z_threshold: float = Field(default=3.5, ge=2.0, le=10.0)
    return_multiplier: float = Field(default=1.5, ge=1.0, le=5.0)
    return_lookback_weeks: int = Field(default=12, ge=4, le=52)
    require_positive_return: bool = True


class ExceptionConfig(BaseModel):
    """Exception framework configuration"""

    z_threshold: float = Field(ge=1.0, le=5.0)
    lookback_weeks: int = Field(ge=2, le=12)
    min_trigger_count: int = Field(ge=1, le=10)
    reentry: ExceptionReentryConfig
    strong_signal: StrongSignalConfig | None = None


class WeightingConfig(BaseModel):
    """Portfolio weighting scheme"""

    scheme: Literal["equal", "risk_parity", "inverse_vol"]
    residual_to_cash: bool = True


class FallbackConfig(BaseModel):
    """Fallback portfolio when no groups qualify"""

    enabled: bool = False
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    allocation: Literal["equal", "market_cap"] = "equal"


class PortfolioConfig(BaseModel):
    """Portfolio construction configuration"""

    max_active_groups: int = Field(ge=1, le=5)
    allow_exception: bool = True
    exception_weight_multiplier: float = Field(ge=1.0, le=3.0)
    weighting: WeightingConfig
    fallback: FallbackConfig | None = None


class StopLossRuleConfig(BaseModel):
    """Single stop-loss rule"""

    enabled: bool
    threshold: float = Field(ge=-0.50, le=0.0)


class StopLossConfig(BaseModel):
    """Stop-loss configuration"""

    frequency: Literal["daily", "intraday", "weekly"]
    absolute: StopLossRuleConfig
    trailing: StopLossRuleConfig


class CooldownConfig(BaseModel):
    """Cooldown configuration"""

    after_stop_days: int = Field(ge=1, le=60)
    block_reentry: bool = True


class StateConfig(BaseModel):
    """State persistence configuration"""

    persist_frequency: Literal["daily", "weekly", "on_rebalance"]
    format: Literal["json", "pickle"]


class AuditConfig(BaseModel):
    """Audit logging configuration"""

    enabled: bool = True
    log_level: Literal["minimal", "standard", "detailed"]


# ============================================================================
# Main Configuration Class
# ============================================================================


class AdaptiveRotationConfig(BaseModel):
    """
    Complete configuration for Adaptive Multi-Asset Rotation Strategy

    This is the main configuration class that contains all strategy parameters.
    All fields are validated using Pydantic validators.
    """

    strategy: StrategyConfig
    paths: PathsConfig
    dates: DatesConfig
    history: HistoryConfig
    benchmark: BenchmarkConfig
    asset_groups: dict[str, AssetGroupConfig]
    market_regime: MarketRegimeConfig
    fast_risk_off: FastRiskOffConfig
    group_strength: GroupStrengthConfig
    ranking: RankingConfig
    exception: ExceptionConfig
    portfolio: PortfolioConfig
    stop_loss: StopLossConfig
    cooldown: CooldownConfig
    state: StateConfig
    audit: AuditConfig

    # Cache for computed values
    _all_symbols: list[str] | None = None
    _symbol_to_group: dict[str, str] | None = None
    _config_hash: str | None = None

    @model_validator(mode="after")
    def validate_cross_field_constraints(self):
        """Validate constraints across multiple fields"""

        # Check that max_active_groups <= number of groups
        num_groups = len(self.asset_groups)
        if self.portfolio.max_active_groups > num_groups:
            msg = (
                f"max_active_groups ({self.portfolio.max_active_groups}) cannot exceed number of groups ({num_groups})"
            )
            raise ValueError(msg)

        # Check that top_n_per_group is reasonable
        for group_name, group in self.asset_groups.items():
            if self.ranking.top_n_per_group > len(group.symbols):
                msg = (
                    f"top_n_per_group ({self.ranking.top_n_per_group}) "
                    f"exceeds number of symbols in {group_name} ({len(group.symbols)})"
                )
                raise ValueError(msg)

        # Validate that cash_floor is achievable
        # Note: group_cap is per-group limit, not total allocation
        # With equal weighting, each group gets ~(1 - cash_floor) / max_active_groups
        for regime_name, regime in [
            ("risk_on", self.market_regime.slow_regime.mapping.risk_on),
            ("neutral", self.market_regime.slow_regime.mapping.neutral),
            ("risk_off", self.market_regime.slow_regime.mapping.risk_off),
        ]:
            # Cash floor should leave room for at least some equity allocation
            if regime.cash_floor >= 1.0:
                msg = f"{regime_name}: cash_floor must be < 1.0, got {regime.cash_floor}"
                raise ValueError(msg)

            # Group cap should be reasonable
            if regime.group_cap <= 0:
                msg = f"{regime_name}: group_cap must be > 0, got {regime.group_cap}"
                raise ValueError(msg)

        return self

    def get_all_symbols(self) -> list[str]:
        """
        Get flat list of all tradable symbols

        Returns:
            List of unique symbols across all groups
        """
        if self._all_symbols is None:
            all_syms = []
            for group in self.asset_groups.values():
                all_syms.extend(group.symbols)
            self._all_symbols = sorted(set(all_syms))
        return self._all_symbols

    def get_symbol_to_group_mapping(self) -> dict[str, str]:
        """
        Get mapping of symbol → group name

        Returns:
            Dict mapping each symbol to its group name

        Note:
            If a symbol appears in multiple groups (shouldn't happen
            with proper config), returns the first group found
        """
        if self._symbol_to_group is None:
            mapping = {}
            for group_name, group in self.asset_groups.items():
                for symbol in group.symbols:
                    if symbol not in mapping:
                        mapping[symbol] = group_name
            self._symbol_to_group = mapping
        return self._symbol_to_group

    def get_group_symbols(self, group_name: str) -> list[str]:
        """
        Get symbols for a specific group

        Args:
            group_name: Name of the group

        Returns:
            List of symbols in the group

        Raises:
            KeyError: If group_name not found
        """
        if group_name not in self.asset_groups:
            msg = f"Group '{group_name}' not found in configuration"
            raise KeyError(msg)
        return self.asset_groups[group_name].symbols

    def get_group_names(self) -> list[str]:
        """Get list of all group names"""
        return list(self.asset_groups.keys())

    def get_required_symbols(self) -> list[str]:
        """
        Get all symbols required for strategy execution

        Includes:
        - All tradable symbols from asset groups
        - Benchmark symbol
        - Market indices (^GSPC for SPX, ^VIX for VIX)

        Returns:
            List of all required symbols
        """
        required = self.get_all_symbols().copy()

        # Add benchmark
        if self.benchmark.excess_return_benchmark not in required:
            required.append(self.benchmark.excess_return_benchmark)

        # Add market indices
        for index in ["^GSPC", "^VIX"]:
            if index not in required:
                required.append(index)

        return sorted(required)

    def compute_config_hash(self) -> str:
        """
        Compute deterministic hash of configuration

        Used for state validation - ensures loaded state matches current config.

        Returns:
            SHA256 hash as hex string
        """
        if self._config_hash is None:
            # Convert to dict and sort keys for deterministic ordering
            config_dict = self.model_dump(mode="json")
            config_json = json.dumps(config_dict, sort_keys=True)
            self._config_hash = hashlib.sha256(config_json.encode()).hexdigest()
        return self._config_hash

    def to_dict(self) -> dict:
        """Convert config to dictionary"""
        return self.model_dump()

    def to_yaml(self, filepath: str):
        """
        Save configuration to YAML file

        Args:
            filepath: Path to save YAML file
        """
        config_dict = self.model_dump(mode="json")
        with open(filepath, "w") as f:
            yaml.safe_dump(config_dict, f, default_flow_style=False, sort_keys=False)

    def summary(self) -> str:
        """
        Generate human-readable summary of configuration

        Returns:
            Multi-line string summarizing key parameters
        """
        lines = [
            f"Strategy: {self.strategy.name} v{self.strategy.version}",
            f"Rebalance: {self.strategy.rebalance_frequency}",
            "",
            f"Asset Groups: {len(self.asset_groups)}",
        ]

        for group_name, group in self.asset_groups.items():
            lines.append(f"  - {group_name}: {len(group.symbols)} symbols")

        lines.extend(
            [
                "",
                f"Total Symbols: {len(self.get_all_symbols())}",
                f"Benchmark: {self.benchmark.excess_return_benchmark}",
                "",
                f"History Required: {self.history.minimum_history_weeks} weeks",
                f"Data Start: {self.dates.start_date}",
                "",
                f"Regime Detection: Slow ({self.market_regime.slow_regime.trend_ma_weeks}w MA) + Fast",
                f"Group Strength: {self.group_strength.lookback_weeks}w lookback",
                f"Max Active Groups: {self.portfolio.max_active_groups}",
                f"Top N per Group: {self.ranking.top_n_per_group}",
                "",
                (
                    f"Stop-Loss: Absolute={self.stop_loss.absolute.threshold:.1%}, "
                    f"Trailing={self.stop_loss.trailing.threshold:.1%}"
                ),
                f"Cooldown: {self.cooldown.after_stop_days} days",
                "",
                f"Config Hash: {self.compute_config_hash()[:16]}...",
            ]
        )

        return "\n".join(lines)


# ============================================================================
# Main Loader Function
# ============================================================================


def load_config(yaml_path: str) -> AdaptiveRotationConfig:
    """
    Load and validate configuration from YAML file

    Args:
        yaml_path: Path to YAML configuration file

    Returns:
        Validated AdaptiveRotationConfig object

    Raises:
        FileNotFoundError: If YAML file not found
        ValueError: If configuration validation fails
        yaml.YAMLError: If YAML parsing fails

    Examples:
        >>> config = load_config("AdaptiveRotationConf_v1.2.1.yaml")
        >>> print(config.strategy.name)
        adaptive_multi_asset_rotation

        >>> symbols = config.get_all_symbols()
        >>> print(f"Trading {len(symbols)} assets")
    """
    # Check file exists
    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        msg = f"Configuration file not found: {yaml_path}"
        raise FileNotFoundError(msg)

    # Load YAML
    try:
        with open(yaml_file) as f:
            config_dict = yaml.safe_load(f)
    except yaml.YAMLError as e:
        msg = f"Failed to parse YAML file {yaml_path}: {e}"
        raise yaml.YAMLError(msg)

    # Validate and create config object
    try:
        config = AdaptiveRotationConfig(**config_dict)
    except Exception as e:
        msg = f"Configuration validation failed: {e}"
        raise ValueError(msg)

    return config


def validate_config_file(yaml_path: str) -> tuple[bool, str | None]:
    """
    Validate configuration file without loading

    Useful for checking config files before running strategy.

    Args:
        yaml_path: Path to YAML configuration file

    Returns:
        (is_valid, error_message)
        - is_valid: True if valid, False otherwise
        - error_message: None if valid, error description if invalid

    Example:
        >>> is_valid, error = validate_config_file("config.yaml")
        >>> if not is_valid:
        >>>     print(f"Config error: {error}")
    """
    try:
        load_config(yaml_path)
        return True, None
    except Exception as e:
        return False, str(e)


if __name__ == "__main__":
    """Quick test of configuration loading"""

    print("Testing config_loader module...")
    print("=" * 60)

    # Find config file
    config_path = "src/strategies/AdaptiveRotationConf_v1.2.1.yaml"

    if not Path(config_path).exists():
        print(f"[ERROR] Config file not found: {config_path}")
        print("   Please run from project root or update path")
    else:
        print(f"\n[INFO] Loading config: {config_path}")

        try:
            # Load config
            config = load_config(config_path)

            print("[SUCCESS] Configuration loaded successfully!\n")

            # Print summary
            print(config.summary())

            print(f"\n{'=' * 60}")
            print("[PASS] Config loader test passed!")

        except Exception as e:
            print(f"[ERROR] Error loading config: {e}")
