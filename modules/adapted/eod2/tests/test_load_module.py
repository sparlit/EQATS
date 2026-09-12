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


import tempfile
import unittest
from pathlib import Path
from types import ModuleType

import pytest
from context import defs

dir = Path(__file__).parent

code = """class Test:
    def foo(self):
        return "bar"
"""


class TestGetModule(unittest.TestCase):
    def setUp(self) -> None:
        self.fname = dir / "mod_test.py"
        self.fname.write_text(code)

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(code)
            self.tmp_file = Path(f.name)

    def tearDown(self) -> None:
        self.fname.unlink()
        self.tmp_file.unlink()

    def test_without_class(self):
        """Load a module without Class"""

        module = defs.load_module(str(self.fname))
        assert isinstance(module, ModuleType)
        assert module.__name__ == self.fname.stem

    def test_with_class(self):
        """Load a module specifying the class. Returns the class"""

        module = defs.load_module(f"{self.fname}|Test")
        assert isinstance(module, type)
        assert module.__name__ == "Test"
        assert module().foo() == "bar"

    def test_with_nonexistent_module(self):
        """Passing a nonexistent_module raises FileNotFoundError"""

        with pytest.raises(FileNotFoundError):
            defs.load_module("nonexistent_module.py")

    def test_with_nonexistent_class(self):
        """Passing a non existent class raises AttributeError"""

        with pytest.raises(AttributeError):
            defs.load_module(f"{self.fname}|NonexistentClass")

    def test_loading_from_any_directory(self):
        """Module can be loaded from any directory even outside of project root"""

        module = defs.load_module(f"{self.tmp_file}|Test")
        assert isinstance(module, type)
        assert module.__name__ == "Test"


if __name__ == "__main__":
    unittest.main()
