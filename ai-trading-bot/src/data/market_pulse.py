"""
Market Pulse Aggregator.
Builds the compact market dashboard for Claude Sonnet's Market Pulse call.
Aggregates: movers, losers, volume surges, sector heatmap, breadth, etc.
"""

import logging
from typing import Optional

import yaml

from src.data.data_warehouse import DataWarehouse

logger = logging.getLogger(__name__)


class MarketPulseAggregator:
    """
    Reads from DataWarehouse and produces the Market Pulse data dict.
    This is purely a data aggregation — no AI logic.
    """

    def __init__(self, warehouse: DataWarehouse, config: dict):
        self.warehouse = warehouse
        self.config = config
        self._top_n = config.get("pipeline", {}).get("top_movers_count", 15)
        self._top_per_sector = config.get("pipeline", {}).get("top_per_sector_count", 3)
        self._gap_threshold = config.get("pipeline", {}).get("gap_threshold_pct", 2.0)
        self._52w_proximity = config.get("pipeline", {}).get("high_low_proximity_pct", 2.0)

        # Load sector mapping for heatmap
        self._sector_indices: dict[str, str] = {}
        self._load_sector_config()

    def _load_sector_config(self) -> None:
        """Load sector index symbols from config."""
        try:
            with open("config/sector_mapping.yaml") as f:
                data = yaml.safe_load(f)
            sectors = data.get("sectors", {})
            for sector_name, info in sectors.items():
                self._sector_indices[sector_name] = info.get("index", "")
        except Exception as e:
            logger.warning(f"Failed to load sector mapping: {e}")

    def build_pulse(self) -> dict:
        """
        Build the complete Market Pulse data dict.
        This is the structured data that gets formatted into the prompt.
        """
        return {
            "top_gainers": self.warehouse.get_top_gainers(self._top_n),
            "top_losers": self.warehouse.get_top_losers(self._top_n),
            "volume_surges": self.warehouse.get_volume_surges(self._top_n),
            "top_per_sector": self.warehouse.get_top_movers_by_sector(self._top_per_sector),
            "near_52w_highs": self.warehouse.get_52w_high_stocks(self._52w_proximity),
            "near_52w_lows": self.warehouse.get_52w_low_stocks(self._52w_proximity),
            "gap_stocks": self.warehouse.get_gap_stocks(self._gap_threshold),
            "market_breadth": self.warehouse.get_market_breadth(),
        }

    def build_sector_heatmap(self, index_quotes: dict) -> list[dict]:
        """
        Build sector heatmap from index quotes.
        index_quotes: dict of "NIFTY BANK" -> {last_price, change_pct, ...}
        Returns sorted list of sectors by performance.
        """
        heatmap = []
        for sector_name, index_symbol in self._sector_indices.items():
            quote = index_quotes.get(index_symbol, {})
            if quote:
                heatmap.append({
                    "sector": sector_name,
                    "index": index_symbol,
                    "change_pct": quote.get("change_pct", 0),
                })

        heatmap.sort(key=lambda x: x["change_pct"], reverse=True)
        return heatmap

    def build_etf_snapshot(self, etf_quotes: dict) -> list[dict]:
        """
        Build ETF snapshot from live quotes.
        etf_quotes: dict of "NIFTYBEES" -> quote_data
        """
        approved = self.config.get("etfs", {}).get("approved", [])
        snapshot = []
        for etf in approved:
            quote = etf_quotes.get(etf, {})
            if quote:
                prev_close = quote.get("ohlc", {}).get("close", 0)
                ltp = quote.get("last_price", 0)
                change_pct = 0
                if prev_close > 0:
                    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)
                snapshot.append({
                    "symbol": etf,
                    "ltp": ltp,
                    "change_pct": change_pct,
                    "volume": quote.get("volume", 0),
                })
        return snapshot
