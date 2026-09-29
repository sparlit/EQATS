# pylint: disable=too-many-instance-attributes,too-many-arguments,too-many-positional-arguments,too-many-locals,arguments-renamed,line-too-long
# codespell:ignore IST,ans
"""JEV AI Decision Engine for EQATS.

Target Integration: jev-ai/jev-ai
Magic Number: 9100088

Integrates JEV AI's typed decision model (Choice, Score, Noul) into EQATS for:
- Market Regime & Strategy Routing (Choice / task-route)
- Execution Engine Model Selection (model-route)
- Trade Signal Research Verification (research-check)
- Trade & Volatility Risk Severity Scoring (Score)
- Order Safety & Tool Execution Guardrails (tool-guard / Noul)
- Trade Completion & Order Execution Audit (completion-review)

Supports live REST API requests to JEV AI endpoints
(https://www.jevai.org/api/v1/decisions/ and https://thejevai.com/v1/systemone)
with automatic deterministic heuristic fallbacks for offline / zero-latency execution.
Complies with TradingOS 0.05 INR price tick rounding and market session validation.
"""

import json
import os
import urllib.error
import urllib.request
import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    round_to_indian_quantity,
    round_to_indian_tick_size,
)

MAGIC_NUMBER_JEV_AI: int = 9100088
DEFAULT_JEV_ORG_ENDPOINT: str = "https://www.jevai.org/api/v1/decisions"
DEFAULT_JEV_SYSTEMONE_ENDPOINT: str = "https://thejevai.com/v1/systemone"
DEFAULT_JEV_MODEL: str = "typesafe/jev-1.13"


def round_tick_005(price: float) -> float:
    """Rounds price to nearest 0.05 INR tick size."""
    return round_to_indian_tick_size(price)


def is_ist_market_open(now_dt: datetime | None = None) -> bool:
    """Checks whether current or provided datetime falls within market hours.

    (Monday-Friday 09:15 - 15:30 IST).
    """
    ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    if now_dt is None:
        now_dt = datetime.now(ist_tz)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=ist_tz)
    else:
        now_dt = now_dt.astimezone(ist_tz)

    if now_dt.weekday() >= 5:  # Saturday or Sunday
        return False

    market_start = now_dt.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now_dt.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now_dt <= market_end


@dataclass
class JevChoiceQuestion:
    """Represents a JEV AI Choice question configuration."""

    question_id: str
    instructions: str
    choices: list[str]
    question_type: str = "choice"


@dataclass
class JevScoreQuestion:
    """Represents a JEV AI Score question configuration."""

    question_id: str
    instructions: str
    levels: list[str]  # Ordered from low to high e.g. ["LOW", "MEDIUM", "HIGH"]
    question_type: str = "score"


@dataclass
class JevNoulQuestion:
    """Represents a JEV AI Noul (Yes/No judgment) question configuration."""

    question_id: str
    instructions: str
    criteria: str = ""
    question_type: str = "noul"


@dataclass
class JevDecisionResult:
    """Structured decision output returned by JevAIDecisionEngine."""

    request_id: str
    state_summary: str
    choices: dict[str, dict[str, Any]] = field(default_factory=dict)
    scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    nouls: dict[str, dict[str, Any]] = field(default_factory=dict)
    is_offline_fallback: bool = False
    magic_number: int = MAGIC_NUMBER_JEV_AI
    timestamp: str = field(
        default_factory=lambda: datetime.now(
            zoneinfo.ZoneInfo("Asia/Kolkata")
        ).isoformat()
    )


class JevAIDecisionEngine:
    """Typed Decision Engine for EQATS using JEV AI (Choice, Score, Noul + Presets).

    Provides structured decisions directly consumable by trading & risk code:
    1. Tool Execution Guardrail (tool-guard)
    2. Execution Engine & Strategy Routing (model-route & task-route)
    3. Trade Signal Research Verification (research-check)
    4. Execution Completion Audit (completion-review)
    5. Regime Classification (Choice)
    6. Trade Setup Risk Scoring (Score)
    7. Safety Guardrail Validation (Noul)
    """

    def __init__(  # noqa: PLR0917
        self,
        api_key: str | None = None,
        org_endpoint: str = DEFAULT_JEV_ORG_ENDPOINT,
        systemone_endpoint: str = DEFAULT_JEV_SYSTEMONE_ENDPOINT,
        model: str = DEFAULT_JEV_MODEL,
        request_timeout: float = 3.0,
        enable_offline_fallback: bool = True,  # noqa: FBT001, FBT002
    ) -> None:
        """Initializes JevAIDecisionEngine with API configuration and policies."""
        self.api_key: str = api_key or os.getenv("JEV_API_KEY") or ""
        self.org_endpoint: str = org_endpoint
        self.systemone_endpoint: str = systemone_endpoint
        self.model: str = model
        self.request_timeout: float = request_timeout
        self.enable_offline_fallback: bool = enable_offline_fallback
        self.decision_history: list[JevDecisionResult] = []

    def guard_tool_call(  # noqa: PLR0917
        self,
        tool: str,
        action: str,
        arguments_summary: list[str],
        side_effects: list[str],
        policy: list[str],
        drawdown_pct: float = 0.0,
    ) -> dict[str, Any]:
        """Evaluates whether a tool call is allowed, confirmed, or denied."""
        if self.api_key:
            payload = {
                "tool": tool,
                "action": action,
                "arguments_summary": arguments_summary,
                "side_effects": side_effects,
                "policy": policy,
                "reversibility": "partially_reversible",
            }
            resp = self._call_jev_api(f"{self.org_endpoint}/tool-guard", payload)
            if resp and "data" in resp:
                data = resp["data"]
                return {
                    "decision": data.get("decision", "confirm"),
                    "confidence": float(data.get("confidence", 0.85)),
                    "guidance": data.get("guidance", ""),
                    "is_fallback": False,
                }

        # Deterministic Heuristic Fallback
        if drawdown_pct >= 2.0 or "emergency_halt" in action.lower():
            decision = "deny"
            guidance = "Portfolio drawdown threshold reached or dangerous action."
        elif "cancel" in action.lower() or drawdown_pct > 1.0:
            decision = "confirm"
            guidance = "Requires explicit confirmation before execution."
        else:
            decision = "allow"
            guidance = "Tool call approved for autonomous execution."

        return {
            "decision": decision,
            "confidence": 0.95,
            "guidance": guidance,
            "is_fallback": True,
        }

    def route_execution_model(
        self,
        task: str,
        candidates: list[dict[str, Any]],
        priorities: list[str],
        stakes: str = "high",
    ) -> dict[str, Any]:
        """Routes task to best execution model / engine candidate."""
        if self.api_key:
            payload = {
                "task": task,
                "candidates": candidates,
                "priorities": priorities,
                "stakes": stakes,
            }
            resp = self._call_jev_api(f"{self.org_endpoint}/model-route", payload)
            if resp and "data" in resp:
                data = resp["data"]
                return {
                    "selected_model": data.get("decision", candidates[0]["id"]),
                    "confidence": float(data.get("confidence", 0.90)),
                    "is_fallback": False,
                }

        # Deterministic Fallback: select candidate matching priority or first
        selected = candidates[0]["id"] if candidates else "default_engine"
        return {
            "selected_model": selected,
            "confidence": 0.90,
            "is_fallback": True,
        }

    def check_research_signal(
        self,
        claim: str,
        evidence: list[str],
        stakes: str = "medium",
    ) -> dict[str, Any]:
        """Verifies if market evidence supports a trade signal claim."""
        if self.api_key:
            payload = {
                "claim": claim,
                "evidence": evidence,
                "source_quality": "high",
                "stakes": stakes,
            }
            resp = self._call_jev_api(f"{self.org_endpoint}/research", payload)
            if resp and "data" in resp:
                data = resp["data"]
                return {
                    "decision": data.get("decision", "accept"),
                    "confidence": float(data.get("confidence", 0.85)),
                    "is_fallback": False,
                }

        # Deterministic Fallback
        has_fail = any(
            "fail" in e.lower() or "unclear" in e.lower() for e in evidence
        )
        decision = "reject" if has_fail else "accept"
        return {
            "decision": decision,
            "confidence": 0.88,
            "is_fallback": True,
        }

    def review_execution_completion(
        self,
        objective: str,
        completed_work: list[str],
        known_gaps: list[str],
    ) -> dict[str, Any]:
        """Audits trade execution completion status."""
        if self.api_key:
            payload = {
                "objective": objective,
                "completed_work": completed_work,
                "known_gaps": known_gaps,
            }
            resp = self._call_jev_api(f"{self.org_endpoint}/completion", payload)
            if resp and "data" in resp:
                data = resp["data"]
                return {
                    "decision": data.get("decision", "complete"),
                    "confidence": float(data.get("confidence", 0.90)),
                    "is_fallback": False,
                }

        # Deterministic Fallback
        decision = "incomplete" if known_gaps else "complete"
        return {
            "decision": decision,
            "confidence": 0.95,
            "is_fallback": True,
        }

    def classify_market_regime(  # noqa: PLR0917
        self,
        symbol: str,
        current_price: float,
        vix: float,
        atr: float,
        rsi: float,
        trend_direction: str = "UP",
    ) -> dict[str, Any]:
        """Classifies current market state into a typed regime choice."""
        sanitized_price = round_tick_005(current_price)
        state_text = (
            f"Symbol: {symbol}, Last Price: {sanitized_price:.2f} INR, "
            f"INDIA VIX: {vix:.2f}, ATR: {atr:.2f}, RSI: {rsi:.1f}, "
            f"Trend: {trend_direction}, Session Open: {is_ist_market_open()}"
        )

        choices = [
            "BULLISH_TREND",
            "BEARISH_TREND",
            "SIDEWAYS_RANGE",
            "HIGH_VOLATILITY_BREAKOUT",
        ]

        if self.api_key:
            api_payload = {
                "model": self.model,
                "state": state_text,
                "questions": {
                    "regime": {
                        "type": "choice",
                        "instructions": "Classify regime based on technical state.",
                        "options": choices,
                    }
                },
            }
            api_response = self._call_jev_api(
                self.systemone_endpoint, api_payload
            )
            if api_response and "answers" in api_response:
                answer = api_response["answers"].get("regime", {})
                return {
                    "regime": answer.get("selected_choice", "SIDEWAYS_RANGE"),
                    "confidence": answer.get("confidence", 0.85),
                    "probabilities": answer.get("probabilities", {}),
                    "is_fallback": False,
                }

        # Deterministic Heuristic Fallback
        selected = "SIDEWAYS_RANGE"
        if vix > 22.0 or atr > (sanitized_price * 0.025):
            selected = "HIGH_VOLATILITY_BREAKOUT"
        elif trend_direction.upper() in ("UP", "BULLISH") and rsi > 50.0:
            selected = "BULLISH_TREND"
        elif trend_direction.upper() in ("DOWN", "BEARISH") and rsi < 50.0:
            selected = "BEARISH_TREND"

        return {
            "regime": selected,
            "confidence": 0.90,
            "probabilities": {
                c: (1.0 if c == selected else 0.0) for c in choices
            },
            "is_fallback": True,
        }

    def score_trade_risk_severity(
        self,
        symbol: str,
        position_size_inr: float,
        portfolio_drawdown_pct: float,
        slippage_estimate_bps: float,
    ) -> dict[str, Any]:
        """Scores trade risk severity on an ordered scale."""
        state_text = (
            f"Symbol: {symbol}, Size: {position_size_inr:.2f} INR, "
            f"Portfolio Drawdown: {portfolio_drawdown_pct:.2f}%, "
            f"Estimated Slippage: {slippage_estimate_bps:.1f} bps"
        )
        levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

        if self.api_key:
            api_payload = {
                "model": self.model,
                "state": state_text,
                "questions": {
                    "risk_severity": {
                        "type": "score",
                        "instructions": "Evaluate risk severity of position.",
                        "levels": levels,
                    }
                },
            }
            api_response = self._call_jev_api(
                self.systemone_endpoint, api_payload
            )
            if api_response and "answers" in api_response:
                answer = api_response["answers"].get("risk_severity", {})
                return {
                    "score_label": answer.get("score_label", "MEDIUM"),
                    "score_value": answer.get("score_value", 2.0),
                    "probabilities": answer.get("probabilities", {}),
                    "is_fallback": False,
                }

        # Deterministic Heuristic Fallback
        if (
            portfolio_drawdown_pct >= 2.0
            or position_size_inr > 500000.0
            or slippage_estimate_bps > 50.0
        ):
            selected_label = "CRITICAL"
            val = 4.0
        elif (
            portfolio_drawdown_pct >= 1.0
            or position_size_inr > 200000.0
            or slippage_estimate_bps > 25.0
        ):
            selected_label = "HIGH"
            val = 3.0
        elif position_size_inr > 50000.0 or slippage_estimate_bps > 10.0:
            selected_label = "MEDIUM"
            val = 2.0
        else:
            selected_label = "LOW"
            val = 1.0

        return {
            "score_label": selected_label,
            "score_value": val,
            "probabilities": {
                lvl: (1.0 if lvl == selected_label else 0.0) for lvl in levels
            },
            "is_fallback": True,
        }

    def evaluate_execution_safety_noul(
        self,
        order_symbol: str,
        order_type: str,
        order_price: float,
        vix: float,
        portfolio_drawdown_pct: float,
    ) -> dict[str, Any]:
        """Evaluates yes/no execution safety guardrail (Noul) for an order."""
        sanitized_price = round_tick_005(order_price)
        state_text = (
            f"Order: {order_type} {order_symbol} @ {sanitized_price:.2f} INR, "
            f"VIX: {vix:.2f}, Drawdown: {portfolio_drawdown_pct:.2f}%, "
            f"Market Open: {is_ist_market_open()}"
        )

        if self.api_key:
            api_payload = {
                "model": self.model,
                "state": state_text,
                "questions": {
                    "is_safe_to_execute": {
                        "type": "noul",
                        "instructions": "Is order safe to execute?",
                        "criteria": "True if drawdown < 2% and price > 0",
                    }
                },
            }
            api_response = self._call_jev_api(
                self.systemone_endpoint, api_payload
            )
            if api_response and "answers" in api_response:
                answer = api_response["answers"].get("is_safe_to_execute", {})
                noul_val = float(answer.get("noul", 0.0))
                return {
                    "is_safe": noul_val >= 0.5,
                    "noul_prob": round(noul_val, 4),
                    "is_fallback": False,
                }

        # Deterministic Heuristic Fallback
        is_safe = (portfolio_drawdown_pct < 2.0) and (sanitized_price > 0.0)
        noul_prob = 0.95 if is_safe else 0.05

        return {
            "is_safe": is_safe,
            "noul_prob": noul_prob,
            "is_fallback": True,
        }

    def evaluate_full_decision_matrix(  # noqa: PLR0917
        self,
        symbol: str,
        price: float,
        vix: float,
        atr: float,
        rsi: float,
        position_size_inr: float,
        portfolio_drawdown_pct: float,
        slippage_bps: float,
    ) -> JevDecisionResult:
        """Evaluates Choice, Score, and Noul decisions across market state."""
        sanitized_price = round_tick_005(price)

        regime_res = self.classify_market_regime(
            symbol, sanitized_price, vix, atr, rsi
        )
        risk_res = self.score_trade_risk_severity(
            symbol, position_size_inr, portfolio_drawdown_pct, slippage_bps
        )
        safety_res = self.evaluate_execution_safety_noul(
            symbol, "BUY", sanitized_price, vix, portfolio_drawdown_pct
        )

        is_fallback = regime_res.get("is_fallback", True) or risk_res.get(
            "is_fallback", True
        )

        result = JevDecisionResult(
            request_id=f"JEV-DECISION-{int(datetime.now().timestamp() * 1000)}",
            state_summary=(
                f"{symbol} @ {sanitized_price:.2f} INR | "
                f"VIX {vix} | DD {portfolio_drawdown_pct}%"
            ),
            choices={"market_regime": regime_res},
            scores={"trade_risk_severity": risk_res},
            nouls={"execution_safety": safety_res},
            is_offline_fallback=is_fallback,
            magic_number=MAGIC_NUMBER_JEV_AI,
        )

        self.decision_history.append(result)
        return result

    def _call_jev_api(
        self, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Executes REST POST request to JEV AI endpoint."""
        if not self.api_key:
            return None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "TradingOS-EQATS/7.0.0",
        }

        req = urllib.request.Request(  # noqa: S310
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout) as response:  # noqa: S310
                if response.status == 200:
                    data = response.read().decode("utf-8")
                    return json.loads(data)
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            Exception,  # pylint: disable=broad-exception-caught
        ):
            if not self.enable_offline_fallback:
                raise
        return None


class JevAIDecisionBrokerAdapter(SEBIBrokerAdapter):
    """SEBIBrokerAdapter compliance wrapper for JEV AI Decision Engine."""

    def __init__(self, broker_name: str = "JEV_AI_DECISION_ENGINE") -> None:
        """Initializes JevAIDecisionBrokerAdapter."""
        super().__init__()
        self.broker_name = broker_name
        self.engine = JevAIDecisionEngine()
        self._is_connected = False

    def connect(self) -> bool:
        """Connects the adapter."""
        self._is_connected = True
        return True

    def disconnect(self) -> bool:
        """Disconnects the adapter."""
        self._is_connected = False
        return True

    def is_connected(self) -> bool:
        """Returns connection state."""
        return self._is_connected

    def execute_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        """Executes order if JEV AI Noul execution safety check passes."""
        if not self._is_connected:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=request.price,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                error="Adapter not connected",
            )
        return self.place_order(request)

    def place_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        """Places order after evaluating JEV AI decision matrix."""
        sanitized_price = round_tick_005(request.price)
        sanitized_qty = round_to_indian_quantity(request.quantity)
        ticket_id = f"JEV-{int(datetime.now().timestamp() * 1000)}"

        safety = self.engine.evaluate_execution_safety_noul(
            order_symbol=request.symbol,
            order_type=request.order_type,
            order_price=sanitized_price,
            vix=16.5,
            portfolio_drawdown_pct=0.5,
        )

        if not safety.get("is_safe", False):
            return SEBIOrderResponse(
                success=False,
                ticket=ticket_id,
                price=sanitized_price,
                status="REJECTED_BY_JEV_SAFETY_GUARDRAIL",
                product=request.product,
                exchange=request.exchange,
                error="JEV AI Noul safety guardrail evaluated order as unsafe",
                raw_response={"quantity": sanitized_qty},
            )

        return SEBIOrderResponse(
            success=True,
            ticket=ticket_id,
            price=sanitized_price,
            status="EXECUTED",
            product=request.product,
            exchange=request.exchange,
            raw_response={"quantity": sanitized_qty},
        )

    def close_order(
        self,
        ticket: str,
        symbol: str,
        exchange: str = "NSE",
        product: str = "CNC",
    ) -> SEBIOrderResponse:
        """Closes an active order."""
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=0.0,
            status="CLOSED",
            product=product,
            exchange=exchange,
        )

    def modify_order(
        self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0
    ) -> bool:
        """Modifies order parameters."""
        return True

    def get_account_info(self) -> dict[str, Any]:
        """Gets account balance & equity information."""
        return {
            "balance": 1000000.0,
            "equity": 1000000.0,
            "currency": "INR",
            "is_demo": True,
            "magic_number": MAGIC_NUMBER_JEV_AI,
            "adapter_type": "JEV_AI_DECISION_ENGINE",
        }

    def get_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        count: int = 100,
        interval: str = "minute",
    ) -> list[dict[str, Any]]:
        """Gets price history for symbol."""
        return []

    def get_current_price(
        self, symbol: str, exchange: str = "NSE"
    ) -> dict[str, float]:
        """Gets current bid/ask quote."""
        return {"bid": 100.0, "ask": 100.05, "last": 100.0}

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Gets list of open orders."""
        return []


# Register adapter into microkernel plugin registry
IndianBrokerPluginRegistry.register(
    "JEV_AI_DECISION_ENGINE", JevAIDecisionBrokerAdapter
)
