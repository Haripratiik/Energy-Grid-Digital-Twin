"""Binary-classification metrics in pure numpy (no sklearn dependency)."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel


class ClsMetrics(BaseModel):
    n: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    auroc: float
    base_rate: float        # fraction of positives (class balance)


def _auroc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """AUROC via the rank-sum (Mann-Whitney U) identity."""
    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    # Average ranks for ties.
    _, inv, counts = np.unique(scores, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts))
    np.add.at(sums, inv, ranks)
    avg = sums / counts
    ranks = avg[inv]
    rank_sum_pos = ranks[y_true == 1].sum()
    n_pos, n_neg = len(pos), len(neg)
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2
    return float(u / (n_pos * n_neg))


def evaluate(y_true: np.ndarray, scores: np.ndarray, threshold: float = 0.5) -> ClsMetrics:
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores, dtype=float)
    pred = (scores >= threshold).astype(int)

    tp = int(((pred == 1) & (y_true == 1)).sum())
    fp = int(((pred == 1) & (y_true == 0)).sum())
    fn = int(((pred == 0) & (y_true == 1)).sum())
    tn = int(((pred == 0) & (y_true == 0)).sum())

    n = len(y_true)
    acc = (tp + tn) / n if n else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    auroc = _auroc(y_true, scores)

    return ClsMetrics(
        n=n, accuracy=round(acc, 4), precision=round(prec, 4), recall=round(rec, 4),
        f1=round(f1, 4), auroc=round(auroc, 4) if auroc == auroc else float("nan"),
        base_rate=round(float(y_true.mean()), 4) if n else 0.0,
    )
