"""
Institutional Integration Suite.
Consolidates advanced machine learning, data science, databases, natural language processing,
advanced quantitative mathematics modules, options & derivatives engines, hedge fund swarms,
extended market connectors, quantitative portfolio analytics, and alpha strategy libraries.
"""
from typing import Any
from .advanced_math import calculate_markov_regime_switching_probability, evaluate_black_scholes_option_pricing
from .alpha_strategies_library import AlphaStrategyLibrary
from .brain_self_healer import QuantumSelfHealer
from .comprehensive_suite import integrate_airflow, integrate_akshare, integrate_altair, integrate_arrow, integrate_autots, integrate_backtrader, integrate_beautifulsoup, integrate_bert, integrate_bokeh, integrate_boto3, integrate_catboost, integrate_ccxt, integrate_chromadb, integrate_click, integrate_cupy, integrate_darts, integrate_dask, integrate_datatable, integrate_django, integrate_duckdb, integrate_edgartools, integrate_faiss, integrate_fastapi, integrate_flask, integrate_folium, integrate_gensim, integrate_geopandas, integrate_github, integrate_gpio, integrate_great_expectations, integrate_hadoop, integrate_jax, integrate_jupyter, integrate_kafka, integrate_kats, integrate_keras, integrate_kivy, integrate_koalas, integrate_langchain, integrate_langextract, integrate_langgraph, integrate_lifelines, integrate_lightgbm, integrate_litellm, integrate_llamaindex, integrate_loguru, integrate_matplotlib, integrate_modin, integrate_neo4j, integrate_networkx, integrate_nltk, integrate_numpy, integrate_octoparse, integrate_openai, integrate_opencv, integrate_pandas, integrate_pandera, integrate_paramiko, integrate_peewee, integrate_pinecone, integrate_pingouin, integrate_plotly, integrate_pmdarima, integrate_polars, integrate_polyglot, integrate_prophet, integrate_pycryptodome, integrate_pydantic, integrate_pyfolio, integrate_pygal, integrate_pygame, integrate_pymc3, integrate_pyo3, integrate_pyscript, integrate_pyserial, integrate_pyspark, integrate_pystan, integrate_pytest, integrate_pytorch, integrate_quantlib, integrate_ray, integrate_requests, integrate_rich, integrate_robyn, integrate_rq, integrate_ruff, integrate_rust_wrapped_python, integrate_scikit_learn, integrate_scipy, integrate_scrapy, integrate_seaborn, integrate_selenium, integrate_sentence_transformers, integrate_sktime, integrate_spacy, integrate_sqlalchemy, integrate_statsmodels, integrate_sympy, integrate_talib, integrate_tensorflow, integrate_textblob, integrate_textual, integrate_theano, integrate_tinydb, integrate_tkinter, integrate_transformers, integrate_tsfresh, integrate_typer, integrate_vaex, integrate_xgboost, integrate_yfinance, integrate_zipline
from .data_science import calculate_portfolio_weights, perform_statistical_pingouin_test
from .kronos_model import KronosFoundationModel, KronosTokenizer
from .propfirm_risk_guard_engine import PropFirmRiskGuardEngine, RiskTick, RiskSeverity, TrailingDDConfig, DailyLossConfig, CutoffConfig, ConsistencyConfig, NewsWindow
from .arkorisk_guard import ArkoRiskGuard, RiskProfilePreset, PROP_FIRM_DATABASE, MarketType, DrawdownTaxonomy
from .prop_firm_monte_carlo_ev import PropFirmMonteCarloEVEngine, PropChallengeConfig, SimulationResult
from .trading_seatbelt_engine import TradingSeatbeltEngine, SeatbeltStatus, CooldownStatus
from .dxtrade_broker_adapter import DXTradeBrokerAdapter, DXTradeAccountSummary, DXTradeOrderRequest, DXTradeOrderResponse
from .batch3_quant_strategies import VWAPFadeStrategy, OvernightDriftStrategy, VolatilityExpansionStrategy, EngulfingAtExtremeStrategy, PivotReactionZoneStrategy, QuantSignal
from .neoethos_autoresearch import NeoethosAutoResearchEngine, ResearchObjectiveConfig, ResearchHypothesisResult, NeoethosReplayStats
from .ict_system_v2_engine import ICTSystemV2Engine, MarketBias, StructureType, PDAZone, SMTDivergenceResult, PDAResult, ICTSignalResult
from .crypto_trader_v2_engine import CryptoTraderV2Engine, OBISignalType, OrderBookLevel, OrderBookDepthPayload, SentimentResult, OBIScalperState
from .apex_trading_engine import ApexTradingRiskEngine, ApexTradingAISignalEngine, ApexVaRResult, ApexGreeksResult, ApexRiskLimitCheck, ApexLSTMPricePrediction
from .quant_backtest_pro_engine import MultiAssetMathEngine, HighPrecisionOrderMatchingEngine, SymbolConfig, Candle, Position, PendingOrder, OrderType, PositionSide, PositionStatus
from .rc_news_feeder import RCNewsFeederEngine, NewsEvent, NewsImpact, NewsBlackoutCheck
from .trading_agents_suite import TradingAgentsOrchestrator, BullResearcherAgent, BearResearcherAgent, RiskDebaterAgent, DebateRound, TradingAgentsDecision, AgentRole
from .trading_agents_cn_suite import ChinaMarketAnalystAgent, EnhancedNewsFilterEngine, DataCompletenessChecker, ChinaMarketReport, FilteredNewsArticle, DataCompletenessReport
from .solana_dex_risk_guard import SolanaDEXRiskGuard, DEXPoolMetrics, DEXRiskCheckResult
from .freqtrade_protection_engine import FreqtradeProtectionEngine, PairLock, LockSide, ProtectionCheckResult
from .quantdinger_engine import QuantDingerGridEngine, QuantDingerFactorResearchEngine, GridMode, GridLevel, GridState, FactorScoreResult
from .superalgos_trading_engine import SuperalgosTradingStagesEngine, StageType, TriggerStatus, SuperalgosPosition, EpisodeMetrics
from .backtrader_engine import BacktraderAnalyzerEngine, BacktraderSizerEngine, BacktraderPerformanceMetrics, BacktraderSizerResult
from .ml4t_trading_engine import PurgedWalkForwardCV, EigenportfolioDecomposition, WalkForwardSplit, EigenportfolioResult
from .zipline_finance_engine import ZiplineSlippageModel, ZiplineCommissionModel, ZiplineRiskControlEngine, OrderSide as ZiplineOrderSide, SlippageResult, CommissionResult, RiskControlCheck
from .stocksharp_risk_engine import StockSharpRiskManager, RiskAction, RiskRuleViolation
from .binance_trade_bot_engine import BridgeCoinScoutEngine, AltcoinRatio, BridgeJumpDecision
from .lean_framework_engine import PearsonCorrelationPairsTradingAlphaModel, LeanMaximumDrawdownPercentPortfolio, PairCorrelationResult, LeanPortfolioTarget
from .ai_trader_scoring_engine import AITraderSignalQualityEvaluator, AITraderChallengeScoringEngine, SignalQualityMetrics, AgentScoreResult
from .systematic_trading_carver import PySystemTradeEngine, CarverForecastScalarResult, CarverDiversificationResult
from .jesse_metrics_and_quant_suite import JesseMetricsEngine, JesseQuantStrategyLibrary, JessePerformanceReport, QuantStrategySignal
from .backtesting_py_suite import SignalStrategy, TrailingStrategy, resample_apply, crossover, cross, barssince, BacktestTradeSignal
from .hummingbot_suite import AvellanedaStoikovMarketMakingEngine, PureMarketMakingInventorySkewEngine, CrossExchangeArbitrageEngine, AvellanedaQuote, SkewedSpreads, ArbitrageOpportunity
from .pytrader_gym_suite import TradingGymRLAdapter, PyTraderDepthAnalyzer, GymStepResult, DepthAnalysisResult
from .nofx_ai_terminal_engine import NoFxRiskRuntimeDisposer, NoFxMarketDirectionBoard, NoFxAiModelManager, NoFxAction, NoFxModelDecision, NoFxClampedOrder, global_nofx_disposer, global_nofx_direction_board, global_nofx_model_manager
from .finterion_adapter import FinterionPortfolioProvider, FinterionOrderExecutor, FinterionPingHook, FinterionPosition, FinterionPortfolio, FinterionOrderRequest, FinterionOrderResponse
from .kit_bot_engine import KitPineScriptGenerator, KitSocialSignalParser, KitAutopilotManager, KitAutopilotMode, KitParsedSignal, KitAutopilotDecision
from .indian_market_state_machine import IndianMarketStateMachine, IndianMarketState, round_to_indian_tick_size, global_indian_state_machine
from .indian_instrument_scheduler import IndianInstrumentScheduler, global_indian_scheduler
from .sebi_broker_adapter import round_to_indian_quantity, SEBIBrokerAdapter, KiteConnectAdapter, DhanHQAdapter, AngelOneAdapter, KotakNeoAdapter, UpstoxAdapter, ICICIDirectAdapter, FivePaisaAdapter, IIFLXTSAdapter, MotilalOswalAdapter, UnifiedIndianBrokerClientAdapter, SEBIOrderRequest, SEBIOrderResponse, validate_indian_product_tag, VALID_INDIAN_PRODUCT_TAGS, VALID_INDIAN_EXCHANGES
from .databases import insert_vector_embedding, propagate_graph_breakout_warnings, query_high_speed_analytical_duckdb
from .extended_market_connectors import ExtendedDataConnectors
from .finagent_hedgefund_swarm import HedgeFundSwarmOrchestrator
from .go_gateway import start_go_concurrency_websocket_relay
from .machine_learning import evaluate_deep_rl_policy_action, generate_multi_model_ensemble_prediction
from .natural_language import extract_advanced_nlp_sentiments
from .options_derivatives_engine import GammaExposureAnalyzer, OptionStrategySimulator, OptionsPricingEngine
from .quant_portfolio_analytics import PortfolioOptimizationEngine, QuantPerformanceMetrics
from .quantum_quantum_engine import QuantumAutoEngine
from .rust_bridge import execute_high_speed_rust_order_send
from .web_api import fetch_yfinance_external_rates, push_telemetry_to_kafka_queue
from .bayesian_consensus import BayesianConsensusEngine, global_bayesian_consensus
from . import aat_strategies
from .aat_analyst import MacroAnalyst, SMCAnalyst, VolatilityAnalyst
from . import itip_signal_store
from .mql_colab_engine import SLTPEngine, CandlestickAIClassifier, LatencyArbitrage
from .sovereign_intelligence import SovereignIntelligencePlugin
from . import vibe_quantlib
from .openalgo_engine import OpenAlgoSmartOrderSplitter, OpenAlgoSessionSquareOffManager, OpenAlgoIndianExchangeRouter
from .openbull_analytics import calculate_max_pain, calculate_synthetic_future_price
from .nautilus_trader_engine import NautilusFixedRiskSizer, NautilusOrderRoutingGuard
from .prop_firm_tracker import PropFirmChallengeTracker
from .ftmo_risk_guard import FTMORiskGuardEngine, FTMOQualificationAuditor
from .meta_edge_quant import calculate_probabilistic_sharpe_ratio, calculate_kelly_fraction, calculate_edge_score, EmpiricalSlippageTracker
from .nexquant_engine import NexQuantFactorModel, NexQuantPortfolioOptimizer
from .ftmo_journal_analyzer import FTMOJournalAnalyzer
from .ftmo_tradingbot_core import ScaleOnProfitEngine, FTMODynamicStopEngine, ConsensusSizingModulator, CombinedExposureCapGuard
from .prop_firm_calendar_feed import PropFirmTradingEvent, PropFirmCalendarFeedManager
from .qma_quant_strategy import detect_rsi_failure_swing, calculate_ttm_squeeze, QMAQuantStrategy
from .mt5bot_engine import MT5BotVolumeNormalizer, RelativePricePredictionEvaluator
from .ftmo_temporal_matcher import FewShotTemporalMatcher
from .awesome_llm_finance_team import MultiAgentFinanceTeamOrchestrator
from .awesome_llm_agents import DeepResearchAgent, InvestmentAgent, DataAnalystAgent
from .ea_scalper_xauusd_engine import AMDCycleTracker, FootprintPocAnalyzer, MarketGapCooldownGuard
from .prop_guard_equity_armor import PropGuardEquityArmorEngine
from .prop_firm_elite_tracker import SignalPulseLogSyncParser, PropFirmEliteMultiAccountAggregator
from .prop_guardian_safety import PropGuardianMasterFilters, PROP_FIRMS_DATABASE
from .calculus_quant_engine import calculate_hma, MarketEntropyMonitor, GeometricExitEngine
__all__ = ["BayesianConsensusEngine", "global_bayesian_consensus", "aat_strategies", "MacroAnalyst", "SMCAnalyst", "VolatilityAnalyst", "itip_signal_store", "SLTPEngine", "CandlestickAIClassifier", "LatencyArbitrage", "SovereignIntelligencePlugin", "vibe_quantlib", "OpenAlgoSmartOrderSplitter", "OpenAlgoSessionSquareOffManager", "OpenAlgoIndianExchangeRouter", "calculate_max_pain", "calculate_synthetic_future_price", "NautilusFixedRiskSizer", "NautilusOrderRoutingGuard", "PropFirmChallengeTracker", "FTMORiskGuardEngine", "FTMOQualificationAuditor", "calculate_probabilistic_sharpe_ratio", "calculate_kelly_fraction", "calculate_edge_score", "EmpiricalSlippageTracker", "NexQuantFactorModel", "NexQuantPortfolioOptimizer", "FTMOJournalAnalyzer", "ScaleOnProfitEngine", "FTMODynamicStopEngine", "ConsensusSizingModulator", "CombinedExposureCapGuard", "PropFirmTradingEvent", "PropFirmCalendarFeedManager", "detect_rsi_failure_swing", "calculate_ttm_squeeze", "QMAQuantStrategy", "MT5BotVolumeNormalizer", "RelativePricePredictionEvaluator", "FewShotTemporalMatcher", "MultiAgentFinanceTeamOrchestrator", "DeepResearchAgent", "InvestmentAgent", "DataAnalystAgent", "AMDCycleTracker", "FootprintPocAnalyzer", "MarketGapCooldownGuard", "PropGuardEquityArmorEngine", "SignalPulseLogSyncParser", "PropFirmEliteMultiAccountAggregator", "PropGuardianMasterFilters", "PROP_FIRMS_DATABASE", "calculate_hma", "MarketEntropyMonitor", "GeometricExitEngine", "calculate_markov_regime_switching_probability", "evaluate_black_scholes_option_pricing", "QuantumSelfHealer", "integrate_pandas", "calculate_portfolio_weights", "perform_statistical_pingouin_test", "insert_vector_embedding", "propagate_graph_breakout_warnings", "query_high_speed_analytical_duckdb", "start_go_concurrency_websocket_relay", "evaluate_deep_rl_policy_action", "generate_multi_model_ensemble_prediction", "extract_advanced_nlp_sentiments", "QuantumAutoEngine", "execute_high_speed_rust_order_send", "fetch_yfinance_external_rates", "push_telemetry_to_kafka_queue", "OptionsPricingEngine", "GammaExposureAnalyzer", "OptionStrategySimulator", "HedgeFundSwarmOrchestrator", "ExtendedDataConnectors", "PortfolioOptimizationEngine", "QuantPerformanceMetrics", "AlphaStrategyLibrary", "KronosFoundationModel", "KronosTokenizer", "PropFirmRiskGuardEngine", "RiskTick", "RiskSeverity", "TrailingDDConfig", "DailyLossConfig", "CutoffConfig", "ConsistencyConfig", "NewsWindow", "ArkoRiskGuard", "RiskProfilePreset", "PROP_FIRM_DATABASE", "MarketType", "DrawdownTaxonomy", "PropFirmMonteCarloEVEngine", "PropChallengeConfig", "SimulationResult", "TradingSeatbeltEngine", "SeatbeltStatus", "CooldownStatus", "DXTradeBrokerAdapter", "DXTradeAccountSummary", "DXTradeOrderRequest", "DXTradeOrderResponse", "VWAPFadeStrategy", "OvernightDriftStrategy", "VolatilityExpansionStrategy", "EngulfingAtExtremeStrategy", "PivotReactionZoneStrategy", "QuantSignal", "NeoethosAutoResearchEngine", "ResearchObjectiveConfig", "ResearchHypothesisResult", "NeoethosReplayStats", "ICTSystemV2Engine", "MarketBias", "StructureType", "PDAZone", "SMTDivergenceResult", "PDAResult", "ICTSignalResult", "CryptoTraderV2Engine", "OBISignalType", "OrderBookLevel", "OrderBookDepthPayload", "SentimentResult", "OBIScalperState", "ApexTradingRiskEngine", "ApexTradingAISignalEngine", "ApexVaRResult", "ApexGreeksResult", "ApexRiskLimitCheck", "ApexLSTMPricePrediction", "MultiAssetMathEngine", "HighPrecisionOrderMatchingEngine", "SymbolConfig", "Candle", "Position", "PendingOrder", "OrderType", "PositionSide", "PositionStatus", "RCNewsFeederEngine", "NewsEvent", "NewsImpact", "NewsBlackoutCheck", "TradingAgentsOrchestrator", "BullResearcherAgent", "BearResearcherAgent", "RiskDebaterAgent", "DebateRound", "TradingAgentsDecision", "AgentRole", "ChinaMarketAnalystAgent", "EnhancedNewsFilterEngine", "DataCompletenessChecker", "ChinaMarketReport", "FilteredNewsArticle", "DataCompletenessReport", "SolanaDEXRiskGuard", "DEXPoolMetrics", "DEXRiskCheckResult", "FreqtradeProtectionEngine", "PairLock", "LockSide", "ProtectionCheckResult", "QuantDingerGridEngine", "QuantDingerFactorResearchEngine", "GridMode", "GridLevel", "GridState", "FactorScoreResult", "SuperalgosTradingStagesEngine", "StageType", "TriggerStatus", "SuperalgosPosition", "EpisodeMetrics", "BacktraderAnalyzerEngine", "BacktraderSizerEngine", "BacktraderPerformanceMetrics", "BacktraderSizerResult", "ZiplineSlippageModel", "ZiplineCommissionModel", "ZiplineRiskControlEngine", "ZiplineOrderSide", "SlippageResult", "CommissionResult", "RiskControlCheck", "StockSharpRiskManager", "RiskAction", "RiskRuleViolation", "BridgeCoinScoutEngine", "AltcoinRatio", "BridgeJumpDecision", "PearsonCorrelationPairsTradingAlphaModel", "LeanMaximumDrawdownPercentPortfolio", "PairCorrelationResult", "LeanPortfolioTarget", "AITraderSignalQualityEvaluator", "AITraderChallengeScoringEngine", "SignalQualityMetrics", "AgentScoreResult", "PySystemTradeEngine", "CarverForecastScalarResult", "CarverDiversificationResult", "JesseMetricsEngine", "JesseQuantStrategyLibrary", "JessePerformanceReport", "QuantStrategySignal", "SignalStrategy", "TrailingStrategy", "resample_apply", "crossover", "cross", "barssince", "BacktestTradeSignal", "AvellanedaStoikovMarketMakingEngine", "PureMarketMakingInventorySkewEngine", "CrossExchangeArbitrageEngine", "AvellanedaQuote", "SkewedSpreads", "ArbitrageOpportunity", "TradingGymRLAdapter", "PyTraderDepthAnalyzer", "GymStepResult", "DepthAnalysisResult", "NoFxRiskRuntimeDisposer", "NoFxMarketDirectionBoard", "NoFxAiModelManager", "NoFxAction", "NoFxModelDecision", "NoFxClampedOrder", "global_nofx_disposer", "global_nofx_direction_board", "global_nofx_model_manager", "FinterionPortfolioProvider", "FinterionOrderExecutor", "FinterionPingHook", "FinterionPosition", "FinterionPortfolio", "FinterionOrderRequest", "FinterionOrderResponse", "KitPineScriptGenerator", "KitSocialSignalParser", "KitAutopilotManager", "KitAutopilotMode", "KitParsedSignal", "KitAutopilotDecision", "IndianInstrumentScheduler", "global_indian_scheduler", "IndianMarketStateMachine", "IndianMarketState", "round_to_indian_tick_size", "global_indian_state_machine", "AngelOneAdapter", "KotakNeoAdapter", "UpstoxAdapter", "ICICIDirectAdapter", "FivePaisaAdapter", "IIFLXTSAdapter", "MotilalOswalAdapter", "UnifiedIndianBrokerClientAdapter", "round_to_indian_quantity"]
