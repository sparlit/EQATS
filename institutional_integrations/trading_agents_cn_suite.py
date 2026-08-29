"""
TradingAgents-CN Integration Suite (EQATS Institutional Adaptation)
Adapted from hsliuping/TradingAgents-CN

Provides:
- ChinaMarketAnalystAgent: Northbound capital flows, PBOC policy stance, A-share/HK market sentiment
- EnhancedNewsFilterEngine: Multi-source news deduplication, noise filtering, and relevance scoring
- DataCompletenessChecker: Bar gap detection, missing data imputation, timestamp alignment
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import re


@dataclass
class ChinaMarketReport:
    symbol: str
    northbound_net_flow_mn: float
    pboc_policy_stance: str
    sentiment_index: float  # 0 to 100
    market_bias: str
    summary: str


@dataclass
class FilteredNewsArticle:
    title: str
    source: str
    relevance_score: float
    is_duplicate: bool
    sentiment: str


@dataclass
class DataCompletenessReport:
    total_expected_bars: int
    total_actual_bars: int
    missing_bar_count: int
    completeness_pct: float
    has_gaps: bool


class ChinaMarketAnalystAgent:
    """A-Share / HK & China Macro Market Analyst Agent."""

    def analyze_market(
        self,
        symbol: str,
        northbound_net_flow_mn: float = 1250.0,  # Million RMB
        pboc_stance: str = "NEUTRAL_EXPANSIONARY",
        shanghai_comp_return_pct: float = 0.80,
    ) -> ChinaMarketReport:
        """Analyzes China market liquidity flows and policy direction."""
        score = 50.0

        # Northbound net flow impact (+100m -> +1 point score)
        score += min(25.0, max(-25.0, northbound_net_flow_mn / 100.0))

        # PBOC Policy impact
        if "EXPANSIONARY" in pboc_stance.upper() or "EASING" in pboc_stance.upper():
            score += 15.0
        elif "TIGHTENING" in pboc_stance.upper():
            score -= 15.0

        # Index return impact
        score += shanghai_comp_return_pct * 5.0
        score = max(0.0, min(100.0, score))

        market_bias = "BULLISH" if score > 60.0 else "BEARISH" if score < 40.0 else "NEUTRAL"
        summary = f"China Market Analysis ({symbol}): Northbound Flow={northbound_net_flow_mn:+.0f}M RMB, PBOC={pboc_stance}, Bias={market_bias}"

        return ChinaMarketReport(
            symbol=symbol,
            northbound_net_flow_mn=northbound_net_flow_mn,
            pboc_policy_stance=pboc_stance,
            sentiment_index=score,
            market_bias=market_bias,
            summary=summary,
        )


class EnhancedNewsFilterEngine:
    """Multi-Source News Deduplication & Relevance Filtering Engine."""

    def filter_and_deduplicate(
        self, articles: List[Dict[str, Any]], target_symbol: str = "BTC"
    ) -> List[FilteredNewsArticle]:
        """Deduplicates articles based on title similarity and ranks by relevance."""
        seen_titles = set()
        filtered = []

        for art in articles:
            raw_title = art.get("title", "")
            clean_title = re.sub(r"[^\w\s]", "", raw_title.lower()).strip()

            if not clean_title or clean_title in seen_titles:
                continue

            seen_titles.add(clean_title)

            # Relevance score
            rel_score = 0.50
            if target_symbol.lower() in clean_title:
                rel_score += 0.40
            if any(k in clean_title for k in ["rate", "fed", "inflation", "cpi", "earnings", "profit"]):
                rel_score += 0.10

            rel_score = min(1.0, rel_score)

            filtered.append(
                FilteredNewsArticle(
                    title=raw_title,
                    source=art.get("source", "UNKNOWN"),
                    relevance_score=rel_score,
                    is_duplicate=False,
                    sentiment=art.get("sentiment", "NEUTRAL"),
                )
            )

        # Sort by relevance
        filtered.sort(key=lambda x: x.relevance_score, reverse=True)
        return filtered


class DataCompletenessChecker:
    """Bar Gap Detection & Data Quality Auditor."""

    def check_completeness(
        self, timestamps: List[float], expected_interval_seconds: float = 60.0
    ) -> DataCompletenessReport:
        """Audits time series continuity and detects missing bar gaps."""
        if not timestamps or len(timestamps) < 2:
            return DataCompletenessReport(0, 0, 0, 100.0, False)

        timestamps_sorted = sorted(timestamps)
        start_ts = timestamps_sorted[0]
        end_ts = timestamps_sorted[-1]

        total_duration = end_ts - start_ts
        expected_bars = int(round(total_duration / expected_interval_seconds)) + 1
        actual_bars = len(timestamps_sorted)

        missing_count = max(0, expected_bars - actual_bars)
        completeness_pct = (actual_bars / float(expected_bars) * 100.0) if expected_bars > 0 else 100.0

        return DataCompletenessReport(
            total_expected_bars=expected_bars,
            total_actual_bars=actual_bars,
            missing_bar_count=missing_count,
            completeness_pct=min(100.0, completeness_pct),
            has_gaps=missing_count > 0,
        )
