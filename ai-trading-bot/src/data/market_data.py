"""
Market data fetcher.
Fetches historical candles, live quotes, and 52-week ranges.
Daily candles are disk-cached (per-symbol parquet files) to avoid re-fetching
static historical data on every boot.
"""

import logging
import os
import time
from datetime import datetime, date, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Cache TTL for recent candle data (seconds)
_CANDLE_CACHE_TTL = 300  # 5 minutes
_DAILY_CACHE_DIR = "data/candle_cache"


class MarketDataFetcher:
    """Fetches and caches market data."""

    def __init__(self, data_client, instrument_manager, config: dict = None):
        self.data_client = data_client
        self.instrument_manager = instrument_manager
        self.config = config or {}
        # Cache: {symbol_interval: (timestamp, candle_dict)}
        self._candle_cache: dict[str, tuple[float, dict]] = {}
        os.makedirs(_DAILY_CACHE_DIR, exist_ok=True)

    def _daily_cache_path(self, symbol: str, exchange: str) -> str:
        return os.path.join(_DAILY_CACHE_DIR, f"{exchange}_{symbol}_daily.parquet")

    def _read_daily_cache(
        self, symbol: str, exchange: str, days: int
    ) -> Optional[pd.DataFrame]:
        """
        Return cached daily candles if the parquet file exists. The cache is
        authoritative during market hours — no freshness check. The EOD job
        (warm_universe(force_refresh=True)) is the single source that
        rewrites the cache once per trading session, so daytime callers
        never need to refetch.
        """
        path = self._daily_cache_path(symbol, exchange)
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_parquet(path)
            if df.empty:
                return None
            return df.tail(days).reset_index(drop=True) if len(df) > days else df
        except Exception as e:
            logger.warning(f"Failed to read daily cache for {symbol}: {e}")
            return None

    def _write_daily_cache(
        self, symbol: str, exchange: str, df: pd.DataFrame
    ) -> None:
        try:
            path = self._daily_cache_path(symbol, exchange)
            df.to_parquet(path, index=False)
        except Exception as e:
            logger.warning(f"Failed to write daily cache for {symbol}: {e}")

    def fetch_daily_candles(
        self, symbol: str, exchange: str = "NSE", days: int = 30,
        use_cache: bool = True, cache_only: bool = False,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch daily OHLCV candles for a symbol.

        `use_cache` controls only the READ path — when False, the cache is
        bypassed and Dhan is called directly. A successful API fetch ALWAYS
        writes back to disk, regardless of `use_cache`, so the EOD
        force-refresh path actually persists the fresh data. The previous
        behavior coupled write-gating to read-gating, which silently
        discarded API results when callers used `use_cache=False`.

        Returns DataFrame with columns: date, open, high, low, close, volume
        """
        if use_cache:
            cached = self._read_daily_cache(symbol, exchange, days)
            if cached is not None:
                return cached

        if cache_only:
            # Caller doesn't want us to hit the API — return None on cache miss
            return None

        token = self.instrument_manager.get_token(exchange, symbol)
        if token is None:
            logger.warning(f"No instrument token found for {exchange}:{symbol}")
            return None

        try:
            candles = self.data_client.get_daily_candles(token, days=days)
            if not candles:
                return None

            df = pd.DataFrame(candles)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            # Always persist a successful API fetch. `use_cache` is the
            # READ knob, not the write knob — see docstring above.
            self._write_daily_cache(symbol, exchange, df)

            return df
        except Exception as e:
            logger.error(f"Failed to fetch daily candles for {symbol}: {e}")
            return None

    def fetch_intraday_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "15minute",
    ) -> Optional[pd.DataFrame]:
        """Fetch today's intraday candles."""
        token = self.instrument_manager.get_token(exchange, symbol)
        if token is None:
            return None

        try:
            candles = self.data_client.get_intraday_candles(token, interval)
            if not candles:
                return None

            df = pd.DataFrame(candles)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch intraday candles for {symbol}: {e}")
            return None

    def fetch_recent_candle(
        self, symbol: str, exchange: str = "NSE", interval: str = "5minute"
    ) -> Optional[dict]:
        """
        Fetch the most recent COMPLETED candle for a symbol.
        Returns dict with keys: open, high, low, close, volume — or None.

        Uses a per-symbol cache (5-min TTL) to respect Kite's rate limit
        of 1 request/second on historical data endpoints.
        The second-to-last candle is returned since the last candle may
        still be in progress (incomplete).
        """
        cache_key = f"{exchange}:{symbol}:{interval}"
        now = time.time()

        # Check cache
        if cache_key in self._candle_cache:
            cached_at, cached_candle = self._candle_cache[cache_key]
            if now - cached_at < _CANDLE_CACHE_TTL:
                return cached_candle

        # Cache miss — fetch from Kite
        token = self.instrument_manager.get_token(exchange, symbol)
        if token is None:
            return None

        try:
            candles = self.data_client.get_intraday_candles(token, interval)
            if not candles or len(candles) < 2:
                return None

            df = pd.DataFrame(candles)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            # Take second-to-last row (last completed candle)
            row = df.iloc[-2]
            candle = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            }

            # Cache it
            self._candle_cache[cache_key] = (now, candle)
            return candle

        except Exception as e:
            logger.error(f"Failed to fetch recent candle for {symbol}: {e}")
            return None

    def fetch_bulk_quotes(
        self, symbols: list[str], exchange: str = "NSE"
    ) -> dict:
        """
        Fetch live quotes for a list of symbols.
        Batches requests (Kite allows ~500 per call).
        Returns dict of symbol -> quote data.
        """
        results = {}
        instruments = [f"{exchange}:{s}" for s in symbols]

        # Batch into chunks of 900 (Dhan supports 1000 per call)
        batch_size = 900
        for i in range(0, len(instruments), batch_size):
            batch = instruments[i : i + batch_size]
            try:
                quotes = self.data_client.get_quote(batch)
                for key, data in quotes.items():
                    # Extract symbol from "NSE:SYMBOL"
                    sym = key.split(":")[1] if ":" in key else key
                    results[sym] = data
            except Exception as e:
                logger.error(f"Failed to fetch quotes batch {i}: {e}")

        return results

    def get_52_week_range(
        self, symbol: str, exchange: str = "NSE"
    ) -> Optional[dict]:
        """Get 52-week high and low for a symbol."""
        token = self.instrument_manager.get_token(exchange, symbol)
        if token is None:
            return None

        try:
            to_date = datetime.now()
            from_date = to_date - timedelta(days=365)
            candles = self.data_client.get_historical_data(
                token, from_date, to_date, "day"
            )
            if not candles:
                return None

            df = pd.DataFrame(candles)
            return {
                "high_52w": float(df["high"].max()),
                "low_52w": float(df["low"].min()),
            }
        except Exception as e:
            logger.error(f"Failed to get 52w range for {symbol}: {e}")
            return None

    def get_previous_close(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        """Get previous day's close price."""
        try:
            quote = self.data_client.get_quote([f"{exchange}:{symbol}"])
            data = quote.get(f"{exchange}:{symbol}", {})
            ohlc = data.get("ohlc", {})
            return ohlc.get("close")
        except Exception as e:
            logger.error(f"Failed to get prev close for {symbol}: {e}")
            return None

    def compute_volume_stats(
        self, daily_df: pd.DataFrame
    ) -> dict:
        """Compute volume statistics from daily candles."""
        if daily_df is None or daily_df.empty:
            return {"avg_volume_20d": 0, "volume_ratio": 0}

        vol = daily_df["volume"]
        avg_20d = vol.tail(20).mean() if len(vol) >= 20 else vol.mean()
        latest_vol = vol.iloc[-1] if len(vol) > 0 else 0
        ratio = latest_vol / avg_20d if avg_20d > 0 else 0

        return {
            "avg_volume_20d": float(avg_20d),
            "latest_volume": float(latest_vol),
            "volume_ratio": round(float(ratio), 2),
        }
