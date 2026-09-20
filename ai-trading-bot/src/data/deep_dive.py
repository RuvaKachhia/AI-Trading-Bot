"""
Deep Dive Data Pack Assembler.
Fetches and formats full data for Claude-selected stocks (from watchlist).
This is the data sent to Opus for trading decisions.
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from src.data.data_warehouse import DataWarehouse, StockDataPack

logger = logging.getLogger(__name__)


class DeepDiveAssembler:
    """
    Assembles full data packs for Claude-selected stocks.
    Data is pre-computed in the DataWarehouse — this step just
    formats it for the Opus trading decision prompt.
    """

    def __init__(self, warehouse: DataWarehouse, config: dict):
        self.warehouse = warehouse
        self.config = config
        self._daily_candles_count = config.get("ai", {}).get("daily_candles_count", 15)

    def assemble(self, symbols: list[str]) -> list[dict]:
        """
        Assemble full data packs for a list of stocks.
        Returns list of dicts, each containing all data for one stock.
        """
        packs = []
        for symbol in symbols:
            data = self._assemble_one(symbol)
            if data:
                packs.append(data)
            else:
                logger.warning(f"No data available for {symbol}, skipping deep dive")

        logger.info(f"Deep dive assembled for {len(packs)}/{len(symbols)} stocks")
        return packs

    def _assemble_one(self, symbol: str) -> Optional[dict]:
        """Assemble the complete deep dive data for one stock."""
        # Lazy-load candles + indicators for this symbol if not yet loaded
        pack = self.warehouse.ensure_loaded(symbol)
        if pack is None or pack.daily_df is None:
            return None

        result = {
            "symbol": symbol,
            "exchange": pack.exchange,

            # Price data
            "price_data": self._format_price_data(pack),

            # Daily candles (last N sessions)
            "daily_candles": self._format_daily_candles(pack),

            # Intraday candles
            "intraday_candles": self._format_intraday_candles(pack),

            # Technical indicators
            "indicators": pack.indicators,
            "vwap": pack.vwap,

            # Key levels
            "levels": pack.levels,

            # Candlestick patterns
            "patterns": pack.patterns,

            # Volume stats
            "volume_stats": pack.volume_stats,

            # 52-week range
            "range_52w": pack.range_52w,

            # Sector context
            "sector": pack.sector,
        }

        return result

    def _format_price_data(self, pack: StockDataPack) -> dict:
        """Format current price data for the prompt."""
        return {
            "ltp": pack.ltp,
            "change_pct": pack.change_pct,
            "abs_change": round(pack.ltp - pack.prev_close, 2) if pack.prev_close else 0,
            "day_open": pack.day_open,
            "day_high": pack.day_high,
            "day_low": pack.day_low,
            "prev_close": pack.prev_close,
            "volume_today_cr": round(pack.volume * pack.ltp / 1e7, 2) if pack.ltp else 0,
            "avg_volume_20d_cr": round(
                pack.volume_stats.get("avg_volume_20d", 0) * pack.ltp / 1e7, 2
            ) if pack.ltp else 0,
            "volume_ratio": pack.volume_stats.get("volume_ratio", 0),
            "high_52w": pack.range_52w.get("high_52w", 0),
            "low_52w": pack.range_52w.get("low_52w", 0),
        }

    def _format_daily_candles(self, pack: StockDataPack) -> list[dict]:
        """Format daily candles for the prompt (last N sessions, newest first)."""
        if pack.daily_df is None or pack.daily_df.empty:
            return []

        df = pack.daily_df.tail(self._daily_candles_count).copy()
        df = df.sort_values("date", ascending=False)

        candles = []
        for _, row in df.iterrows():
            candles.append({
                "date": str(row["date"])[:10],
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume_cr": round(float(row["volume"]) * float(row["close"]) / 1e7, 2),
            })
        return candles

    def _format_intraday_candles(self, pack: StockDataPack) -> list[dict]:
        """Format today's intraday candles for the prompt."""
        if pack.intraday_df is None or pack.intraday_df.empty:
            return []

        candles = []
        for _, row in pack.intraday_df.iterrows():
            candles.append({
                "time": str(row["date"])[11:16],  # HH:MM
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume_lakhs": round(float(row["volume"]) / 1e5, 2),
            })
        return candles
