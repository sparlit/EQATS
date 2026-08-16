"""
Central Bank NLP Hawkish/Dovish Parser & Guidance Semantic Diff Extractor.
Analyzes policy statements (FOMC, ECB, BOE, BOJ) to derive continuous Hawkish (+1.0)
to Dovish (-1.0) sentiment scores and wording diffs.
"""

import re

class CentralBankNLPParser:
    """Hawkish / Dovish policy statement parser and guidance diff extractor."""

    HAWKISH_KEYWORDS = [
        "inflation", "tightening", "rate hike", "upside risk", "restrictive",
        "persistent", "overheating", "taper", "elevated", "wage pressure"
    ]

    DOVISH_KEYWORDS = [
        "slowdown", "easing", "rate cut", "downside risk", "transitory",
        "accommodative", "weakness", "recession", "cooling", "headwinds"
    ]

    @classmethod
    def score_hawkish_dovish_index(cls, statement_text):
        """Scores statement text on continuous Hawkish (+1.0) to Dovish (-1.0) spectrum."""
        if not statement_text:
            return {"sentiment_score": 0.0, "classification": "NEUTRAL"}

        text_lower = statement_text.lower()
        hawk_count = sum(len(re.findall(r'\b' + kw + r'\b', text_lower)) for kw in cls.HAWKISH_KEYWORDS)
        dove_count = sum(len(re.findall(r'\b' + kw + r'\b', text_lower)) for kw in cls.DOVISH_KEYWORDS)

        total_matches = hawk_count + dove_count
        if total_matches == 0:
            return {"sentiment_score": 0.0, "classification": "NEUTRAL"}

        score = (hawk_count - dove_count) / float(total_matches)
        classification = "HAWKISH" if score >= 0.20 else ("DOVISH" if score <= -0.20 else "NEUTRAL")

        return {
            "sentiment_score": round(score, 4),
            "hawkish_count": hawk_count,
            "dovish_count": dove_count,
            "classification": classification
        }

    @classmethod
    def extract_forward_guidance_shift(cls, prev_statement, current_statement):
        """Computes semantic diffs between two consecutive central bank policy statements."""
        prev_score = cls.score_hawkish_dovish_index(prev_statement)["sentiment_score"]
        curr_score = cls.score_hawkish_dovish_index(current_statement)["sentiment_score"]

        diff = curr_score - prev_score
        shift = "HAWKISH_SHIFT" if diff > 0.15 else ("DOVISH_SHIFT" if diff < -0.15 else "UNCHANGED")

        return {
            "prev_score": prev_score,
            "current_score": curr_score,
            "guidance_score_diff": round(diff, 4),
            "policy_shift": shift
        }
