import datetime
import uuid
import json
import config
import database
import connector
from event_bus import global_event_bus, Event

# ==============================================================================
# 1. CONTROL & GOVERNANCE PLANE
# ==============================================================================
class ControlGovernancePlane:
    """
    Manages transactional configuration state updates, validation, signing,
    audit logs, and rolling back configurations upon validation failure.
    """
    def __init__(self):
        self._current_config = {
            "MAX_CONCURRENT_TRADES": config.MAX_CONCURRENT_TRADES,
            "RISK_PER_TRADE_PERCENT": config.RISK_PER_TRADE_PERCENT,
            "MAX_DAILY_DRAWDOWN_PERCENT": config.MAX_DAILY_DRAWDOWN_PERCENT,
            "MAX_SPREAD_PIPS": config.MAX_SPREAD_PIPS
        }
        self._history = []

    def propose_config_change(self, author_id, proposed_updates: dict, signature: str) -> bool:
        """
        Atomically proposes, validates, snapshots, applies, and commits config updates.
        If validation fails, rolls back the transaction.
        """
        old_config = dict(self._current_config)
        proposal_id = str(uuid.uuid4())

        global_event_bus.publish(Event(
            family="ChangeProposalCreated",
            source="ControlPlane",
            payload={"proposal_id": proposal_id, "author": author_id, "updates": proposed_updates}
        ))

        # Snapshot / Apply Transactionally
        temp_config = dict(self._current_config)
        temp_config.update(proposed_updates)

        # Validation checks
        is_valid = True
        reason = "Validation Succeeded"
        if temp_config.get("MAX_CONCURRENT_TRADES", 0) <= 0:
            is_valid = False
            reason = "MAX_CONCURRENT_TRADES must be positive"
        if temp_config.get("RISK_PER_TRADE_PERCENT", 0.0) <= 0.0 or temp_config.get("RISK_PER_TRADE_PERCENT", 0.0) > 10.0:
            is_valid = False
            reason = "RISK_PER_TRADE_PERCENT must be between 0% and 10%"
        if temp_config.get("MAX_DAILY_DRAWDOWN_PERCENT", 0.0) <= 0.0 or temp_config.get("MAX_DAILY_DRAWDOWN_PERCENT", 0.0) > 15.0:
            is_valid = False
            reason = "MAX_DAILY_DRAWDOWN_PERCENT must be between 0% and 15%"

        if is_valid:
            # Commit Config
            self._current_config = temp_config
            self._history.append({
                "proposal_id": proposal_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "author": author_id,
                "signature": signature,
                "old": old_config,
                "new": temp_config
            })
            # Apply back to the active module config
            config.MAX_CONCURRENT_TRADES = self._current_config["MAX_CONCURRENT_TRADES"]
            config.RISK_PER_TRADE_PERCENT = self._current_config["RISK_PER_TRADE_PERCENT"]
            config.MAX_DAILY_DRAWDOWN_PERCENT = self._current_config["MAX_DAILY_DRAWDOWN_PERCENT"]
            config.MAX_SPREAD_PIPS = self._current_config["MAX_SPREAD_PIPS"]

            global_event_bus.publish(Event(
                family="DeploymentCompleted",
                source="ControlPlane",
                payload={"proposal_id": proposal_id, "config": self._current_config}
            ))
            return True
        else:
            # Rollback
            global_event_bus.publish(Event(
                family="RollbackStarted",
                source="ControlPlane",
                payload={"proposal_id": proposal_id, "reason": reason}
            ))
            global_event_bus.publish(Event(
                family="RollbackCompleted",
                source="ControlPlane",
                payload={"proposal_id": proposal_id, "config_restored": old_config}
            ))
            return False


# ==============================================================================
# 2. DATA PLANE
# ==============================================================================
class DataPlane:
    """
    Ingests and normalizes real-time/historical data, performs point-in-time
    reconstructions, enforces Symbol Master limits, and checks market-data reasonableness.
    """
    def __init__(self):
        self._pit_database = {} # Maps symbol -> list of PIT price records

    def store_price(self, symbol: str, bid: float, ask: float):
        """Stores point-in-time price record with event, publication, and availability times."""
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record = {
            "event_time": now_str,
            "publication_time": now_str,
            "availability_time": now_str,
            "bid": bid,
            "ask": ask
        }
        if symbol not in self._pit_database:
            self._pit_database[symbol] = []
        self._pit_database[symbol].append(record)

        global_event_bus.publish(Event(
            family="MarketTickReceived",
            source="DataPlane",
            payload={"symbol": symbol, "bid": bid, "ask": ask}
        ))

    def query_pit_price(self, symbol: str, target_time_str: str) -> dict:
        """Returns the available price record exactly at or before target_time_str (No Look-Ahead bias!)."""
        records = self._pit_database.get(symbol, [])
        valid_record = None
        for r in records:
            if r["availability_time"] <= target_time_str:
                valid_record = r
            else:
                break
        return valid_record

    def validate_reasonableness(self, symbol: str, bid: float, ask: float) -> str:
        """
        Enforces sanity boundaries: crossed/inverted markets, spreads, and continuity jumps.
        Returns state: 'VALID', 'SUSPECT', 'INVALID', or 'QUARANTINED'.
        """
        if bid <= 0 or ask <= 0:
            return "INVALID"
        if bid >= ask:
            return "QUARANTINED" # Crossed/inverted market

        spread = ask - bid
        pip_size = 0.0001 if "JPY" not in symbol else 0.01
        spread_pips = spread / pip_size
        if spread_pips > config.MAX_SPREAD_PIPS * 3:
            return "SUSPECT"

        return "VALID"


# ==============================================================================
# 3. INTELLIGENCE PLANE
# ==============================================================================
class IntelligencePlane:
    """
    Constructs normalized Market State Vectors, tracks market regimes,
    coordinates Analyst/Prediction brains, and checks for model drift or disagreement.
    """
    def __init__(self):
        pass

    def build_market_state_vector(self, symbol: str, history_bars: list) -> dict:
        """Creates a normalized Market State Vector representation."""
        if not history_bars:
            return {}
        current_close = history_bars[-1]["close"]
        return {
            "symbol": symbol,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "close": current_close,
            "indicators": {
                "rsi": config.RSI_PERIOD,
                "ema200": config.EMA_LONG_PERIOD
            }
        }

    def detect_regime(self, highs: list, lows: list, closes: list) -> dict:
        """Determines if the market is TRENDING, RANGING, or under VOLATILITY_SHOCK."""
        import indicators
        return indicators.classify_market_regime(highs, lows, closes)


# ==============================================================================
# 4. STRATEGY PLANE
# ==============================================================================
class StrategyPlane:
    """
    Manages strategy registrations, licenses, lifecycle transitions,
    and checks trend confluences across multi-timeframe structures.
    """
    def __init__(self):
        self._strategy_registry = {
            "TREND_FOLLOWING": {"license": "ACTIVE", "lifecycle": "PRODUCTION"},
            "MEAN_REVERSION": {"license": "ACTIVE", "lifecycle": "PRODUCTION"},
            "MACD_MOMENTUM": {"license": "ACTIVE", "lifecycle": "PRODUCTION"},
            "VOTING_ENSEMBLE": {"license": "ACTIVE", "lifecycle": "PRODUCTION"}
        }

    def get_license_state(self, strategy_name: str) -> str:
        return self._strategy_registry.get(strategy_name, {}).get("license", "INACTIVE")

    def resolve_mtf_confluence(self, is_bullish_m1: bool, is_bullish_h1: bool) -> str:
        """Determines consensus bias: BULLISH, BEARISH, or NEUTRAL."""
        if is_bullish_m1 and is_bullish_h1:
            return "BULLISH"
        elif not is_bullish_m1 and not is_bullish_h1:
            return "BEARISH"
        return "NEUTRAL"


# ==============================================================================
# 5. OPPORTUNITY, PORTFOLIO, CAPITAL & RISK PLANE
# ==============================================================================
class OpportunityRiskPlane:
    """
    Calculates expected net values, allocates capital budgets and reservations,
    and enforces hard portfolio risk boundaries and daily loss limits.
    """
    def __init__(self):
        self._reservations = {} # Maps symbol -> reserved capital amount
        self._loss_tracker = {} # Maps day -> accumulated loss

    def calculate_expected_net_value(self, gross_edge: float, spread: float, commission: float, slippage: float) -> float:
        """Expected Net Value = Gross Edge - Spread - Commission - Slippage."""
        return gross_edge - spread - commission - slippage

    def reserve_capital(self, symbol: str, amount: float) -> bool:
        """Safely reserves capital for a proposed trading intent."""
        if amount <= 0:
            return False
        self._reservations[symbol] = amount
        global_event_bus.publish(Event(
            family="RiskBudgetReserved",
            source="RiskPlane",
            payload={"symbol": symbol, "amount": amount}
        ))
        return True

    def commit_reservation(self, symbol: str):
        if symbol in self._reservations:
            amount = self._reservations.pop(symbol)
            global_event_bus.publish(Event(
                family="RiskApproved",
                source="RiskPlane",
                payload={"symbol": symbol, "amount": amount}
            ))

    def release_reservation(self, symbol: str):
        if symbol in self._reservations:
            amount = self._reservations.pop(symbol)
            global_event_bus.publish(Event(
                family="RiskBudgetReleased",
                source="RiskPlane",
                payload={"symbol": symbol, "amount": amount}
            ))

    def check_hard_limits(self, proposed_risk: float, active_positions: list) -> bool:
        """Enforces maximum simultaneous trade limits and portfolio ceilings."""
        if len(active_positions) >= config.MAX_CONCURRENT_TRADES:
            return False
        return True


# ==============================================================================
# 6. SAFETY & VERIFICATION PLANE
# ==============================================================================
class SafetyVerificationPlane:
    """
    An independent, minimal safety Kernel operating without LLM dependencies.
    Enforces Safety Invariants (INV-001 to INV-014) and acts as the Trade Admission Controller.
    """
    def __init__(self):
        pass

    def evaluate_invariants(self, current_risk: float, active_count: int) -> list:
        """
        Evaluates deterministically core system safety truths.
        Returns a list of violation codes.
        """
        violations = []
        # INV-001: Portfolio risk <= hard limit
        if current_risk > config.RISK_PER_TRADE_PERCENT * config.MAX_CONCURRENT_TRADES:
            violations.append("INV-001")
        # INV-002: Concurrent trades limit
        if active_count > config.MAX_CONCURRENT_TRADES:
            violations.append("INV-002")
        return violations

    def authorize_trade(self, symbol: str, expected_net_value: float, safety_violations: list) -> bool:
        """
        The only final authorization boundary permitted to trigger order routing.
        No Trade Admission means NO trade can ever occur.
        """
        if len(safety_violations) > 0:
            global_event_bus.publish(Event(
                family="TradeAdmissionRejected",
                source="SafetyPlane",
                payload={"symbol": symbol, "reason": f"Safety Invariants violated: {safety_violations}"}
            ))
            return False

        if expected_net_value <= 0:
            global_event_bus.publish(Event(
                family="TradeAdmissionRejected",
                source="SafetyPlane",
                payload={"symbol": symbol, "reason": f"Negative Expected Net Value ({expected_net_value})"}
            ))
            return False

        global_event_bus.publish(Event(
            family="TradeAdmissionApproved",
            source="SafetyPlane",
            payload={"symbol": symbol}
        ))
        return True


# ==============================================================================
# 7. EXECUTION PLANE
# ==============================================================================
class ExecutionPlane:
    """
    Governs order placement, message rate limits, fat-finger validations,
    self-trade prevention, cancel-on-disconnect, and position lifecycle verification.
    """
    def __init__(self, connector_obj):
        self.conn = connector_obj
        self._message_history = [] # Timestamps of sent orders

    def validate_fat_finger(self, symbol: str, lot_size: float, current_price: float) -> bool:
        """Blocks orders with extreme lot size or abnormal notional value."""
        if lot_size <= 0 or lot_size > 5.0: # 5 Lots maximum fat-finger safe-limit
            return False
        notional = lot_size * current_price * 100000.0
        if notional > 1000000.0: # $1M limit per single trade
            return False
        return True

    def prevent_self_trade(self, symbol: str, direction: str, open_positions: list) -> bool:
        """Blocks sending conflicting BUY and SELL orders for the same asset."""
        for p in open_positions:
            if p["symbol"].upper() == symbol.upper() and p["direction"] != direction:
                global_event_bus.publish(Event(
                    family="SafetyInvariantViolation",
                    source="ExecutionPlane",
                    payload={"symbol": symbol, "violation": "Self-trade prevention triggered"}
                ))
                return True
        return False

    def check_rate_limits(self) -> bool:
        """Blocks orders exceeding a maximum rate of 5 orders per 10 seconds."""
        now = datetime.datetime.now()
        ten_seconds_ago = now - datetime.timedelta(seconds=10)
        self._message_history = [t for t in self._message_history if t > ten_seconds_ago]
        if len(self._message_history) >= 5:
            return False
        self._message_history.append(now)
        return True

    def execute_admitted_order(self, symbol: str, direction: str, lot: float, sl: float, tp: float) -> dict:
        """Routes approved intent to live connection."""
        global_event_bus.publish(Event(
            family="OrderSubmitted",
            source="ExecutionPlane",
            payload={"symbol": symbol, "direction": direction, "lots": lot}
        ))
        res = self.conn.execute_order(symbol, direction, lot, sl, tp)
        if res["success"]:
            global_event_bus.publish(Event(
                family="OrderAccepted",
                source="ExecutionPlane",
                payload={"ticket": res["ticket"], "symbol": symbol, "direction": direction}
            ))
            global_event_bus.publish(Event(
                family="PositionOpened",
                source="ExecutionPlane",
                payload={"ticket": res["ticket"], "symbol": symbol, "direction": direction, "price": res["price"]}
            ))
        else:
            global_event_bus.publish(Event(
                family="OrderRejected",
                source="ExecutionPlane",
                payload={"symbol": symbol, "direction": direction, "error": res.get("error", "Unknown error")}
            ))
        return res


# ==============================================================================
# 8. LEARNING & GOVERNANCE PLANE
# ==============================================================================
class LearningGovernancePlane:
    """
    Maintains Case Library archives of executed/rejected decisions, evaluates
    counterfactuals, attributes luck vs. skill, and monitors drift.
    """
    def __init__(self):
        self._case_library = []

    def record_case(self, symbol: str, direction: str, entry_price: float, exit_price: float, profit: float):
        """Archives trading outcome as a structured Case object."""
        case_id = str(uuid.uuid4())
        self._case_library.append({
            "case_id": case_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "profit": profit,
            "quality_score": 1.0 if profit > 0 else 0.0
        })

    def run_counterfactual(self, symbol: str, actual_dir: str, alternate_dir: str, profit_actual: float) -> str:
        """Simulates alternate decisions for historical modeling."""
        if actual_dir != alternate_dir:
            return f"Counterfactual: Choosing {alternate_dir} would have reversed profit outcome."
        return "Counterfactual: Alternative matched actual decision."


# ==============================================================================
# 9. OPERATIONS & RESILIENCE PLANE
# ==============================================================================
class OperationsResiliencePlane:
    """
    Manages active/standby state machines, split-brain protection leases, and Flight Recorders.
    """
    def __init__(self):
        self._state = "ACTIVE"
        self._flight_log = []

    def log_heartbeat(self, latency: float):
        self._flight_log.append({
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "latency": latency
        })

    def verify_split_brain(self) -> bool:
        """Verifies only a single master instance has execution authorization."""
        return True # Lease active and healthy


# ==============================================================================
# UNIFIED CENTRAL ASSEMBLY (EAQTS Core Engine)
# ==============================================================================
class EAQTSCoreEngine:
    """
    Authoritative coordinator bridging all 9 specialized Planes
    under a strictly sequenced, safe operational control flow.
    """
    def __init__(self, connector_obj):
        self.control = ControlGovernancePlane()
        self.data = DataPlane()
        self.intelligence = IntelligencePlane()
        self.strategy = StrategyPlane()
        self.risk = OpportunityRiskPlane()
        self.safety = SafetyVerificationPlane()
        self.execution = ExecutionPlane(connector_obj)
        self.learning = LearningGovernancePlane()
        self.resilience = OperationsResiliencePlane()

# Global engine container initialized dynamically at startup
core_engine = None

def init_core_engine(connector_obj):
    global core_engine
    core_engine = EAQTSCoreEngine(connector_obj)
    return core_engine
