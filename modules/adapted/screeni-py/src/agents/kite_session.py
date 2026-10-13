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
KiteMCPSession — persistent Kite MCP session manager.

The Kite MCP login flow requires the MCP session to stay open between:
  1. Calling the `login` tool (which returns a browser URL)
  2. The user completing browser auth
  3. Subsequent tool calls (get_ltp, get_quotes, etc.)

This module manages a background thread + event loop that keeps the MCP
server connected across multiple agent invocations, so the session_id
in the login URL remains valid until the user completes auth.
"""
import asyncio
import contextlib
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_SESSION_LOCK = threading.Lock()
_SESSION: Optional["KiteMCPSession"] = None


class KiteMCPSession:
    """
    Persistent holder for a connected MCPServerStreamableHttp instance.
    Runs its own daemon thread + event loop so the session stays alive
    across multiple synchronous call sites (e.g., Streamlit reruns).
    """

    def __init__(self, url: str):
        self.url = url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server = None  # MCPServerStreamableHttp instance
        self._connected = False
        self._login_url: str | None = None
        self._ready_event = threading.Event()
        self._error: Exception | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        """Spin up the background event loop and connect to MCP."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="kite-mcp-loop")
        self._thread.start()
        # Wait up to 15 s for the connect to complete
        if not self._ready_event.wait(timeout=15):
            raise TimeoutError("Kite MCP connect timed out")
        if self._error:
            raise self._error

    def stop(self):
        """Disconnect and shut down the background loop."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._cleanup(), self._loop).result(timeout=10)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect())
            # Keep the loop running (servicing keep-alive pings etc.)
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _connect(self):
        try:
            # Import lazily — avoids breaking if openai-agents absent.
            # First try the real agents reference cached by screeni_agent.py;
            # fall back to the site-packages import dance.
            import importlib as _il
            import sys as _sys

            _real = _sys.modules.get("_screenipy_openai_agents_real")
            if _real is not None:
                _mcp_mod = _il.import_module("agents.mcp")
                _mcp_mod = _real.mcp
            else:
                import site as _site

                _sp = [p for p in _site.getsitepackages() if __import__("os").path.exists(p)]
                _our = _sys.modules.pop("agents", None)
                _our_mcp = _sys.modules.pop("agents.mcp", None)
                for p in _sp:
                    _sys.path.insert(0, p)
                try:
                    _il.import_module("agents")
                    _mcp_mod = _il.import_module("agents.mcp")
                finally:
                    for p in _sp:
                        with contextlib.suppress(ValueError):
                            _sys.path.remove(p)
                    if _our is not None:
                        _sys.modules["agents"] = _our
                    else:
                        _sys.modules.pop("agents", None)
                    if _our_mcp is not None:
                        _sys.modules["agents.mcp"] = _our_mcp
            MCPServerStreamableHttp = _mcp_mod.MCPServerStreamableHttp
            MCPServerStreamableHttpParams = _mcp_mod.MCPServerStreamableHttpParams

            self._server = MCPServerStreamableHttp(MCPServerStreamableHttpParams({"url": self.url}))
            await self._server.connect()
            self._connected = True
            logger.info(f"Kite MCP session connected: {self.url}")
        except Exception as e:
            self._error = e
            logger.error(f"Kite MCP connect failed: {e}")
        finally:
            self._ready_event.set()

    async def _cleanup(self):
        if self._server:
            with contextlib.suppress(Exception):
                await self._server.cleanup()
        self._connected = False
        if self._loop and self._loop.is_running():
            self._loop.stop()

    # ── public API ─────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def server(self):
        """The live MCPServerStreamableHttp instance (for passing to Agent)."""
        return self._server

    def get_login_url(self) -> str | None:
        """
        Call the Kite `login` MCP tool synchronously and return the URL.
        The session stays open so the session_id in the URL remains valid.
        """
        if not self._connected or not self._loop:
            raise RuntimeError("Session not connected. Call start() first.")
        future = asyncio.run_coroutine_threadsafe(self._call_login(), self._loop)
        return future.result(timeout=30)

    async def _call_login(self) -> str:
        """Invoke the MCP login tool and extract the URL from the response."""
        try:
            result = await self._server.call_tool("login", {})
            # CallToolResult has a .content list of TextContent items
            if result.content:
                return result.content[0].text
            return str(result)
        except Exception as e:
            logger.error(f"Kite login tool call failed: {e}")
            raise

    def run_agent_query(self, agent, query: str, sql_session=None) -> str:
        """
        Run an openai-agents Agent query inside this session's event loop
        so it shares the already-authenticated MCP server connection.
        Pass a SQLiteSession for multi-turn conversation history.
        """
        if not self._connected or not self._loop:
            raise RuntimeError("Session not connected.")
        future = asyncio.run_coroutine_threadsafe(
            self._run_agent(agent, query, sql_session=sql_session), self._loop
        )
        return future.result(timeout=300)

    async def _run_agent(self, agent, query: str, sql_session=None) -> str:
        try:
            import importlib as _il
            import site as _site
            import sys as _sys

            _sp = [p for p in _site.getsitepackages() if __import__("os").path.exists(p)]
            _our = _sys.modules.pop("agents", None)
            for p in _sp:
                _sys.path.insert(0, p)
            try:
                _agents = _il.import_module("agents")
                Runner = _agents.Runner
            finally:
                for p in _sp:
                    with contextlib.suppress(ValueError):
                        _sys.path.remove(p)
                if _our is not None:
                    _sys.modules["agents"] = _our
                else:
                    _sys.modules.pop("agents", None)

            run_kwargs = {}
            if sql_session is not None:
                run_kwargs["session"] = sql_session
            result = await Runner.run(agent, query, **run_kwargs)
            return result.final_output
        except Exception as e:
            logger.error(f"Agent run in Kite session failed: {e}")
            return f"Error: {e}"


# ── module-level singleton helpers ─────────────────────────────────────────────


def get_or_create_session(url: str = "https://mcp.kite.trade/mcp") -> "KiteMCPSession":
    """Return the existing live session or create a new one."""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None or not _SESSION.is_connected:
            if _SESSION is not None:
                with contextlib.suppress(Exception):
                    _SESSION.stop()
            _SESSION = KiteMCPSession(url)
            _SESSION.start()
        return _SESSION


def clear_session():
    """Tear down the singleton session (e.g., on logout)."""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None:
            with contextlib.suppress(Exception):
                _SESSION.stop()
            _SESSION = None
