"""
Candlestick pattern detection.
Uses TA-Lib if available, falls back to manual detection.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

try:
    import talib
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False
    logger.info("TA-Lib not installed. Using manual pattern detection.")


class PatternDetector:
    """Detects candlestick patterns in OHLCV data."""

    # TA-Lib pattern functions to check
    TALIB_PATTERNS = {
        "CDLDOJI": "Doji",
        "CDLENGULFING": "Engulfing",
        "CDLHAMMER": "Hammer",
        "CDLINVERTEDHAMMER": "Inverted Hammer",
        "CDLMORNINGSTAR": "Morning Star",
        "CDLEVENINGSTAR": "Evening Star",
        "CDLHARAMI": "Harami",
        "CDLPIERCING": "Piercing",
        "CDLDARKCLOUDCOVER": "Dark Cloud Cover",
        "CDLSHOOTINGSTAR": "Shooting Star",
        "CDLSPINNINGTOP": "Spinning Top",
        "CDLMARUBOZU": "Marubozu",
        "CDLHANGINGMAN": "Hanging Man",
        "CDLTHREEWHITESOLDIERS": "Three White Soldiers",
        "CDLTHREEBLACKCROWS": "Three Black Crows",
    }

    def detect_patterns(
        self, df: pd.DataFrame, last_n_days: int = 5
    ) -> list[tuple[str, str]]:
        """
        Detect candlestick patterns.
        Returns list of (date_str, pattern_name) tuples.
        """
        if df is None or df.empty or len(df) < 3:
            return []

        if HAS_TALIB:
            return self._detect_talib(df, last_n_days)
        else:
            return self._detect_manual(df, last_n_days)

    def _detect_talib(
        self, df: pd.DataFrame, last_n_days: int
    ) -> list[tuple[str, str]]:
        """Detect patterns using TA-Lib CDL functions."""
        patterns = []
        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        c = df["close"].values.astype(float)

        for func_name, pattern_name in self.TALIB_PATTERNS.items():
            try:
                func = getattr(talib, func_name)
                result = func(o, h, l, c)

                # Check last N days for non-zero values
                for i in range(-min(last_n_days, len(df)), 0):
                    if result[i] != 0:
                        date_str = str(df.iloc[i].get("date", ""))[:10]
                        direction = "Bullish" if result[i] > 0 else "Bearish"
                        patterns.append(
                            (date_str, f"{direction} {pattern_name}")
                        )
            except Exception:
                continue

        return patterns

    def _detect_manual(
        self, df: pd.DataFrame, last_n_days: int
    ) -> list[tuple[str, str]]:
        """Manual pattern detection fallback."""
        patterns = []
        start_idx = max(0, len(df) - last_n_days)

        for i in range(start_idx, len(df)):
            row = df.iloc[i]
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            body = abs(c - o)
            total_range = h - l
            date_str = str(row.get("date", ""))[:10]

            if total_range == 0:
                continue

            body_pct = body / total_range

            # Doji: very small body
            if body_pct < 0.1:
                patterns.append((date_str, "Doji"))

            # Hammer: small body at top, long lower shadow
            upper_shadow = h - max(o, c)
            lower_shadow = min(o, c) - l
            if body_pct < 0.35 and lower_shadow > body * 2 and upper_shadow < body * 0.5:
                patterns.append((date_str, "Hammer"))

            # Shooting Star: small body at bottom, long upper shadow
            if body_pct < 0.35 and upper_shadow > body * 2 and lower_shadow < body * 0.5:
                patterns.append((date_str, "Shooting Star"))

            # Marubozu: very large body, minimal shadows
            if body_pct > 0.9:
                direction = "Bullish" if c > o else "Bearish"
                patterns.append((date_str, f"{direction} Marubozu"))

            # Engulfing (requires previous candle)
            if i > 0:
                prev = df.iloc[i - 1]
                po, pc = prev["open"], prev["close"]
                # Bullish engulfing
                if pc < po and c > o and o < pc and c > po:
                    patterns.append((date_str, "Bullish Engulfing"))
                # Bearish engulfing
                if pc > po and c < o and o > pc and c < po:
                    patterns.append((date_str, "Bearish Engulfing"))

        return patterns
