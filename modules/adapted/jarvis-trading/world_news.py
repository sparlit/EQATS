"""
Geocoded world-news markers for the AXIOM globe/flat map.

GDELT's geo API is unreliable from cloud IPs, so we geocode our own RSS headlines
against a built-in gazetteer (countries + major financial cities). Free, no API
key, works anywhere. Returns aggregated points with the matching headlines.
"""
from __future__ import annotations

import re

from loguru import logger

# name (+ aliases) -> (lat, lng). Whole-word, case-insensitive match on headlines.
GAZETTEER: dict[str, tuple[float, float]] = {
    # financial cities (checked first — more specific)
    "new york": (40.71, -74.0), "wall street": (40.71, -74.0), "washington": (38.9, -77.04),
    "london": (51.51, -0.13), "frankfurt": (50.11, 8.68), "paris": (48.85, 2.35),
    "tokyo": (35.68, 139.69), "hong kong": (22.32, 114.17), "shanghai": (31.23, 121.47),
    "singapore": (1.35, 103.82), "mumbai": (19.07, 72.87), "delhi": (28.61, 77.21),
    "dubai": (25.2, 55.27), "moscow": (55.75, 37.62), "seoul": (37.57, 126.98),
    "beijing": (39.9, 116.4), "sydney": (-33.87, 151.21), "zurich": (47.37, 8.54),
    # countries / regions
    "united states": (38.0, -97.0), "u.s.": (38.0, -97.0), "usa": (38.0, -97.0), "america": (38.0, -97.0),
    "china": (35.86, 104.2), "india": (22.0, 79.0), "japan": (36.2, 138.25), "russia": (61.5, 105.3),
    "ukraine": (48.38, 31.17), "germany": (51.17, 10.45), "france": (46.6, 1.89), "italy": (41.87, 12.57),
    "spain": (40.46, -3.75), "united kingdom": (55.38, -3.44), "u.k.": (55.38, -3.44), "britain": (55.38, -3.44),
    "iran": (32.43, 53.69), "israel": (31.05, 34.85), "gaza": (31.5, 34.47), "saudi arabia": (23.89, 45.08),
    "turkey": (38.96, 35.24), "brazil": (-14.24, -51.93), "canada": (56.13, -106.35), "mexico": (23.63, -102.55),
    "australia": (-25.27, 133.78), "south korea": (35.91, 127.77), "north korea": (40.34, 127.51),
    "taiwan": (23.7, 120.96), "pakistan": (30.38, 69.35), "indonesia": (-0.79, 113.92), "nigeria": (9.08, 8.68),
    "south africa": (-30.56, 22.94), "egypt": (26.82, 30.8), "argentina": (-38.42, -63.62), "europe": (54.0, 15.0),
    "eurozone": (50.0, 10.0), "switzerland": (46.82, 8.23), "netherlands": (52.13, 5.29), "vietnam": (14.06, 108.28),
    "thailand": (15.87, 100.99), "venezuela": (6.42, -66.59), "qatar": (25.35, 51.18), "iraq": (33.22, 43.68),
    "syria": (34.8, 38.99), "yemen": (15.55, 48.52), "greece": (39.07, 21.82), "poland": (51.92, 19.15),
}
# longest names first so "new york" matches before "york", "south korea" before "korea"
_KEYS = sorted(GAZETTEER.keys(), key=len, reverse=True)


def geocode_news(limit_headlines: int = 60) -> dict:
    from data.news_feed import fetch_market_news

    try:
        items = fetch_market_news(limit_headlines)
    except Exception as exc:
        logger.warning("world-news fetch failed: {}", exc)
        return {"available": False, "points": []}

    agg: dict[tuple[float, float], dict] = {}
    for it in items:
        title = (it.get("title") if isinstance(it, dict) else getattr(it, "title", "")) or ""
        low = title.lower()
        seen: set[tuple[float, float]] = set()
        for key in _KEYS:
            if re.search(r"\b" + re.escape(key) + r"\b", low):
                coord = GAZETTEER[key]
                if coord in seen:
                    continue
                seen.add(coord)
                slot = agg.setdefault(coord, {"lat": coord[0], "lng": coord[1], "place": key.title(), "count": 0, "headlines": []})
                slot["count"] += 1
                if len(slot["headlines"]) < 5:
                    slot["headlines"].append(title[:140])
                break  # one (most specific) place per headline
    points = sorted(agg.values(), key=lambda p: p["count"], reverse=True)
    return {"available": bool(points), "count": len(points), "points": points}
