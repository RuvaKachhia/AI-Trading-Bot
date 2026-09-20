"""
Support, resistance, and pivot point computation.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class LevelCalculator:
    """Computes pivot points and support/resistance levels."""

    def compute_pivot_points(
        self, prev_high: float, prev_low: float, prev_close: float
    ) -> dict:
        """
        Classic pivot point formula.
        PP = (H + L + C) / 3
        R1 = 2*PP - L, S1 = 2*PP - H
        R2 = PP + (H - L), S2 = PP - (H - L)
        """
        pp = (prev_high + prev_low + prev_close) / 3
        r1 = 2 * pp - prev_low
        s1 = 2 * pp - prev_high
        r2 = pp + (prev_high - prev_low)
        s2 = pp - (prev_high - prev_low)

        return {
            "pivot": round(pp, 2),
            "r1": round(r1, 2),
            "r2": round(r2, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2),
        }

    def compute_pivot_from_df(self, daily_df: pd.DataFrame) -> Optional[dict]:
        """Compute pivot points from the most recent daily candle."""
        if daily_df is None or len(daily_df) < 2:
            return None

        prev = daily_df.iloc[-2]
        return self.compute_pivot_points(
            prev["high"], prev["low"], prev["close"]
        )

    def compute_support_resistance(
        self, df: pd.DataFrame, window: int = 20
    ) -> dict:
        """
        Compute support and resistance using swing high/low detection.
        A swing high is a high that's higher than `window` bars on each side.
        A swing low is a low that's lower than `window` bars on each side.
        """
        if df is None or len(df) < window * 2 + 1:
            return {"resistance_levels": [], "support_levels": []}

        highs = df["high"].values
        lows = df["low"].values
        resistance_levels = []
        support_levels = []

        lookback = min(window, 5)  # Use smaller window for recent levels

        for i in range(lookback, len(df) - lookback):
            # Swing high: higher than surrounding bars
            if highs[i] == max(highs[i - lookback : i + lookback + 1]):
                resistance_levels.append(round(float(highs[i]), 2))

            # Swing low: lower than surrounding bars
            if lows[i] == min(lows[i - lookback : i + lookback + 1]):
                support_levels.append(round(float(lows[i]), 2))

        # Deduplicate close levels (within 0.5% of each other)
        resistance_levels = self._deduplicate_levels(resistance_levels)
        support_levels = self._deduplicate_levels(support_levels)

        # Sort: resistance descending, support descending
        resistance_levels.sort(reverse=True)
        support_levels.sort(reverse=True)

        return {
            "resistance_levels": resistance_levels[:5],
            "support_levels": support_levels[:5],
        }

    def _deduplicate_levels(self, levels: list[float], threshold: float = 0.005) -> list[float]:
        """Merge levels that are within threshold % of each other."""
        if not levels:
            return []

        sorted_levels = sorted(set(levels))
        deduped = [sorted_levels[0]]

        for level in sorted_levels[1:]:
            if abs(level - deduped[-1]) / deduped[-1] > threshold:
                deduped.append(level)

        return deduped

    def get_key_levels(self, daily_df: pd.DataFrame) -> dict:
        """
        Compute all key levels for a stock.
        Returns pivot points + swing support/resistance.
        """
        result = {}

        # Pivot points
        pivots = self.compute_pivot_from_df(daily_df)
        if pivots:
            result.update(pivots)

        # Swing levels
        sr = self.compute_support_resistance(daily_df)
        result["resistance_levels"] = sr["resistance_levels"]
        result["support_levels"] = sr["support_levels"]

        return result
