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


#!/usr/bin/env python3
# Copyright (C) 2015-2026 Nautech Systems Pty Ltd. All rights reserved.
# Licensed under the GNU Lesser General Public License Version 3.0.
# See https://www.gnu.org/licenses/lgpl-3.0.en.html for license details.
"""
Check the network-pattern guard with safe and suspicious test snippets.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check_test_network import check, findings


def test_patterns() -> None:
    """
    Flag literal remote calls without flagging configuration or local mocks.
    """
    cases = [
        ('requests.get("https://api.exchange.com")', "non-local network call"),
        ('client.get(\n "https://api.exchange.com")', "non-local network call"),
        ('reqwest::get("https://api.exchange.com").await', "non-local network call"),
        ('connect_async("wss://api.exchange.com").await', "non-local network call"),
        ('socket.connect(("192.0.2.1", 443))', "non-local network call"),
        ('TcpStream::connect("[2001:db8::1]:443")', "non-local network call"),
        ('socket.connect(("::ffff:192.0.2.1", 443))', "non-local network call"),
        ('os.getenv("RUN_LIVE_TESTS")', "live-test switch"),
        ('std::env::var("VENUE_LIVE_TEST")', "live-test switch"),
        ('std::env::var("BLOCKCHAIN_FORK_TESTS")', "live-test switch"),
        ('std::env::var("BLOCKCHAIN_FORK_RPC_URL")', "fork-RPC option"),
        ('command.arg("--fork-url")', "fork-RPC option"),
        ("anvil.fork_url(endpoint)", "fork-RPC option"),
        ('requests.get("http://127.0.0.1:8080")', None),
        ('TcpStream::connect("[::1]:8080")', None),
        ('socket.connect(("localhost", 8080))', None),
        ('client.get("https://fixture.invalid")', None),
        ('client.get("https://example.com")', None),
        ('endpoint = "https://api.exchange.com"', None),
        ('assert_eq!(url, "https://api.exchange.com");', None),
        ('// reqwest::get("https://api.exchange.com")', None),
        ('# requests.get("https://api.exchange.com")', None),
        ("VenueHttpClient::default()", None),
        ('client.connect("test_bearer_token")', None),
        ("requests.get(endpoint)", None),
    ]
    for source, expected in cases:
        assert [rule for _, rule in findings(source)] == ([] if expected is None else [expected]), (
            source
        )


def test_discovery() -> None:
    """
    Cover test files and inline Rust modules while excluding production code.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        files = {
            "crates/probe/src/lib.rs": 'reqwest::get("https://api.exchange.com");\n',
            "crates/probe/src/client.rs": '#[cfg(test)]\nmod tests {\nreqwest::get("https://api.exchange.com");\n}',
            "crates/probe/src/legacy.rs": '#[cfg(test)]\nmod test {\nreqwest::get("https://api.exchange.com");\n}',
            "crates/probe/tests/http.rs": 'reqwest::get("https://api.exchange.com");',
            "python/tests/test_http.py": 'requests.get("https://api.exchange.com")',
        }
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        expected = [
            "crates/probe/src/client.rs:3: non-local network call",
            "crates/probe/src/legacy.rs:3: non-local network call",
            "crates/probe/tests/http.rs:1: non-local network call",
            "python/tests/test_http.py:1: non-local network call",
        ]
        assert check(root) == expected
        script = root / "scripts/ci/check_test_network.py"
        script.parent.mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name(script.name), script)
        result = subprocess.run(
            [sys.executable, "-B", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert result.stderr.splitlines() == expected


if __name__ == "__main__":
    test_patterns()
    test_discovery()
    print("Network pattern checks passed")
