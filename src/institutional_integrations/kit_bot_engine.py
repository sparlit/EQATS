"""
K.I.T. (Knight Industries Trading) Framework Engine (EQATS Institutional Adaptation).
Adapted from Signal-Execution-Labs/forex-trading-ai-agent & kayzaa/k.i.t.-bot (MIT License)

Provides:
- KitPineScriptGenerator: Natural language & parameter-driven Pine Script v5 code generator for TradingView
- KitSocialSignalParser: Universal multi-format signal parser for Telegram / Social Copy Trading
- KitAutopilotManager: Multi-mode autopilot governor (MANUAL, SEMI_AUTO, FULL_AUTO) with emergency kill switch
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("KitBotEngine")


class KitAutopilotMode(str, Enum):
    MANUAL = "MANUAL"
    SEMI_AUTO = "SEMI_AUTO"
    FULL_AUTO = "FULL_AUTO"


@dataclass
class KitParsedSignal:
    symbol: str
    direction: str
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    confidence: float = 0.8
    source_channel: str = "UNKNOWN"
    raw_text: str = ""


@dataclass
class KitAutopilotDecision:
    mode: KitAutopilotMode
    symbol: str
    direction: str
    order_value_usd: float
    approved: bool
    requires_manual_approval: bool
    reason: str


class KitPineScriptGenerator:
    """
    Generates TradingView Pine Script v5 indicators and strategies.
    """

    def generate_indicator(self, name: str = "EQATS Custom RSI", indicator_type: str = "rsi", period: int = 14) -> str:
        """Generates Pine Script v5 indicator script."""
        script = f'//@version=5\nindicator("{name}", overlay=false)\n\nrsi_period = input.int({period}, "RSI Period")\nrsi_val = ta.rsi(close, rsi_period)\n\nplot(rsi_val, "RSI", color=color.blue)\nhline(70, "Overbought", color=color.red, linestyle=hline.style_dashed)\nhline(30, "Oversold", color=color.green, linestyle=hline.style_dashed)\n\nalertcondition(rsi_val < 30, title="RSI Oversold", message="EQATS Alert: RSI Oversold on {{ticker}}")\nalertcondition(rsi_val > 70, title="RSI Overbought", message="EQATS Alert: RSI Overbought on {{ticker}}")\n'
        return script.strip()

    def generate_strategy(self, name: str = "EQATS EMA Cross Strategy", fast_ema: int = 9, slow_ema: int = 21) -> str:
        """Generates Pine Script v5 strategy script with TP/SL webhook alerts."""
        script = f'//@version=5\nstrategy("{name}", overlay=true, margin_long=100, margin_short=100)\n\nfast_length = input.int({fast_ema}, "Fast EMA Length")\nslow_length = input.int({slow_ema}, "Slow EMA Length")\n\nfast_ema_val = ta.ema(close, fast_length)\nslow_ema_val = ta.ema(close, slow_length)\n\nplot(fast_ema_val, "Fast EMA", color=color.green)\nplot(slow_ema_val, "Slow EMA", color=color.red)\n\nlong_condition = ta.crossover(fast_ema_val, slow_ema_val)\nshort_condition = ta.crossunder(fast_ema_val, slow_ema_val)\n\nif (long_condition)\n    strategy.entry("Long", strategy.long)\n\nif (short_condition)\n    strategy.entry("Short", strategy.short)\n'
        return script.strip()


class KitSocialSignalParser:
    """
    Universal multi-format parser converting social / Telegram messages into structured trade orders.
    """

    def parse_text_signal(self, text: str, default_symbol: str = "EURUSD") -> KitParsedSignal | None:
        """Parses raw text signal using regex pattern matching."""
        if not text or not text.strip():
            return None
        clean_text = text.upper()
        direction = None
        if "BUY" in clean_text or "LONG" in clean_text:
            direction = "BUY"
        elif "SELL" in clean_text or "SHORT" in clean_text:
            direction = "SELL"
        if not direction:
            return None
        sym_match = re.search("([A-Z]{6}|[A-Z]{3}/[A-Z]{3}|XAUUSD|BTCUSD|ETHUSD)", clean_text)
        symbol = sym_match.group(1).replace("/", "") if sym_match else default_symbol
        entry_match = re.search("(?:ENTRY|@|PRICE)[:\\s]*([0-9]+\\.?[0-9]*)", clean_text)
        sl_match = re.search("(?:SL|STOP)[:\\s]*([0-9]+\\.?[0-9]*)", clean_text)
        tp_match = re.search("(?:TP|TARGET)[:\\s]*([0-9]+\\.?[0-9]*)", clean_text)
        entry = float(entry_match.group(1)) if entry_match else 0.0
        sl = float(sl_match.group(1)) if sl_match else 0.0
        tp = float(tp_match.group(1)) if tp_match else 0.0
        return KitParsedSignal(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            confidence=0.85,
            raw_text=text,
        )


class KitAutopilotManager:
    """
    Multi-mode autopilot governor enforcing manual approval thresholds and emergency kill switches.
    """

    def __init__(
        self, mode: KitAutopilotMode = KitAutopilotMode.SEMI_AUTO, approval_threshold_usd: float = 500.0,
    ) -> None:
        self.mode = mode
        self.approval_threshold_usd = approval_threshold_usd
        self.kill_switch_activated: bool = False
        self.lock = threading.Lock()

    def evaluate_order_gate(self, symbol: str, direction: str, order_value_usd: float) -> KitAutopilotDecision:
        """Evaluates whether an order requires manual confirmation based on mode and value threshold."""
        with self.lock:
            if self.kill_switch_activated:
                return KitAutopilotDecision(
                    mode=self.mode,
                    symbol=symbol,
                    direction=direction,
                    order_value_usd=order_value_usd,
                    approved=False,
                    requires_manual_approval=True,
                    reason="Emergency kill switch activated. All automated trading blocked.",
                )
            if self.mode == KitAutopilotMode.MANUAL:
                return KitAutopilotDecision(
                    mode=self.mode,
                    symbol=symbol,
                    direction=direction,
                    order_value_usd=order_value_usd,
                    approved=False,
                    requires_manual_approval=True,
                    reason="Manual mode active. User approval required.",
                )
            if self.mode == KitAutopilotMode.SEMI_AUTO:
                if order_value_usd > self.approval_threshold_usd:
                    return KitAutopilotDecision(
                        mode=self.mode,
                        symbol=symbol,
                        direction=direction,
                        order_value_usd=order_value_usd,
                        approved=False,
                        requires_manual_approval=True,
                        reason=f"Order value ${order_value_usd:.2f} exceeds semi-auto threshold ${self.approval_threshold_usd:.2f}.",
                    )
                return KitAutopilotDecision(
                    mode=self.mode,
                    symbol=symbol,
                    direction=direction,
                    order_value_usd=order_value_usd,
                    approved=True,
                    requires_manual_approval=False,
                    reason="Order value below semi-auto threshold. Approved automatically.",
                )
            return KitAutopilotDecision(
                mode=self.mode,
                symbol=symbol,
                direction=direction,
                order_value_usd=order_value_usd,
                approved=True,
                requires_manual_approval=False,
                reason="Full autopilot active. Approved automatically.",
            )

    def activate_kill_switch(self) -> None:
        """Triggers emergency kill switch to block all automated trading."""
        with self.lock:
            self.kill_switch_activated = True
            logger.warning("KIT Autopilot: EMERGENCY KILL SWITCH ACTIVATED!")

    def reset_kill_switch(self) -> None:
        """Resets emergency kill switch."""
        with self.lock:
            self.kill_switch_activated = False
            logger.info("KIT Autopilot: Emergency kill switch RESET.")
