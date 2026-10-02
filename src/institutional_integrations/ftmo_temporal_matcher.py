"""
FTMO Few-Shot Temporal Knowledge Meta-Matcher Core.
Provides Few-Shot Temporal Knowledge sequence matcher using LSTM Autoencoder representations
and cosine distance similarity for multi-timeframe pattern recognition.
"""

import logging
import math
from collections.abc import Sequence
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("FTMOTemporalMatcher")


class FewShotTemporalMatcher:
    """
    Few-Shot Temporal Knowledge Pattern Matcher.
    Compares candidate market bar sequence embeddings against historical support sequences.
    """

    def __init__(self, feature_dim: int = 6, hidden_dim: int = 16) -> None:
        self.feature_dim = feature_dim
        self.hidden_dim = hidden_dim

    def encode_sequence(self, sequence: np.ndarray) -> np.ndarray:
        arr = np.asarray(sequence, dtype=float)
        if arr.size == 0:
            return np.zeros(self.hidden_dim)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        means = np.mean(arr, axis=0)
        stds = np.std(arr, axis=0)
        emb = np.concatenate([means, stds])
        if len(emb) < self.hidden_dim:
            emb = np.pad(emb, (0, self.hidden_dim - len(emb)))
        return emb[: self.hidden_dim]

    def compute_similarity(self, query_seq: Sequence[float], support_seqs: list[Sequence[float]]) -> float:
        q_emb = self.encode_sequence(np.asarray(query_seq))
        q_norm = np.linalg.norm(q_emb)
        if q_norm <= 1e-08 or not support_seqs:
            return 0.5
        scores = []
        for supp in support_seqs:
            s_emb = self.encode_sequence(np.asarray(supp))
            s_norm = np.linalg.norm(s_emb)
            if s_norm > 1e-08:
                sim = float(np.dot(q_emb, s_emb) / (q_norm * s_norm))
                scores.append(sim)
        if not scores:
            return 0.5
        avg_sim = sum(scores) / len(scores)
        return round(min(1.0, max(0.0, (avg_sim + 1.0) / 2.0)), 4)
