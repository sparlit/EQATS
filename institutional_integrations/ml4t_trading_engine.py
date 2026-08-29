"""
ML4T Financial Machine Learning & Eigenportfolio Suite (EQATS Institutional Adaptation)
Adapted from stefan-jansen/machine-learning-for-trading (utils/cv_splits.py & 14_latent_factors/02_eigenportfolios.py)

Provides:
- PurgedWalkForwardCV: Financial ML Walk-Forward Cross-Validation Splitter with Purging & Embargo Buffer Gap
- EigenportfolioDecomposition: Principal Component Analysis (PCA) Factor Loadings & Eigenportfolio Weight Solver
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np


@dataclass
class WalkForwardSplit:
    fold_index: int
    train_start: datetime
    train_end: datetime
    embargo_end: datetime
    val_start: datetime
    val_end: datetime


@dataclass
class EigenportfolioResult:
    num_components: int
    explained_variance_ratios: List[float]
    first_eigenportfolio_weights: Dict[str, float]
    factor_loadings: List[List[float]]


class PurgedWalkForwardCV:
    """Purged & Embargoed Walk-Forward Cross-Validation Splitter for Financial ML."""

    def __init__(
        self,
        train_days: int = 180,
        val_days: int = 30,
        embargo_days: int = 5,  # Buffer gap to prevent overlap leakage
        num_folds: int = 3,
    ):
        self.train_days = train_days
        self.val_days = val_days
        self.embargo_days = embargo_days
        self.num_folds = num_folds

    def generate_splits(self, start_date: datetime) -> List[WalkForwardSplit]:
        """Generates purged walk-forward date splits."""
        splits = []
        curr_train_start = start_date

        for fold in range(self.num_folds):
            train_end = curr_train_start + timedelta(days=self.train_days)
            embargo_end = train_end + timedelta(days=self.embargo_days)
            val_start = embargo_end
            val_end = val_start + timedelta(days=self.val_days)

            splits.append(
                WalkForwardSplit(
                    fold_index=fold + 1,
                    train_start=curr_train_start,
                    train_end=train_end,
                    embargo_end=embargo_end,
                    val_start=val_start,
                    val_end=val_end,
                )
            )

            # Step forward
            curr_train_start = val_start

        return splits


class EigenportfolioDecomposition:
    """PCA Latent Factor Decomposition & Eigenportfolio Weight Solver."""

    def compute_eigenportfolios(
        self, returns_matrix: Dict[str, List[float]], n_components: int = 3
    ) -> EigenportfolioResult:
        """Solves principal component factor loadings and normalized eigenportfolio weights."""
        symbols = sorted(list(returns_matrix.keys()))
        if len(symbols) < 2 or not all(len(v) >= 5 for v in returns_matrix.values()):
            return EigenportfolioResult(0, [], {}, [])

        # Construct matrix (N assets x T timestamps)
        min_len = min(len(v) for v in returns_matrix.values())
        matrix = np.array([returns_matrix[sym][-min_len:] for sym in symbols])

        # Covariance matrix (N x N)
        cov_matrix = np.cov(matrix)

        # Eigenvalue decomposition
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)

        # Sort descending by eigenvalue
        idx = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]

        tot_var = sum(eigenvalues) if sum(eigenvalues) > 0 else 1.0
        exp_var_ratios = [float(v / tot_var) for v in eigenvalues[:n_components]]

        # Normalize 1st Eigenportfolio weights (sum(abs(w)) = 1)
        first_eigenvector = eigenvectors[:, 0]
        norm_weights = first_eigenvector / np.sum(np.abs(first_eigenvector))
        eigenportfolio_weights = {
            sym: round(float(w), 4) for sym, w in zip(symbols, norm_weights)
        }

        factor_loadings = eigenvectors[:, :n_components].tolist()

        return EigenportfolioResult(
            num_components=min(n_components, len(symbols)),
            explained_variance_ratios=[round(r, 4) for r in exp_var_ratios],
            first_eigenportfolio_weights=eigenportfolio_weights,
            factor_loadings=factor_loadings,
        )
