"""
Institutional Integration Suite.
Consolidates advanced machine learning, data science, databases, natural language processing,
advanced quantitative mathematics modules, options & derivatives engines, hedge fund swarms,
extended market connectors, quantitative portfolio analytics, and alpha strategy libraries.
"""

from .advanced_math import (  # noqa: F401
    calculate_markov_regime_switching_probability,
    evaluate_black_scholes_option_pricing,
)
from .alpha_strategies_library import AlphaStrategyLibrary  # noqa: F401
from .brain_self_healer import QuantumSelfHealer  # noqa: F401
from .comprehensive_suite import (  # noqa: F401
    integrate_airflow, integrate_akshare, integrate_altair, integrate_arrow, integrate_autots, integrate_backtrader,  # noqa: F401
    integrate_beautifulsoup, integrate_bert, integrate_bokeh, integrate_boto3, integrate_catboost, integrate_ccxt,  # noqa: F401
    integrate_chromadb, integrate_click, integrate_cupy, integrate_darts, integrate_dask, integrate_datatable,  # noqa: F401
    integrate_django, integrate_duckdb, integrate_edgartools, integrate_faiss, integrate_fastapi, integrate_flask,  # noqa: F401
    integrate_folium, integrate_gensim, integrate_geopandas, integrate_github, integrate_gpio, integrate_great_expectations,  # noqa: F401
    integrate_hadoop, integrate_jax, integrate_jupyter, integrate_kafka, integrate_kats, integrate_keras, integrate_kivy,  # noqa: F401
    integrate_koalas, integrate_langchain, integrate_langextract, integrate_langgraph, integrate_lifelines,  # noqa: F401
    integrate_lightgbm, integrate_litellm, integrate_llamaindex, integrate_loguru, integrate_matplotlib, integrate_modin,  # noqa: F401
    integrate_neo4j, integrate_networkx, integrate_nltk, integrate_numpy, integrate_octoparse, integrate_openai,  # noqa: F401
    integrate_opencv, integrate_pandas, integrate_pandera, integrate_paramiko, integrate_peewee, integrate_pinecone,  # noqa: F401
    integrate_pingouin, integrate_plotly, integrate_pmdarima, integrate_polars, integrate_polyglot, integrate_prophet,  # noqa: F401
    integrate_pycryptodome, integrate_pydantic, integrate_pyfolio, integrate_pygal, integrate_pygame, integrate_pymc3,  # noqa: F401
    integrate_pyo3, integrate_pyscript, integrate_pyserial, integrate_pyspark, integrate_pystan, integrate_pytest,  # noqa: F401
    integrate_pytorch, integrate_quantlib, integrate_ray, integrate_requests, integrate_rich, integrate_robyn,  # noqa: F401
    integrate_rq, integrate_ruff, integrate_rust_wrapped_python, integrate_scikit_learn, integrate_scipy,  # noqa: F401
    integrate_scrapy, integrate_seaborn, integrate_selenium, integrate_sentence_transformers, integrate_sktime,  # noqa: F401
    integrate_spacy, integrate_sqlalchemy, integrate_statsmodels, integrate_sympy, integrate_talib, integrate_tensorflow,  # noqa: F401
    integrate_textblob, integrate_textual, integrate_theano, integrate_tinydb, integrate_tkinter, integrate_transformers,  # noqa: F401
    integrate_tsfresh, integrate_typer, integrate_vaex, integrate_xgboost, integrate_yfinance, integrate_zipline  # noqa: F401
)
from .data_science import calculate_portfolio_weights, perform_statistical_pingouin_test  # noqa: F401
from .databases import (  # noqa: F401
    insert_vector_embedding,  # noqa: F401
    propagate_graph_breakout_warnings,  # noqa: F401
    query_high_speed_analytical_duckdb,  # noqa: F401
)
from .extended_market_connectors import ExtendedDataConnectors  # noqa: F401
from .finagent_hedgefund_swarm import HedgeFundSwarmOrchestrator  # noqa: F401
from .go_gateway import start_go_concurrency_websocket_relay  # noqa: F401
from .machine_learning import (  # noqa: F401
    evaluate_deep_rl_policy_action,  # noqa: F401
    generate_multi_model_ensemble_prediction,  # noqa: F401
)
from .natural_language import extract_advanced_nlp_sentiments  # noqa: F401
from .options_derivatives_engine import (  # noqa: F401
    GammaExposureAnalyzer,  # noqa: F401
    OptionStrategySimulator,  # noqa: F401
    OptionsPricingEngine,  # noqa: F401
)
from .quant_portfolio_analytics import (  # noqa: F401
    PortfolioOptimizationEngine,  # noqa: F401
    QuantPerformanceMetrics,  # noqa: F401
)
from .quantum_quantum_engine import QuantumAutoEngine  # noqa: F401
from .rust_bridge import execute_high_speed_rust_order_send  # noqa: F401
from .web_api import fetch_yfinance_external_rates, push_telemetry_to_kafka_queue  # noqa: F401

__all__ = [
    "calculate_markov_regime_switching_probability",
    "evaluate_black_scholes_option_pricing",
    "QuantumSelfHealer",
    "integrate_pandas",
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
    "OptionsPricingEngine",
    "GammaExposureAnalyzer",
    "OptionStrategySimulator",
    "HedgeFundSwarmOrchestrator",
    "ExtendedDataConnectors",
    "PortfolioOptimizationEngine",
    "QuantPerformanceMetrics",
    "AlphaStrategyLibrary",
]
