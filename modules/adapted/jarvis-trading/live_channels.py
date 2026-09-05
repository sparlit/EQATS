"""
Live-status check for the dashboard's Live-TV card.

The video embeds are cross-origin, so the browser can't tell which channel is
actually broadcasting. We check each channel's YouTube /live page server-side
(no API key) for live-stream signals, so the UI can auto-pick a live channel.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests
from loguru import logger

_CANON = re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"')
_OGURL = re.compile(r'<meta property="og:url" content="https://www\.youtube\.com/watch\?v=([\w-]{11})"')
_VIDID = re.compile(r'"videoId":"([\w-]{11})"')
_VIDPATS = (_CANON, _OGURL, _VIDID)
_EMBED = re.compile(r'"playableInEmbed":(true|false)')
_STATUS = re.compile(r'"playabilityStatus":\{"status":"([A-Z_]+)"')

# name, channelId — kept in sync with the frontend card
CHANNELS = [
    ("Zee Business", "UCkXopQ3ubd-rnXnStZqCl2w"),
    ("CNBC-TV18", "UCmRbHAgG2k2vDUvb3xsEunQ"),
    ("ET Now", "UCI_mwTKUhicNzFrhm33MzBQ"),
    ("Bloomberg TV", "UCIALMKvObZNtJ6AmdCLP7Lg"),
    ("CNBC Intl", "UCF8HUTbUwPKh2Q-KpGOCVGw"),
    ("CNBC", "UCvJJ_dzjViJCoLf5uKUTwoA"),
    ("Yahoo Finance", "UCEAZeUIeJs0IjQiqTCdVSIg"),
]
_H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    # consent-accepted cookies to skip YouTube's EU/datacenter consent interstitial
    "Cookie": "SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg; CONSENT=YES+cb",
}
_LIVE_URL = "https://www.youtube.com/channel/{cid}/live?gl=US&hl=en&persist_gl=1&persist_hl=1"


def _check(cid: str) -> tuple[bool, str | None]:
    """Return (playable_live, live_video_id). Playable = currently live, embeddable
    and status OK — so the UI only offers channels that actually play in an iframe."""
    try:
        r = requests.get(_LIVE_URL.format(cid=cid), headers=_H, timeout=10)
        if r.status_code != 200:
            return (False, None)
        t = r.text
        is_live = ("hlsManifestUrl" in t) or ('"isLive":true' in t)
        if not is_live:
            return (False, None)
        emb = _EMBED.search(t)
        st = _STATUS.search(t)
        if (emb and emb.group(1) == "false") or (st and st.group(1) != "OK"):
            return (False, None)
        vid = None
        for pat in _VIDPATS:
            m = pat.search(t)
            if m:
                vid = m.group(1)
                break
        # live & playable; embed by video id when we could resolve it, else the
        # channel live_stream form (handled in the frontend) is the fallback.
        return (True, vid)
    except Exception as exc:
        logger.debug("live check failed for {}: {}", cid, exc)
        return (False, None)


def _check_api(cid: str, key: str) -> tuple[bool, str | None]:
    """Reliable live detection via YouTube Data API v3 (works from any IP).
    search.list eventType=live → the channel's current live video, if any.
    Falls back to the scrape check if the API errors (e.g. quota exhausted)."""
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part": "id", "channelId": cid, "eventType": "live",
                    "type": "video", "maxResults": 1, "key": key},
            timeout=10,
        )
        if r.status_code != 200:
            logger.debug("YT API {} for {}: {}", r.status_code, cid, r.text[:120])
            return _check(cid)
        items = r.json().get("items", [])
        if not items:
            return (False, None)
        vid = items[0].get("id", {}).get("videoId")
        return (bool(vid), vid)
    except Exception as exc:
        logger.debug("YT API check failed for {}: {}", cid, exc)
        return _check(cid)


def live_channels() -> dict:
    key = os.getenv("YOUTUBE_API_KEY")
    check = (lambda cid: _check_api(cid, key)) if key else _check
    try:
        with ThreadPoolExecutor(max_workers=7) as ex:
            results = list(ex.map(lambda c: (c[0], c[1], *check(c[1])), CHANNELS))
    except Exception:
        results = [(n, i, False, None) for n, i in CHANNELS]
    out = [{"name": n, "id": i, "live": live, "videoId": vid} for n, i, live, vid in results]
    # prefer a channel where we resolved a video id (reliable embed), else any live one
    first_live = next((c["id"] for c in out if c["live"] and c["videoId"]), None) \
        or next((c["id"] for c in out if c["live"]), None)
    return {"channels": out, "first_live": first_live}
