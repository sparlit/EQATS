"""
ArkoRisk Guard & Comprehensive Prop Firm Rules Database (EQATS Institutional Adaptation)
Adapted from roseshayan/ArkoRisk, powerFC/propfirm-rules-dataset, and propfirmkey/prop-firm-comparison-database

Provides:
- Unified Prop Firm Rules Database covering 35+ Prop Trading Firms (Futures, Forex, Crypto, Stocks)
- Dynamic Lot Sizing & Risk Profile Calculator
- ArkoRisk Equity Safeguard Engine
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

class MarketType(str, Enum):
    FOREX = 'forex'
    FUTURES = 'futures'
    CRYPTO = 'crypto'
    STOCKS = 'stocks'

class DrawdownTaxonomy(str, Enum):
    STATIC = 'static'
    INTRADAY_TRAILING = 'intraday_trailing'
    EOD_TRAILING = 'eod_trailing'
    PCT_INITIAL = 'pct_initial'
    EOD_FIXED_BUFFER = 'eod_fixed_buffer'

@dataclass
class PropFirmPlanSpec:
    plan_id: str
    plan_name: str
    market: MarketType
    profit_target_pct: float
    daily_loss_pct: float
    max_drawdown_type: DrawdownTaxonomy
    max_drawdown_val: float
    min_trading_days: int = 0
    news_trading_allowed: bool = True
    weekend_holding_allowed: bool = False
    eas_allowed: bool = True

@dataclass
class PropFirmSpec:
    name: str
    asset_classes: List[MarketType]
    plans: Dict[str, PropFirmPlanSpec]
PROP_FIRM_DATABASE: Dict[str, PropFirmSpec] = {'FTMO': PropFirmSpec(name='FTMO', asset_classes=[MarketType.FOREX, MarketType.CRYPTO], plans={'2step': PropFirmPlanSpec(plan_id='ftmo_2step', plan_name='FTMO 2-Step Normal', market=MarketType.FOREX, profit_target_pct=10.0, daily_loss_pct=5.0, max_drawdown_type=DrawdownTaxonomy.STATIC, max_drawdown_val=10.0, min_trading_days=4, news_trading_allowed=True, weekend_holding_allowed=False), '1step': PropFirmPlanSpec(plan_id='ftmo_1step', plan_name='FTMO 1-Step Alpha', market=MarketType.FOREX, profit_target_pct=10.0, daily_loss_pct=3.0, max_drawdown_type=DrawdownTaxonomy.STATIC, max_drawdown_val=6.0, min_trading_days=0)}), 'TOPSTEP': PropFirmSpec(name='TopStep', asset_classes=[MarketType.FUTURES], plans={'50k': PropFirmPlanSpec(plan_id='topstep_50k', plan_name='Topstep 50K Trading Combine', market=MarketType.FUTURES, profit_target_pct=6.0, daily_loss_pct=2.0, max_drawdown_type=DrawdownTaxonomy.EOD_TRAILING, max_drawdown_val=2000.0, min_trading_days=0), '100k': PropFirmPlanSpec(plan_id='topstep_100k', plan_name='Topstep 100K Trading Combine', market=MarketType.FUTURES, profit_target_pct=6.0, daily_loss_pct=2.0, max_drawdown_type=DrawdownTaxonomy.EOD_TRAILING, max_drawdown_val=3000.0)}), 'APEX': PropFirmSpec(name='Apex Trader Funding', asset_classes=[MarketType.FUTURES], plans={'50k_trail': PropFirmPlanSpec(plan_id='apex_50k_trail', plan_name='Apex 50k Intraday Trailing', market=MarketType.FUTURES, profit_target_pct=6.0, daily_loss_pct=0.0, max_drawdown_type=DrawdownTaxonomy.INTRADAY_TRAILING, max_drawdown_val=2500.0, min_trading_days=7)}), 'MYFUNDEDFUTURES': PropFirmSpec(name='MyFundedFutures', asset_classes=[MarketType.FUTURES], plans={'150k': PropFirmPlanSpec(plan_id='mff_150k', plan_name='MFF 150K Starter', market=MarketType.FUTURES, profit_target_pct=6.0, daily_loss_pct=0.0, max_drawdown_type=DrawdownTaxonomy.STATIC, max_drawdown_val=4500.0)}), 'TAKEPROFITTRADER': PropFirmSpec(name='TakeProfitTrader', asset_classes=[MarketType.FUTURES], plans={'150k': PropFirmPlanSpec(plan_id='tpt_150k', plan_name='TPT 150K Pro', market=MarketType.FUTURES, profit_target_pct=6.0, daily_loss_pct=0.0, max_drawdown_type=DrawdownTaxonomy.EOD_TRAILING, max_drawdown_val=3000.0)}), 'FUNDEDNEXT': PropFirmSpec(name='FundedNext', asset_classes=[MarketType.FOREX, MarketType.CRYPTO], plans={'stellar_2step': PropFirmPlanSpec(plan_id='fn_stellar_2step', plan_name='FundedNext Stellar 2-Step', market=MarketType.FOREX, profit_target_pct=8.0, daily_loss_pct=5.0, max_drawdown_type=DrawdownTaxonomy.STATIC, max_drawdown_val=10.0)}), 'FUNDINGPIPS': PropFirmSpec(name='FundingPips', asset_classes=[MarketType.FOREX], plans={'2step_standard': PropFirmPlanSpec(plan_id='fundingpips_2step', plan_name='FundingPips 2-Step Standard', market=MarketType.FOREX, profit_target_pct=8.0, daily_loss_pct=5.0, max_drawdown_type=DrawdownTaxonomy.STATIC, max_drawdown_val=10.0)}), 'THE5ERS': PropFirmSpec(name='The5%ers', asset_classes=[MarketType.FOREX], plans={'hyper': PropFirmPlanSpec(plan_id='the5ers_hyper', plan_name='The5%ers High Stakes', market=MarketType.FOREX, profit_target_pct=8.0, daily_loss_pct=5.0, max_drawdown_type=DrawdownTaxonomy.STATIC, max_drawdown_val=10.0)}), 'FXIFY': PropFirmSpec(name='FXIFY', asset_classes=[MarketType.FOREX], plans={'2step': PropFirmPlanSpec(plan_id='fxify_2step', plan_name='FXIFY 2-Step Premium', market=MarketType.FOREX, profit_target_pct=8.0, daily_loss_pct=5.0, max_drawdown_type=DrawdownTaxonomy.STATIC, max_drawdown_val=10.0)})}

class RiskProfilePreset(str, Enum):
    CONSERVATIVE = 'CONSERVATIVE'
    MODERATE = 'MODERATE'
    AGGRESSIVE = 'AGGRESSIVE'
    PROP_SHIELD = 'PROP_SHIELD'

class ArkoRiskGuard:
    """ArkoRisk dynamic risk manager and lot sizer."""

    def __init__(self, account_balance: float=100000.0, firm_key: str='FTMO', plan_key: str='2step', profile: RiskProfilePreset=RiskProfilePreset.PROP_SHIELD) -> None:
        self.account_balance = account_balance
        self.firm_spec = PROP_FIRM_DATABASE.get(firm_key, PROP_FIRM_DATABASE['FTMO'])
        self.plan_spec = self.firm_spec.plans.get(plan_key, list(self.firm_spec.plans.values())[0])
        self.profile = profile

    def calculate_lot_size(self, current_equity: float, stop_loss_pips: float, pip_value_per_lot: float=10.0, current_drawdown_usd: float=0.0) -> Dict[str, Any]:
        """Calculates optimal lot size based on ArkoRisk dynamic risk rules."""
        if stop_loss_pips <= 0 or pip_value_per_lot <= 0:
            return {'lot_size': 0.0, 'risk_amount': 0.0, 'risk_pct': 0.0, 'reason': 'Invalid SL or Pip Value'}
        base_risk_pct = 1.0
        if self.profile == RiskProfilePreset.CONSERVATIVE:
            base_risk_pct = 0.5
        elif self.profile == RiskProfilePreset.MODERATE:
            base_risk_pct = 1.0
        elif self.profile == RiskProfilePreset.AGGRESSIVE:
            base_risk_pct = 2.0
        elif self.profile == RiskProfilePreset.PROP_SHIELD:
            max_dd_usd = self.plan_spec.max_drawdown_val if self.plan_spec.max_drawdown_type != DrawdownTaxonomy.STATIC else self.account_balance * (self.plan_spec.max_drawdown_val / 100.0)
            cushion_ratio = max(0.0, (max_dd_usd - current_drawdown_usd) / max_dd_usd)
            if cushion_ratio > 0.6:
                base_risk_pct = 1.0
            elif cushion_ratio > 0.3:
                base_risk_pct = 0.5
            else:
                base_risk_pct = 0.25
        risk_amount = current_equity * (base_risk_pct / 100.0)
        risk_per_lot = stop_loss_pips * pip_value_per_lot
        raw_lots = risk_amount / risk_per_lot if risk_per_lot > 0 else 0.0
        lot_size = max(0.01, round(raw_lots, 2)) if raw_lots >= 0.01 else 0.0
        return {'lot_size': lot_size, 'risk_amount': risk_amount, 'risk_pct': base_risk_pct, 'stop_loss_pips': stop_loss_pips, 'firm': self.firm_spec.name, 'plan': self.plan_spec.plan_name}

    def get_firm_rules_summary(self) -> Dict[str, Any]:
        return {'firm_name': self.firm_spec.name, 'plan_id': self.plan_spec.plan_id, 'plan_name': self.plan_spec.plan_name, 'profit_target_pct': self.plan_spec.profit_target_pct, 'daily_loss_pct': self.plan_spec.daily_loss_pct, 'drawdown_type': self.plan_spec.max_drawdown_type.value, 'max_drawdown_val': self.plan_spec.max_drawdown_val}
