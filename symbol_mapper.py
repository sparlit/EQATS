"""
Master Symbology Translation & Dynamic Discovery Engine.
Decouples internal application logic from broker-specific ticker conventions.
"""

import re
import database
from typing import Optional, Dict, Tuple

class SymbolMapper:
    """
    Translates between internal Master Symbology (e.g., EUR_USD, XAU_USD)
    and broker-specific identifiers (e.g., EURUSD.raw, CS.D.EURUSD.TODAY.IP, GOLD).

    Provides regex-based automatic discovery and contract size / pip scale inference.
    """

    # Common broker suffixes and prefixes to clean
    SUFFIX_PATTERN = re.compile(r'(\.raw|\.pro|_i|\.m|\.micro|\.ecn|\.stp|#.*|\.f|\.TODAY\.IP|\.IP)$', re.IGNORECASE)
    PREFIX_PATTERN = re.compile(r'^(CS\.D\.|FX_|CRYPTO_|SPOT_)', re.IGNORECASE)

    # Commodity and Crypto Alias Map to ISO standards
    ALIAS_MAP = {
        "GOLD": "XAU_USD",
        "SILVER": "XAG_USD",
        "OIL": "WTI_USD",
        "BRENT": "BRENT_USD",
        "BITCOIN": "BTC_USD",
        "ETHEREUM": "ETH_USD"
    }

    def __init__(self, default_broker_id: str = "PRIMARY_GATEWAY"):
        self.default_broker_id = default_broker_id

    def infer_master_symbol(self, broker_symbol: str) -> Tuple[str, float, float]:
        """
        Parses a raw broker symbol using regex to infer its Master Symbol, pip size, and contract size.

        Returns:
            Tuple[internal_symbol, pip_size, contract_size]
        """
        clean_symbol = broker_symbol.strip()

        # Check alias map first (e.g., GOLD -> XAU_USD)
        if clean_symbol.upper() in self.ALIAS_MAP:
            master = self.ALIAS_MAP[clean_symbol.upper()]
            pip_size = 0.01 if "XAU" in master or "GOLD" in master else 0.0001
            contract_size = 100.0 if "XAU" in master else 100000.0
            return master, pip_size, contract_size

        # Infer contract size based on micro/nano designations
        contract_size = 100000.0
        if ".micro" in clean_symbol.lower() or "micro" in clean_symbol.lower():
            contract_size = 1000.0
        elif ".mini" in clean_symbol.lower() or "mini" in clean_symbol.lower():
            contract_size = 10000.0

        # Strip prefixes and suffixes
        stripped = self.PREFIX_PATTERN.sub('', clean_symbol)
        stripped = self.SUFFIX_PATTERN.sub('', stripped)
        stripped = re.sub(r'[^A-Za-z0-9]', '', stripped).upper()

        # Handle 6-character forex pairs (e.g., EURUSD -> EUR_USD)
        if len(stripped) == 6 and stripped.isalpha():
            master_symbol = f"{stripped[:3]}_{stripped[3:]}"
        elif len(stripped) == 7 and stripped.startswith("XAU"):
            master_symbol = "XAU_USD"
        elif len(stripped) == 7 and stripped.startswith("XAG"):
            master_symbol = "XAG_USD"
        else:
            master_symbol = stripped if "_" in stripped else f"FX:{stripped}"

        # Infer pip size
        pip_size = 0.0001
        if "JPY" in master_symbol:
            pip_size = 0.01
        elif "XAU" in master_symbol or "GOLD" in master_symbol:
            pip_size = 0.01
        elif "XAG" in master_symbol or "SILVER" in master_symbol:
            pip_size = 0.001
        elif "BTC" in master_symbol or "ETH" in master_symbol:
            pip_size = 1.0

        return master_symbol, pip_size, contract_size

    def to_broker_symbol(self, internal_symbol: str, broker_id: Optional[str] = None) -> str:
        """
        Translates an internal Master Symbol (e.g. EUR_USD) to the target broker symbol.
        If no explicit mapping exists, falls back to stripped format (EURUSD).
        """
        target_broker = broker_id or self.default_broker_id
        mapped = database.get_broker_symbol(internal_symbol, target_broker)
        if mapped:
            return mapped

        # Fallback: EUR_USD -> EURUSD
        return internal_symbol.replace("_", "").replace("FX:", "").replace("CRYPTO:", "")

    def to_internal_symbol(self, broker_symbol: str, broker_id: Optional[str] = None) -> str:
        """
        Translates a broker symbol (e.g. EURUSD.raw) back to internal Master Symbology.
        If unmapped, infers and auto-registers the mapping dynamically.
        """
        target_broker = broker_id or self.default_broker_id
        mapped = database.get_internal_symbol(broker_symbol, target_broker)
        if mapped:
            return mapped

        # Auto-discover and register mapping
        master_symbol, pip_size, contract_size = self.infer_master_symbol(broker_symbol)
        database.add_symbol_mapping(
            internal_symbol=master_symbol,
            broker_id=target_broker,
            broker_symbol=broker_symbol,
            pip_size=pip_size,
            contract_size=contract_size
        )
        return master_symbol

    def auto_discover_and_map_instruments(self, broker_symbol_list: list, broker_id: Optional[str] = None) -> int:
        """
        Batch discovers and registers a list of tradable broker instruments.
        Returns count of newly registered or updated symbol mappings.
        """
        target_broker = broker_id or self.default_broker_id
        count = 0
        for broker_sym in broker_symbol_list:
            master_symbol, pip_size, contract_size = self.infer_master_symbol(broker_sym)
            success = database.add_symbol_mapping(
                internal_symbol=master_symbol,
                broker_id=target_broker,
                broker_symbol=broker_sym,
                pip_size=pip_size,
                contract_size=contract_size
            )
            if success:
                count += 1
        return count


# Global singleton instance
_global_symbol_mapper = None

def get_symbol_mapper(broker_id: str = "PRIMARY_GATEWAY") -> SymbolMapper:
    """Gets or creates the global SymbolMapper instance."""
    global _global_symbol_mapper
    if _global_symbol_mapper is None:
        _global_symbol_mapper = SymbolMapper(default_broker_id=broker_id)
    return _global_symbol_mapper
