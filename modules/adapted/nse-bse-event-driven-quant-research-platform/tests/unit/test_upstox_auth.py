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


"""Upstox auth CLI tests (offline; network calls mocked)."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import upstox_auth  # noqa: E402


class TestLoginUrl:
    def test_url_contains_encoded_params(self):
        url = upstox_auth.build_login_url("test-key-1234", "https://280f95af306b.ngrok-free.app")
        assert url.startswith(upstox_auth.LOGIN_DIALOG_URL + "?")
        assert "response_type=code" in url
        assert "client_id=test-key-1234" in url
        assert "redirect_uri=https%3A%2F%2F280f95af306b.ngrok-free.app" in url


class TestExtractCode:
    def test_from_full_redirect_url(self):
        pasted = "https://280f95af306b.ngrok-free.app/?code=eyJ0eXAiOiJKV1QiLCJ9&state=x"
        assert upstox_auth.extract_code(pasted) == "eyJ0eXAiOiJKV1QiLCJ9"

    def test_bare_code_passthrough(self):
        assert upstox_auth.extract_code("aB3dEf7hJk9Lm") == "aB3dEf7hJk9Lm"

    def test_garbage_rejected(self):
        with pytest.raises(SystemExit):
            upstox_auth.extract_code("https://no-code-here.com/?foo=1")


class TestTokenFile:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(upstox_auth, "TOKEN_FILE", tmp_path / "upstox_tokens.json")
        monkeypatch.setattr(upstox_auth, "ENV_FILE", tmp_path / ".env")
        payload = {"access_token": "SECRET_TOKEN_123456", "expires_at": 123}
        upstox_auth.save_token_file(payload)
        loaded = json.loads((tmp_path / "upstox_tokens.json").read_text())
        assert loaded["access_token"] == "SECRET_TOKEN_123456"
        env_text = (tmp_path / ".env").read_text()
        assert "UPSTOX_ACCESS_TOKEN=SECRET_TOKEN_123456" in env_text

    def test_get_valid_token_prefers_cached(self, tmp_path, monkeypatch):
        monkeypatch.setattr(upstox_auth, "TOKEN_FILE", tmp_path / "t.json")
        (tmp_path / "t.json").write_text(json.dumps({"access_token": "CACHED"}))
        assert upstox_auth.get_valid_access_token() == "CACHED"

    def test_get_valid_token_refreshes_when_only_refresh_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(upstox_auth, "TOKEN_FILE", tmp_path / "t.json")
        (tmp_path / "t.json").write_text(
            json.dumps({"access_token": "", "extended_token": "REFRESH_ME"})
        )
        monkeypatch.setattr(upstox_auth, "get_creds", lambda overrides=None: ("K", "S", "R"))
        monkeypatch.setattr(
            upstox_auth,
            "refresh_tokens",
            lambda **kw: {"access_token": "ROTATED"},
        )
        assert upstox_auth.get_valid_access_token() == "ROTATED"

    def test_no_tokens_exits_with_message(self, tmp_path, monkeypatch):
        monkeypatch.setattr(upstox_auth, "TOKEN_FILE", tmp_path / "missing.json")
        with pytest.raises(SystemExit):
            upstox_auth.get_valid_access_token()


class TestExchangeAndProfile:
    def test_exchange_posts_form_and_saves(self, tmp_path, monkeypatch):
        monkeypatch.setattr(upstox_auth, "TOKEN_FILE", tmp_path / "t.json")
        monkeypatch.setattr(upstox_auth, "ENV_FILE", tmp_path / ".env")

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "NEW_TOKEN_987654"})

        payload = upstox_auth.exchange_code(
            "MYCODE",
            api_key="K",
            api_secret="S",
            redirect_uri="R",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        assert payload["access_token"] == "NEW_TOKEN_987654"
        assert "grant_type=authorization_code" in captured["body"]
        assert "code=MYCODE" in captured["body"]
        assert (tmp_path / "t.json").exists()

    def test_exchange_failure_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(upstox_auth, "TOKEN_FILE", tmp_path / "t.json")
        monkeypatch.setattr(upstox_auth, "ENV_FILE", tmp_path / ".env")
        handler = lambda request: httpx.Response(400, text="bad code")  # noqa: E731
        with pytest.raises(SystemExit):
            upstox_auth.exchange_code(
                "BAD",
                api_key="K",
                api_secret="S",
                redirect_uri="R",
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )

    def test_whoami_parses_profile(self):
        handler = lambda request: httpx.Response(  # noqa: E731
            200, json={"user_id": "2EBWYN", "user_name": "POLA NARAMMA"}
        )
        profile = upstox_auth.whoami(
            "TOK", http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        assert profile["user_name"] == "POLA NARAMMA"

    def test_masking_hides_long_tokens(self):
        out = upstox_auth.masked({"access_token": "VERYLONGSECRETTOKEN123"})
        assert "VERYLONGSECRETTOKEN123" not in str(out)
