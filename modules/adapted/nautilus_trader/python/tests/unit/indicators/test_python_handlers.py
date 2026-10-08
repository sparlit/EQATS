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


# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2026 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Test python handlers behavior.
"""

import re
from pathlib import Path

PY_HANDLE = re.compile(
    r"fn\s+(py_handle_(?:quote_tick|trade_tick|bar|book|delta|deltas|depth))\s*\(",
)

EXPECTED_DELEGATE = {
    "py_handle_quote_tick": "self.handle_quote(",
    "py_handle_trade_tick": "self.handle_trade(",
    "py_handle_bar": "self.handle_bar(",
    "py_handle_book": "self.handle_book(",
    "py_handle_delta": "self.handle_delta(",
    "py_handle_deltas": "self.handle_deltas(",
    "py_handle_depth": "self.handle_depth(",
}


def test_python_indicator_handlers_delegate_to_rust_core() -> None:
    """
    Test python indicator handlers delegate to rust core.
    """
    # Arrange
    rust_source = Path(__file__).resolve().parents[4] / "crates" / "indicators" / "src" / "python"
    handlers = 0
    failures: list[str] = []

    # Act
    assert rust_source.is_dir()

    for file_path in sorted(rust_source.rglob("*.rs")):
        source = file_path.read_text(encoding="utf-8")
        for match in PY_HANDLE.finditer(source):
            handlers += 1
            function_name = match.group(1)
            body = _function_body(source, match.end())
            expected_delegate = EXPECTED_DELEGATE[function_name]
            if expected_delegate not in body:
                failures.append(f"{file_path.relative_to(rust_source)}::{function_name}")

    # Assert
    assert handlers > 0
    assert failures == []


def _function_body(source: str, signature_end: int) -> str:
    body_start = source.find("{", signature_end)
    assert body_start >= 0

    depth = 0

    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[body_start + 1 : index]

    raise AssertionError("unterminated Rust function body")
