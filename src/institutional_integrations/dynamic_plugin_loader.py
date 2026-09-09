"""
Dynamic Microkernel Plugin Loader Engine
========================================
Scans `modules/adapted/` and `src/institutional_integrations/` to auto-discover
and dynamically register trading strategies, broker adapters, and risk engines into
`IndianBrokerPluginRegistry` at runtime.
"""

import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List

from institutional_integrations.sebi_broker_adapter import (
    SEBIBrokerAdapter,
    IndianBrokerPluginRegistry,
)

logger = logging.getLogger(__name__)


class DynamicPluginLoader:
    """
    Automated Runtime Plugin Discovery & Microkernel Registration Loader.
    """

    def __init__(self, search_paths: List[Path] | None = None) -> None:
        root = Path.cwd()
        self.search_paths = search_paths or [
            root / "modules" / "adapted",
            root / "src" / "institutional_integrations",
        ]
        self.loaded_modules: Dict[str, Any] = {}
        self.registered_plugins: List[str] = []

    def discover_and_load_plugins(self) -> Dict[str, Any]:
        """
        Scans search_paths, dynamically imports Python files, and registers SEBIBrokerAdapter subclasses.
        Safely catches exceptions and SystemExit to prevent dynamic scripts from terminating the runtime.
        """
        for search_path in self.search_paths:
            if not search_path.exists():
                continue

            for py_file in search_path.glob("**/*.py"):
                if py_file.name.startswith("__") or py_file.name.startswith("."):
                    continue

                mod_name = f"dynamic_plugin_{py_file.stem}_{hash(str(py_file)) & 0xFFFFFFFF}"
                try:
                    spec = importlib.util.spec_from_file_location(mod_name, py_file)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[mod_name] = module
                        spec.loader.exec_module(module)
                        self.loaded_modules[mod_name] = module

                        # Discover SEBIBrokerAdapter subclasses
                        for name, obj in inspect.getmembers(module, inspect.isclass):
                            try:
                                if issubclass(obj, SEBIBrokerAdapter) and obj is not SEBIBrokerAdapter:
                                    plugin_key = getattr(obj, "BROKER_KEY", name.upper())
                                    IndianBrokerPluginRegistry.register(plugin_key, obj)
                                    self.registered_plugins.append(plugin_key)
                            except Exception:
                                continue

                except (Exception, SystemExit, BaseException) as err:
                    logger.debug(f"Skipping dynamic module load for {py_file.name}: {err}")

        return {
            "loaded_modules_count": len(self.loaded_modules),
            "registered_plugins_count": len(self.registered_plugins),
            "registered_plugins": self.registered_plugins,
        }


# Single global instance for microkernel startup
global_plugin_loader = DynamicPluginLoader()


def initialize_dynamic_plugins() -> Dict[str, Any]:
    """Convenience function to trigger dynamic plugin discovery."""
    return global_plugin_loader.discover_and_load_plugins()
