"""
Instrument list management.
Caches the full NSE/BSE instrument dump and provides lookups.
"""

import csv
import logging
import os
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)


class InstrumentManager:
    """
    Manages the tradeable instrument list.
    Fetches from Kite daily and caches to CSV.
    """

    def __init__(self, data_client, cache_path: str = "data/instruments_cache.csv"):
        self.data_client = data_client
        self.cache_path = cache_path
        self._instruments: list[dict] = []
        self._token_map: dict[str, int] = {}  # "EXCHANGE:SYMBOL" -> token
        self._symbol_info: dict[str, dict] = {}  # "SYMBOL" -> info dict
        self._valid_eq_symbols: set[str] = set()
        self._last_refresh: Optional[date] = None

    def refresh_instruments(self, exchanges: list[str] = None) -> None:
        """Fetch instruments from Kite and cache to CSV."""
        if exchanges is None:
            exchanges = ["NSE", "BSE"]

        all_instruments = []
        for exchange in exchanges:
            try:
                instruments = self.data_client.get_instruments(exchange)
                all_instruments.extend(instruments)
                logger.info(f"Fetched {len(instruments)} instruments from {exchange}")
            except Exception as e:
                logger.error(f"Failed to fetch {exchange} instruments: {e}")

        self._instruments = all_instruments
        self._build_lookups()
        self._save_cache()
        self._last_refresh = date.today()

    def _build_lookups(self) -> None:
        """Build fast lookup dicts from instrument list."""
        self._token_map.clear()
        self._symbol_info.clear()
        self._valid_eq_symbols.clear()

        for inst in self._instruments:
            key = f"{inst['exchange']}:{inst['tradingsymbol']}"
            self._token_map[key] = inst["instrument_token"]

            self._symbol_info[inst["tradingsymbol"]] = {
                "exchange": inst["exchange"],
                "instrument_token": inst["instrument_token"],
                "instrument_type": inst.get("instrument_type", ""),
                "segment": inst.get("segment", ""),
                "tick_size": inst.get("tick_size", 0.05),
                "lot_size": inst.get("lot_size", 1),
                "name": inst.get("name", ""),
            }

            if inst.get("instrument_type") == "EQ" or inst.get("segment", "").endswith("-EQ"):
                self._valid_eq_symbols.add(inst["tradingsymbol"])

    def _save_cache(self) -> None:
        """Save instruments to CSV cache."""
        if not self._instruments:
            return

        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        keys = self._instruments[0].keys()
        with open(self.cache_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self._instruments)
        logger.info(f"Instruments cached to {self.cache_path} ({len(self._instruments)} rows)")

    def load_cache(self) -> bool:
        """Load instruments from CSV cache if available and fresh."""
        if not os.path.exists(self.cache_path):
            return False

        try:
            with open(self.cache_path, "r") as f:
                reader = csv.DictReader(f)
                self._instruments = list(reader)

            # Convert numeric fields
            for inst in self._instruments:
                inst["instrument_token"] = int(inst.get("instrument_token", 0))
                inst["tick_size"] = float(inst.get("tick_size", 0.05))
                inst["lot_size"] = int(inst.get("lot_size", 1))

            self._build_lookups()
            logger.info(f"Loaded {len(self._instruments)} instruments from cache")
            return True
        except Exception as e:
            logger.error(f"Failed to load instrument cache: {e}")
            return False

    def get_token(self, exchange: str, symbol: str) -> Optional[int]:
        """Get instrument_token for a given exchange:symbol."""
        return self._token_map.get(f"{exchange}:{symbol}")

    def get_valid_symbols(self) -> set[str]:
        """Return set of all equity symbols."""
        return self._valid_eq_symbols.copy()

    def is_valid_symbol(self, symbol: str) -> bool:
        """Check if a symbol is a valid equity instrument."""
        return symbol in self._valid_eq_symbols

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Get exchange, tick_size, lot_size etc. for a symbol."""
        return self._symbol_info.get(symbol)

    def get_all_eq_instruments(self) -> list[dict]:
        """Return all equity instruments."""
        return [
            inst for inst in self._instruments
            if inst.get("instrument_type") == "EQ"
            or inst.get("segment", "").endswith("-EQ")
        ]

    def get_instruments_for_symbols(self, symbols: list[str]) -> list[dict]:
        """Get instrument data for a list of symbols."""
        return [
            self._symbol_info[s] for s in symbols
            if s in self._symbol_info
        ]
