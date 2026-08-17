"""
Integration Manager
Controls which institutional integrations are allowed to run.
Prevents fake/MOCKED integrations from affecting live trading.
"""

import os
from typing import Dict, List, Set
from enum import Enum


class IntegrationStatus(Enum):
    """Integration status."""
    AVAILABLE = "AVAILABLE"  # Real integration available and verified
    UNAVAILABLE = "UNAVAILABLE"  # Integration not installed
    DISABLED = "DISABLED"  # Integration disabled (fake or unverified)
    MOCKED = "MOCKED"  # Returns fake data (should not be used in production)


class IntegrationManager:
    """
    Manages which institutional integrations are allowed to run.
    
    This prevents fake/MOCKED integrations from affecting live trading
    decisions by controlling which integrations can be used.
    """
    
    def __init__(self):
        """Initialize integration manager."""
        self._enabled_integrations: Set[str] = set()
        self._disabled_integrations: Set[str] = set()
        self._verified_integrations: Set[str] = set()
        self._load_configuration()
    
    def _load_configuration(self):
        """Load integration configuration from environment or defaults."""
        # Default: All comprehensive_suite integrations are DISABLED (fake)
        self._disabled_integrations.update([
            "integrate_airflow", "integrate_akshare", "integrate_altair", "integrate_autots",
            "integrate_beautifulsoup", "integrate_bert", "integrate_bokeh", "integrate_boto3",
            "integrate_chromadb", "integrate_click", "integrate_cupy", "integrate_darts",
            "integrate_dask", "integrate_datatable", "integrate_django", "integrate_duckdb",
            "integrate_edgartools", "integrate_faiss", "integrate_fastapi", "integrate_flask",
            "integrate_folium", "integrate_rpi_gpio", "integrate_gensim", "integrate_geopandas",
            "integrate_github", "integrate_great_expectations", "integrate_hadoop", "integrate_jax",
            "integrate_kafka", "integrate_kats", "integrate_keras", "integrate_kivy",
            "integrate_koalas", "integrate_langchain", "integrate_langdetect", "integrate_langgraph",
            "integrate_lifelines", "integrate_lightgbm", "integrate_litellm", "integrate_llamaindex",
            "integrate_loguru", "integrate_matplotlib", "integrate_modin", "integrate_nltk",
            "integrate_neo4j", "integrate_networkx", "integrate_numpy", "integrate_octoparse",
            "integrate_openai", "integrate_opencv", "integrate_pandera", "integrate_paramiko",
            "integrate_peewee", "integrate_pinecone", "integrate_pingouin", "integrate_plotly",
            "integrate_polars", "integrate_polyglot", "integrate_prophet", "integrate_pycryptodome",
            "integrate_pyfolio", "integrate_pymc3", "integrate_pyscript", "integrate_pyserial",
            "integrate_pyspark", "integrate_pystan", "integrate_pytest", "integrate_pytorch",
            "integrate_pydantic", "integrate_pygal", "integrate_pygame", "integrate_pyo3",
            "integrate_quantlib", "integrate_ray", "integrate_rq", "integrate_rich",
            "integrate_robyn", "integrate_ruff", "integrate_sqlalchemy", "integrate_scipy",
            "integrate_scikit_learn", "integrate_scrapy", "integrate_seaborn", "integrate_selenium",
            "integrate_sentence_transformers", "integrate_sktime", "integrate_statsmodels",
            "integrate_sympy", "integrate_talib", "integrate_tensorflow", "integrate_textblob",
            "integrate_textual", "integrate_tinydb", "integrate_tkinter", "integrate_transformers"
        ])
        
        # Disable fake bridges
        self._disabled_integrations.update([
            "execute_high_speed_rust_order_send",
            "execute_go_microservice"
        ])
        
        # Disable fake quantum engine
        self._disabled_integrations.update([
            "execute_research_scrapers_and_apis",
            "determine_optimal_style_and_strategy",
            "evaluate_all_strategies"
        ])
        
        # Disable fake ML
        self._disabled_integrations.update([
            "generate_multi_model_ensemble_prediction"
        ])
        
        # Check environment for overrides
        enabled_from_env = os.getenv('ENABLED_INTEGRATIONS', '')
        if enabled_from_env:
            self._enabled_integrations.update(enabled_from_env.split(','))
        
        disabled_from_env = os.getenv('DISABLED_INTEGRATIONS', '')
        if disabled_from_env:
            self._disabled_integrations.update(disabled_from_env.split(','))
    
    def is_integration_enabled(self, integration_name: str) -> bool:
        """
        Check if an integration is enabled.
        
        Args:
            integration_name: Name of the integration function
            
        Returns:
            True if integration is enabled, False otherwise
        """
        # Explicitly disabled
        if integration_name in self._disabled_integrations:
            return False
        
        # Explicitly enabled
        if integration_name in self._enabled_integrations:
            return True
        
        # Default: disabled unless verified
        return integration_name in self._verified_integrations
    
    def enable_integration(self, integration_name: str):
        """
        Enable an integration.
        
        Args:
            integration_name: Name of the integration to enable
        """
        self._disabled_integrations.discard(integration_name)
        self._enabled_integrations.add(integration_name)
    
    def disable_integration(self, integration_name: str):
        """
        Disable an integration.
        
        Args:
            integration_name: Name of the integration to disable
        """
        self._enabled_integrations.discard(integration_name)
        self._disabled_integrations.add(integration_name)
    
    def verify_integration(self, integration_name: str):
        """
        Mark an integration as verified (real implementation).
        
        Args:
            integration_name: Name of the verified integration
        """
        self._verified_integrations.add(integration_name)
    
    def get_status(self, integration_name: str) -> IntegrationStatus:
        """
        Get the status of an integration.
        
        Args:
            integration_name: Name of the integration
            
        Returns:
            Integration status
        """
        if integration_name in self._disabled_integrations:
            return IntegrationStatus.DISABLED
        elif integration_name in self._verified_integrations:
            return IntegrationStatus.AVAILABLE
        elif integration_name in self._enabled_integrations:
            return IntegrationStatus.AVAILABLE
        else:
            return IntegrationStatus.UNAVAILABLE
    
    def get_all_disabled(self) -> Set[str]:
        """Get all disabled integrations."""
        return self._disabled_integrations.copy()
    
    def get_all_enabled(self) -> Set[str]:
        """Get all enabled integrations."""
        return self._enabled_integrations.copy()
    
    def get_all_verified(self) -> Set[str]:
        """Get all verified integrations."""
        return self._verified_integrations.copy()


# Global integration manager instance
_global_integration_manager = None


def get_integration_manager() -> IntegrationManager:
    """Get or create the global integration manager instance."""
    global _global_integration_manager
    if _global_integration_manager is None:
        _global_integration_manager = IntegrationManager()
    return _global_integration_manager


def is_integration_enabled(integration_name: str) -> bool:
    """
    Convenience function to check if an integration is enabled.
    
    Args:
        integration_name: Name of the integration function
        
    Returns:
        True if integration is enabled, False otherwise
    """
    manager = get_integration_manager()
    return manager.is_integration_enabled(integration_name)


def safe_integration_call(integration_name: str, integration_func, *args, **kwargs):
    """
    Safely call an integration with checks.
    
    Args:
        integration_name: Name of the integration
        integration_func: The integration function to call
        *args: Arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function
        
    Returns:
        Result from integration function, or error dict if disabled
    """
    manager = get_integration_manager()
    
    if not manager.is_integration_enabled(integration_name):
        print(f"[WARNING] Integration '{integration_name}' is DISABLED - cannot be used in production")
        return {
            "status": "DISABLED",
            "error": f"Integration '{integration_name}' is disabled",
            "integration_name": integration_name
        }
    
    try:
        result = integration_func(*args, **kwargs)
        
        # Check if result is MOCKED
        if isinstance(result, dict) and result.get("status") == "MOCKED":
            print(f"[WARNING] Integration '{integration_name}' returned MOCKED data - treating as DISABLED")
            manager.disable_integration(integration_name)
            return {
                "status": "DISABLED",
                "error": f"Integration '{integration_name}' returned MOCKED data",
                "integration_name": integration_name
            }
        
        return result
    except Exception as e:
        print(f"[ERROR] Integration '{integration_name}' failed: {e}")
        return {
            "status": "ERROR",
            "error": str(e),
            "integration_name": integration_name
        }
