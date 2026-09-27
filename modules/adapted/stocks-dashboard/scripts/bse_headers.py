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


# -*- coding: utf-8 -*-
"""The one header set every BSE request carries (runbook §181, 2026-09-26).

From 20-Sep-2026 BSE's front door answered 403 "Access Denied" to any request that carried only a User-Agent (+Referer):
seven daily jobs went dark for six days while staying green. A request carrying the full STANDARD header set a browser
sends (Accept-Language, Referer) is served normally. Since 2026-09-26 22:55 IST the set is HONEST: our own User-Agent,
no browser impersonation (no Chrome UA / sec-ch-ua / Sec-Fetch-*) -- measured 200 on every endpoint the repo uses.

Importing this module installs the headers on every urllib request to *.bseindia.com that lacks them (OpenerDirector.open
is wrapped, so urlopen / build_opener / cookie openers are all covered). curl callers splice CURL_ARGS after "-A UA".
"""
import urllib.request
from urllib.parse import urlsplit

# HONEST identification (2026-09-26 22:55 IST, measured): BSE serves a script that names itself, provided the request
# carries Accept-Language and Referer (UA-only -> 403; no Referer -> 404; no Accept-Language -> 403). No browser
# impersonation: no Chrome User-Agent, no sec-ch-ua*, no Sec-Fetch-*, no Origin. Never add those back. (A UA carrying a
# URL, "+https://...", is refused 403 -- measured; keep the plain name.)
UA = "stocks-dashboard-research/1.0"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Connection": "keep-alive",
}
# curl sends NO Accept-Encoding by default and BSE refuses such a request (measured: identical headers, 403 without
# --compressed, 200 with it); urllib always sends "Accept-Encoding: identity", which is why it passed. --compressed also
# makes curl decompress the body itself, so callers keep receiving plain bytes.
CURL_ARGS = ["--compressed"]
for _k, _v in HEADERS.items():
    if _k != "User-Agent":
        CURL_ARGS += ["-H", f"{_k}: {_v}"]


def is_bse(url):
    try:
        return urlsplit(url).hostname.lower().endswith("bseindia.com")
    except Exception:
        return False


def complete(req):
    """Add every standard header the request lacks; replace any browser-impersonating one the caller set (own UA)."""
    if isinstance(req, urllib.request.Request) and is_bse(req.full_url):
        for store in (req.headers, req.unredirected_hdrs):
            for k in list(store):
                kl = k.lower()
                if kl in {"user-agent", "origin"} or kl.startswith(("sec-ch-ua", "sec-fetch-")):
                    del store[k]
        have = {k.lower() for k in req.headers} | {k.lower() for k in req.unredirected_hdrs}
        for k, v in HEADERS.items():
            if k.lower() not in have:
                req.add_header(k, v)
    return req


def install():
    if getattr(urllib.request.OpenerDirector, "_bse_headers_installed", False):
        return
    _open = urllib.request.OpenerDirector.open

    def open_(self, fullurl, data=None, timeout=urllib.request.socket._GLOBAL_DEFAULT_TIMEOUT):
        if isinstance(fullurl, str) and is_bse(fullurl):
            fullurl = urllib.request.Request(fullurl)
        return _open(self, complete(fullurl), data, timeout)

    urllib.request.OpenerDirector.open = open_
    urllib.request.OpenerDirector._bse_headers_installed = True


install()


# ---- plain GET for callers that used curl_cffi impersonate="chrome" (2026-09-27, runbook §190) -------------------------
# curl_cffi bypasses urllib, so importing this module never reached those requests: they kept posing as Chrome. BH.get /
# BH.Session are drop-in stand-ins with the requests-shaped surface those callers read (status_code, text, content,
# json(), headers). HTTP errors come back as a response (like requests/curl_cffi), network errors raise.
class Response:
    def __init__(self, status_code, content, headers=None, url=""):
        self.status_code, self.content, self.headers, self.url = status_code, content, dict(headers or {}), url
        self.ok = 200 <= status_code < 400

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def json(self):
        import json

        return json.loads(self.text)


class Session:
    """Cookie-keeping GET session (replaces curl_cffi.requests.Session(impersonate="chrome")); honest headers via install()."""

    def __init__(self, **_ignored):  # impersonate= and friends are accepted and IGNORED
        import http.cookiejar

        self.headers = {}
        self._op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, url, headers=None, timeout=60, params=None, **_ignored):
        import urllib.error
        from urllib.parse import urlencode

        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        h = dict(self.headers)
        h.update(headers or {})
        req = urllib.request.Request(url, headers=h)
        try:
            with self._op.open(req, timeout=timeout) as r:
                return Response(r.status, r.read(), r.headers, r.geturl())
        except urllib.error.HTTPError as e:
            return Response(e.code, e.read() or b"", e.headers, url)


def get(url, headers=None, timeout=60, **kw):
    """One plain GET (replaces curl_cffi.requests.get(..., impersonate="chrome")); impersonate= is ignored."""
    return Session().get(url, headers=headers, timeout=timeout, **kw)
