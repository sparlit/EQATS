"""
Institutional Integration Suite.
Consolidates advanced machine learning, data science, databases, natural language processing,
and advanced quantitative mathematics modules.
"""

from .advanced_math import (  # noqa: F401
    calculate_markov_regime_switching_probability,
    evaluate_black_scholes_option_pricing,
)
from .brain_self_healer import QuantumSelfHealer  # noqa: F401
from .comprehensive_suite import *  # noqa: F401, F403
from .data_science import calculate_portfolio_weights, perform_statistical_pingouin_test  # noqa: F401
from .databases import (  # noqa: F401
    insert_vector_embedding,
    propagate_graph_breakout_warnings,
    query_high_speed_analytical_duckdb,
)
from .go_gateway import start_go_concurrency_websocket_relay  # noqa: F401
from .machine_learning import (  # noqa: F401
    evaluate_deep_rl_policy_action,
    generate_multi_model_ensemble_prediction,
)
from .natural_language import extract_advanced_nlp_sentiments
from .quantum_quantum_engine import QuantumAutoEngine
from .rust_bridge import execute_high_speed_rust_order_send
from .web_api import fetch_yfinance_external_rates, push_telemetry_to_kafka_queue

__all__ = [
    "calculate_markov_regime_switching_probability",
    "evaluate_black_scholes_option_pricing",
    "QuantumSelfHealer",
    "calculate_portfolio_weights",
    "perform_statistical_pingouin_test",
    "insert_vector_embedding",
    "propagate_graph_breakout_warnings",
    "query_high_speed_analytical_duckdb",
    "start_go_concurrency_websocket_relay",
    "evaluate_deep_rl_policy_action",
    "generate_multi_model_ensemble_prediction",
    "extract_advanced_nlp_sentiments",
    "QuantumAutoEngine",
    "execute_high_speed_rust_order_send",
    "fetch_yfinance_external_rates",
    "push_telemetry_to_kafka_queue",
]
