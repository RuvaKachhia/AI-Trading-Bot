"""
Technical indicator computation engine.
Uses pandas_ta for most indicators. Computed on OHLCV DataFrames.
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False
    logger.warning("pandas_ta not installed. Indicators will be limited.")


class IndicatorEngine:
    """Computes technical indicators on OHLCV DataFrames."""

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all indicators on a daily OHLCV DataFrame.
        Adds columns in-place and returns the enriched DataFrame.
        Expects columns: open, high, low, close, volume
        """
        if df is None or df.empty or len(df) < 5:
            return df

        df = df.copy()

        if not HAS_PANDAS_TA:
            return self._compute_basic(df)

        try:
            # RSI (14)
            df["rsi_14"] = ta.rsi(df["close"], length=14)

            # MACD (12, 26, 9)
            macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
            if macd is not None:
                df["macd"] = macd.iloc[:, 0]
                df["macd_histogram"] = macd.iloc[:, 1]
                df["macd_signal"] = macd.iloc[:, 2]

            # SMA (20, 50, 200)
            df["sma_20"] = ta.sma(df["close"], length=20)
            df["sma_50"] = ta.sma(df["close"], length=50)
            df["sma_200"] = ta.sma(df["close"], length=200)

            # EMA (9)
            df["ema_9"] = ta.ema(df["close"], length=9)

            # Bollinger Bands (20, 2)
            bbands = ta.bbands(df["close"], length=20, std=2)
            if bbands is not None:
                df["bb_upper"] = bbands.iloc[:, 2]
                df["bb_mid"] = bbands.iloc[:, 1]
                df["bb_lower"] = bbands.iloc[:, 0]

            # ADX (14)
            adx = ta.adx(df["high"], df["low"], df["close"], length=14)
            if adx is not None:
                df["adx_14"] = adx.iloc[:, 0]

            # ATR (14)
            df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

            # Volume SMA (20)
            df["vol_sma_20"] = ta.sma(df["volume"], length=20)

            # Supertrend (10, 3)
            st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3)
            if st is not None:
                # Column names vary by version, take the trend direction and value
                for col in st.columns:
                    if "SUPERTd" in col:
                        df["supertrend_direction"] = st[col]
                    elif "SUPERT_" in col and "SUPERTd" not in col and "SUPERTl" not in col and "SUPERTs" not in col:
                        df["supertrend_value"] = st[col]

        except Exception as e:
            logger.error(f"Error computing indicators: {e}")

        return df

    def compute_vwap(self, intraday_df: pd.DataFrame) -> Optional[float]:
        """
        Compute VWAP from intraday data.
        VWAP = cumsum(price * volume) / cumsum(volume)
        """
        if intraday_df is None or intraday_df.empty:
            return None

        try:
            df = intraday_df.copy()
            typical_price = (df["high"] + df["low"] + df["close"]) / 3
            cum_vol = df["volume"].cumsum()
            cum_tp_vol = (typical_price * df["volume"]).cumsum()

            vwap_series = cum_tp_vol / cum_vol
            return round(float(vwap_series.iloc[-1]), 2) if len(vwap_series) > 0 else None
        except Exception as e:
            logger.error(f"Error computing VWAP: {e}")
            return None

    def get_latest_indicators(self, df: pd.DataFrame) -> dict:
        """Extract the latest indicator values as a dict for prompt building."""
        if df is None or df.empty:
            return {}

        latest = df.iloc[-1]
        result = {}

        for col in [
            "rsi_14", "macd", "macd_histogram", "macd_signal",
            "sma_20", "sma_50", "sma_200", "ema_9",
            "bb_upper", "bb_mid", "bb_lower",
            "adx_14", "atr_14", "vol_sma_20",
            "supertrend_direction", "supertrend_value",
        ]:
            val = latest.get(col)
            if pd.notna(val):
                result[col] = round(float(val), 2) if isinstance(val, (int, float)) else val

        # Add derived signals
        close = latest.get("close", 0)
        if close and result.get("sma_20"):
            result["price_vs_sma20"] = "above" if close > result["sma_20"] else "below"
        if close and result.get("sma_50"):
            result["price_vs_sma50"] = "above" if close > result["sma_50"] else "below"
        if close and result.get("sma_200"):
            result["price_vs_sma200"] = "above" if close > result["sma_200"] else "below"
        if close and result.get("ema_9"):
            result["price_vs_ema9"] = "above" if close > result["ema_9"] else "below"

        # MACD signal
        macd_val = result.get("macd", 0)
        macd_sig = result.get("macd_signal", 0)
        if macd_val and macd_sig:
            if macd_val > macd_sig:
                result["macd_crossover"] = "bullish_crossover"
            elif macd_val < macd_sig:
                result["macd_crossover"] = "bearish_crossover"
            else:
                result["macd_crossover"] = "neutral"

        # MACD histogram expanding/contracting
        hist = result.get("macd_histogram", 0)
        if len(df) >= 2:
            prev_hist = df.iloc[-2].get("macd_histogram")
            if pd.notna(prev_hist) and pd.notna(hist):
                result["macd_hist_trend"] = (
                    "expanding" if abs(hist) > abs(prev_hist) else "contracting"
                )

        # Supertrend signal
        st_dir = result.get("supertrend_direction")
        if st_dir is not None:
            result["supertrend_signal"] = "BUY" if st_dir == 1 else "SELL"

        return result

    def _compute_basic(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fallback basic indicators without pandas_ta."""
        # Simple SMA
        df["sma_20"] = df["close"].rolling(20).mean()
        df["sma_50"] = df["close"].rolling(50).mean()

        # Simple RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # Volume SMA
        df["vol_sma_20"] = df["volume"].rolling(20).mean()

        return df
