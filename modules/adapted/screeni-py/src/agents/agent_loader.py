import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
AgentLoader - Scans and loads persona YAML files for Screeni-py agents.
Personas are stored in src/agents/personas/*.yaml
"""
import glob
import logging
import os

import yaml

logger = logging.getLogger(__name__)

_PERSONAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personas")


class AgentLoader:
    """
    Loads agent persona configurations from YAML files.
    Personas define the agent's instructions, tools, and target index.
    """

    def __init__(self, personas_dir: str = None):
        """
        Initialize AgentLoader.

        Args:
            personas_dir: Directory containing persona YAML files.
                         Defaults to src/agents/personas/
        """
        self.personas_dir = personas_dir or _PERSONAS_DIR

    def list_personas(self) -> list[str]:
        """
        List all available persona names.

        Returns:
            List of persona names (from the 'name' field in YAML)
        """
        personas = self._load_all()
        return [p.get("name", os.path.basename(f)) for p, f in personas]

    def list_persona_files(self) -> list[str]:
        """List all persona YAML file paths."""
        pattern = os.path.join(self.personas_dir, "*.yaml")
        return sorted(glob.glob(pattern))

    def _load_all(self) -> list[tuple]:
        """Load all persona files as (config_dict, filepath) tuples."""
        results = []
        for filepath in self.list_persona_files():
            try:
                with open(filepath) as f:
                    config = yaml.safe_load(f)
                if config:
                    results.append((config, filepath))
            except Exception as e:
                logger.warning(f"Failed to load persona {filepath}: {e}")
        return results

    def load(self, name: str) -> dict | None:
        """
        Load a persona config by name.

        Matches against the 'name' field or filename (without extension).

        Args:
            name: Persona name (e.g., 'SwingTrader', 'swing_trader')

        Returns:
            Persona config dict or None if not found
        """
        name_lower = name.lower().replace("-", "_").replace(" ", "_")

        for config, filepath in self._load_all():
            # Try matching by name field
            config_name = config.get("name", "").lower().replace("-", "_").replace(" ", "_")
            # Try matching by filename
            file_name = os.path.splitext(os.path.basename(filepath))[0].lower()

            if config_name == name_lower or file_name == name_lower:
                return config

        # Case-insensitive partial match fallback
        for config, filepath in self._load_all():
            config_name = config.get("name", "").lower()
            if name_lower in config_name:
                return config

        logger.warning(f"Persona '{name}' not found in {self.personas_dir}")
        return None

    def load_all(self) -> list[dict]:
        """
        Load all persona configurations.

        Returns:
            List of persona config dicts
        """
        return [config for config, _ in self._load_all()]

    def summary(self) -> str:
        """Return a human-readable summary of available personas."""
        personas = self.load_all()
        if not personas:
            return "No personas found."
        lines = ["Available Agent Personas:", "=" * 40]
        for p in personas:
            name = p.get("name", "Unknown")
            desc = p.get("description", "No description")
            index = p.get("index", "Nifty 500")
            tools = ", ".join(p.get("tools", []))
            lines.append(f"\n  {name}")
            lines.append(f"    Description : {desc}")
            lines.append(f"    Default Index: {index}")
            lines.append(f"    Tools       : {tools}")
        return "\n".join(lines)
