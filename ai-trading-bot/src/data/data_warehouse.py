"""
Data Warehouse (Layer 2).
Bulk data storage for the entire tradeable universe.
Pre-computes indicators, levels, patterns — ready for instant retrieval.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from src.data.indicators import IndicatorEngine
from src.data.levels import LevelCalculator
from src.data.patterns import PatternDetector
from src.data.market_data import MarketDataFetcher

logger = logging.getLogger(__name__)


@dataclass
class StockDataPack:
    """Complete pre-computed data for a single stock."""
    symbol: str
    exchange: str = "NSE"

    # Raw data
    daily_df: Optional[pd.DataFrame] = None
    intraday_df: Optional[pd.DataFrame] = None

    # Live quote
    ltp: float = 0.0
    day_open: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    day_close: float = 0.0
    prev_close: float = 0.0
    volume: int = 0
    change_pct: float = 0.0

    # Pre-computed
    indicators: dict = field(default_factory=dict)
    levels: dict = field(default_factory=dict)
    patterns: list = field(default_factory=list)
    volume_stats: dict = field(default_factory=dict)
    range_52w: dict = field(default_factory=dict)
    vwap: Optional[float] = None

    # Metadata
    last_updated: Optional[datetime] = None
    sector: str = ""


class DataWarehouse:
    """
    Central data store for the entire tradeable universe.
    Collects, computes, and caches all data for instant retrieval.
    """

    def __init__(
        self,
        market_data: MarketDataFetcher,
        indicator_engine: IndicatorEngine,
        level_calculator: LevelCalculator,
        pattern_detector: PatternDetector,
        config: dict,
    ):
        self.market_data = market_data
        self.indicator_engine = indicator_engine
        self.level_calculator = level_calculator
        self.pattern_detector = pattern_detector
        self.config = config

        self._data: dict[str, StockDataPack] = {}
        self._sector_map: dict[str, str] = {}
        self._boot_complete = False
        self._daily_candles_count = config.get("ai", {}).get("daily_candles_count", 15)

    def boot(
        self, universe: list[str], sector_map: dict[str, str] = None
    ) -> None:
        """
        Fast boot: register lightweight packs for the full universe with just
        symbol + sector. Live quotes populate on first refresh_quotes().
        Candles + indicators are lazy-loaded on demand (deep-dive) or
        warmed in the background via warm_universe().
        """
        logger.info(f"DataWarehouse boot: registering {len(universe)} stocks...")
        start = time.time()

        if sector_map:
            self._sector_map = sector_map

        cache_hits = 0
        for symbol in universe:
            if symbol not in self._data:
                pack = StockDataPack(symbol=symbol, exchange="NSE")
                pack.sector = self._sector_map.get(symbol, "")
                # Seed volume_stats + range_52w from cached daily candles
                # when available — no API calls, disk-only reads.
                df = self.market_data.fetch_daily_candles(
                    symbol, "NSE", days=252, use_cache=True, cache_only=True,
                )
                if df is not None and not df.empty:
                    pack.volume_stats = self.market_data.compute_volume_stats(df)
                    if len(df) >= 20:
                        lookback = df.tail(252)
                        pack.range_52w = {
                            "high_52w": float(lookback["high"].max()),
                            "low_52w": float(lookback["low"].min()),
                        }
                    cache_hits += 1
                self._data[symbol] = pack

        self._boot_complete = True
        elapsed = time.time() - start
        logger.info(
            f"DataWarehouse boot complete: {len(universe)} stocks in "
            f"{elapsed:.2f}s (seeded {cache_hits} from daily cache)"
        )

    def ensure_loaded(self, symbol: str, exchange: str = "NSE") -> Optional[StockDataPack]:
        """
        Ensure a stock's candles + indicators are loaded.
        Called lazily by deep-dive or watchlist workflows.
        Returns the fully-populated pack, or None if load fails.
        """
        pack = self._data.get(symbol)
        if pack and pack.daily_df is not None:
            return pack

        fresh = self._load_stock(symbol, exchange)
        if fresh is None:
            return None

        # Preserve live quote fields if pack already exists
        if pack:
            fresh.ltp = pack.ltp or fresh.ltp
            fresh.day_open = pack.day_open or fresh.day_open
            fresh.day_high = pack.day_high or fresh.day_high
            fresh.day_low = pack.day_low or fresh.day_low
            fresh.prev_close = pack.prev_close or fresh.prev_close
            fresh.volume = pack.volume or fresh.volume
            fresh.change_pct = pack.change_pct or fresh.change_pct

        self._data[symbol] = fresh
        return fresh

    def warm_universe(
        self,
        symbols: list[str] = None,
        max_stocks: Optional[int] = None,
        force_refresh: bool = False,
    ) -> None:
        """
        Populate candles + indicators for the universe (or given subset).
        Intended to run after EOD or in the background to warm disk cache.
        At ~1.2s per stock, full universe takes ~10 min — call sparingly.

        When force_refresh=True, bypass the parquet cache entirely and
        re-fetch every symbol from Dhan, rewriting the parquet. Use this
        at EOD so the next morning's refresh_quotes hits a fresh cache
        instead of stampeding the API at 09:00. Wall time is bounded by
        Dhan's 1-req-per-2s rate limit (~17 min for ~510 stocks).
        """
        if symbols is None:
            symbols = list(self._data.keys())
        if max_stocks is not None:
            symbols = symbols[:max_stocks]

        start = time.time()
        loaded = 0
        for symbol in symbols:
            try:
                if force_refresh:
                    pack = self._data.get(symbol)
                    exchange = pack.exchange if pack else "NSE"
                    df = self.market_data.fetch_daily_candles(
                        symbol, exchange, days=400, use_cache=False,
                    )
                    if df is not None and not df.empty:
                        loaded += 1
                else:
                    if self.ensure_loaded(symbol):
                        loaded += 1
            except Exception as e:
                logger.warning(f"Warm failed for {symbol}: {e}")

        logger.info(
            f"warm_universe: {loaded}/{len(symbols)} stocks warmed in "
            f"{time.time() - start:.0f}s (force_refresh={force_refresh})"
        )

    def _load_stock(self, symbol: str, exchange: str = "NSE") -> Optional[StockDataPack]:
        """Load and compute all data for a single stock."""
        pack = StockDataPack(symbol=symbol, exchange=exchange)
        pack.sector = self._sector_map.get(symbol, "")

        # Fetch daily candles. Cache-only — EOD owns the API path.
        # If the parquet is missing for this symbol, return None and let
        # the caller skip it rather than stampede Dhan during market hours.
        pack.daily_df = self.market_data.fetch_daily_candles(
            symbol, exchange,
            days=self._daily_candles_count + 200,  # extra for indicator warmup
            use_cache=True, cache_only=True,
        )
        if pack.daily_df is None or pack.daily_df.empty:
            return None

        # Compute indicators
        pack.daily_df = self.indicator_engine.compute_all(pack.daily_df)
        pack.indicators = self.indicator_engine.get_latest_indicators(pack.daily_df)

        # Compute levels
        pack.levels = self.level_calculator.get_key_levels(pack.daily_df)

        # Detect patterns
        pack.patterns = self.pattern_detector.detect_patterns(pack.daily_df)

        # Volume stats
        pack.volume_stats = self.market_data.compute_volume_stats(pack.daily_df)

        # 52-week range from the daily data we already have
        if len(pack.daily_df) >= 200:
            df_52w = pack.daily_df.tail(252)  # ~1 year of trading days
            pack.range_52w = {
                "high_52w": float(df_52w["high"].max()),
                "low_52w": float(df_52w["low"].min()),
            }

        pack.last_updated = datetime.now()
        return pack

    def refresh_quotes(self, universe: list[str]) -> None:
        """
        Update live quotes for all stocks in the universe.
        NOTE on Dhan semantics: `ohlc.close` returned by Dhan's ohlc_data
        endpoint is TODAY's close (equal to last_price after market close),
        NOT yesterday's close. For correct change_pct / gap calculation we
        read previous close from the disk-cached daily candles.
        """
        t0 = time.time()
        quotes = self.market_data.fetch_bulk_quotes(universe)
        logger.info(
            f"refresh_quotes: fetched {len(quotes)}/{len(universe)} quotes "
            f"in {time.time() - t0:.1f}s"
        )

        updated = 0
        pc_hits = 0
        for symbol, quote in quotes.items():
            if symbol in self._data:
                pack = self._data[symbol]
                pack.ltp = quote.get("last_price", 0)
                ohlc = quote.get("ohlc", {})
                pack.day_open = ohlc.get("open", 0)
                pack.day_high = ohlc.get("high", 0)
                pack.day_low = ohlc.get("low", 0)
                pack.day_close = ohlc.get("close", 0)  # TODAY's close (= ltp after hours)
                pack.volume = quote.get("volume", 0)

                # Cache-only read: the parquet is rewritten daily by the
                # EOD warm_universe(force_refresh=True) job, so daytime
                # cycles must never call the Dhan API. cache_only=True
                # short-circuits the API fallthrough on cache miss.
                # 400 calendar days ≈ 280 trading days, guarantees true 52w coverage.
                df = self.market_data.fetch_daily_candles(
                    symbol, pack.exchange or "NSE", days=400,
                    use_cache=True, cache_only=True,
                )
                prev_close = 0.0
                if df is not None and not df.empty:
                    try:
                        from datetime import date as _d
                        last_date = df.iloc[-1]["date"]
                        last_dt = last_date.date() if hasattr(last_date, "date") else None
                        if last_dt is not None and last_dt < _d.today():
                            prev_close = float(df.iloc[-1]["close"])
                        elif len(df) >= 2:
                            prev_close = float(df.iloc[-2]["close"])
                    except Exception:
                        pass
                    # Seed volume_stats + 52w range every cycle — cheap from df
                    try:
                        pack.volume_stats = self.market_data.compute_volume_stats(df)
                    except Exception:
                        pass
                    if len(df) >= 20:
                        try:
                            lookback = df.tail(252)
                            pack.range_52w = {
                                "high_52w": float(lookback["high"].max()),
                                "low_52w": float(lookback["low"].min()),
                            }
                        except Exception:
                            pass

                if prev_close > 0:
                    pack.prev_close = prev_close
                    pc_hits += 1
                    if pack.ltp > 0:
                        pack.change_pct = round(
                            ((pack.ltp - pack.prev_close) / pack.prev_close) * 100, 2
                        )
                else:
                    pack.prev_close = 0
                    pack.change_pct = 0

                pack.last_updated = datetime.now()
                updated += 1
        logger.info(
            f"refresh_quotes: updated {updated} packs, "
            f"prev_close hits {pc_hits}/{updated} (daily cache)"
        )

    def _lookup_prev_close(self, symbol: str, exchange: str = "NSE") -> float:
        """
        Return the previous trading day's close from the daily candle cache.
        We use the last row's close if it pre-dates today; otherwise the
        second-to-last row (when today's candle is already in the file).
        """
        try:
            df = self.market_data.fetch_daily_candles(
                symbol, exchange, days=5,
                use_cache=True, cache_only=True,
            )
        except Exception:
            return 0
        if df is None or df.empty or len(df) < 1:
            return 0
        try:
            from datetime import date
            today = date.today()
            last = df.iloc[-1]
            last_date = last["date"].date() if hasattr(last["date"], "date") else None
            if last_date is not None and last_date < today:
                return float(last["close"])
            # Today's candle is already in the data → use second-to-last
            if len(df) >= 2:
                return float(df.iloc[-2]["close"])
        except Exception:
            pass
        return 0

    def refresh_intraday(self, symbols: list[str] = None) -> None:
        """Refresh intraday candles and recompute intraday indicators."""
        if symbols is None:
            symbols = list(self._data.keys())

        for symbol in symbols:
            if symbol not in self._data:
                continue

            pack = self._data[symbol]
            pack.intraday_df = self.market_data.fetch_intraday_candles(symbol)

            if pack.intraday_df is not None and not pack.intraday_df.empty:
                pack.vwap = self.indicator_engine.compute_vwap(pack.intraday_df)

    # ─── RETRIEVAL ───

    def get_stock_data(self, symbol: str) -> Optional[StockDataPack]:
        """Get complete pre-computed data for one stock."""
        return self._data.get(symbol)

    def get_all_quotes(self) -> dict[str, dict]:
        """Get live quote data for all stocks."""
        result = {}
        for symbol, pack in self._data.items():
            result[symbol] = {
                "ltp": pack.ltp,
                "change_pct": pack.change_pct,
                "volume": pack.volume,
                "day_open": pack.day_open,
                "day_high": pack.day_high,
                "day_low": pack.day_low,
                "prev_close": pack.prev_close,
                "sector": pack.sector,
            }
        return result

    def get_loaded_symbols(self) -> list[str]:
        """Return list of symbols that have been loaded."""
        return list(self._data.keys())

    # ─── AGGREGATIONS FOR MARKET PULSE ───

    def get_top_gainers(self, n: int = 10) -> list[dict]:
        """Top N gainers by % change."""
        stocks = [
            {"symbol": s, "change_pct": p.change_pct, "ltp": p.ltp,
             "volume_ratio": p.volume_stats.get("volume_ratio", 0),
             "sector": p.sector}
            for s, p in self._data.items()
            if p.ltp > 0
        ]
        stocks.sort(key=lambda x: x["change_pct"], reverse=True)
        return stocks[:n]

    def get_top_losers(self, n: int = 10) -> list[dict]:
        """Top N losers by % change."""
        stocks = [
            {"symbol": s, "change_pct": p.change_pct, "ltp": p.ltp,
             "volume_ratio": p.volume_stats.get("volume_ratio", 0),
             "sector": p.sector}
            for s, p in self._data.items()
            if p.ltp > 0
        ]
        stocks.sort(key=lambda x: x["change_pct"])
        return stocks[:n]

    def get_volume_surges(self, n: int = 10) -> list[dict]:
        """Top N stocks by volume ratio (today vs 20-day avg)."""
        stocks = [
            {"symbol": s, "change_pct": p.change_pct, "ltp": p.ltp,
             "volume_ratio": p.volume_stats.get("volume_ratio", 0),
             "sector": p.sector}
            for s, p in self._data.items()
            if p.volume_stats.get("volume_ratio", 0) > 0
        ]
        stocks.sort(key=lambda x: x["volume_ratio"], reverse=True)
        return stocks[:n]

    def get_top_movers_by_sector(self, n_per_sector: int = 3) -> dict[str, list[dict]]:
        """
        Top N gainers per sector (absolute gainers only).
        Surfaces sector rotation that gets buried in absolute top-movers lists.
        Returns {sector_name: [{symbol, change_pct, ltp, volume_ratio}, ...]}.
        """
        by_sector: dict[str, list[dict]] = {}
        for symbol, pack in self._data.items():
            if pack.ltp <= 0 or not pack.sector:
                continue
            by_sector.setdefault(pack.sector, []).append({
                "symbol": symbol,
                "change_pct": pack.change_pct,
                "ltp": pack.ltp,
                "volume_ratio": pack.volume_stats.get("volume_ratio", 0),
            })

        result: dict[str, list[dict]] = {}
        for sector, stocks in by_sector.items():
            stocks.sort(key=lambda x: x["change_pct"], reverse=True)
            result[sector] = stocks[:n_per_sector]
        return result

    def get_52w_high_stocks(self, proximity_pct: float = 2.0) -> list[dict]:
        """Stocks within proximity_pct of their 52-week high."""
        result = []
        for symbol, pack in self._data.items():
            high_52w = pack.range_52w.get("high_52w", 0)
            if high_52w > 0 and pack.ltp > 0:
                pct_from_high = ((high_52w - pack.ltp) / high_52w) * 100
                if pct_from_high <= proximity_pct:
                    result.append({
                        "symbol": symbol,
                        "ltp": pack.ltp,
                        "high_52w": high_52w,
                        "pct_from_high": round(pct_from_high, 2),
                    })
        result.sort(key=lambda x: x["pct_from_high"])
        return result

    def get_52w_low_stocks(self, proximity_pct: float = 2.0) -> list[dict]:
        """Stocks within proximity_pct of their 52-week low."""
        result = []
        for symbol, pack in self._data.items():
            low_52w = pack.range_52w.get("low_52w", 0)
            if low_52w > 0 and pack.ltp > 0:
                pct_from_low = ((pack.ltp - low_52w) / low_52w) * 100
                if pct_from_low <= proximity_pct:
                    result.append({
                        "symbol": symbol,
                        "ltp": pack.ltp,
                        "low_52w": low_52w,
                        "pct_from_low": round(pct_from_low, 2),
                    })
        result.sort(key=lambda x: x["pct_from_low"])
        return result

    def get_gap_stocks(self, threshold_pct: float = 2.0) -> dict:
        """Stocks that gapped up or down more than threshold at open."""
        gap_up = []
        gap_down = []
        for symbol, pack in self._data.items():
            if pack.prev_close > 0 and pack.day_open > 0:
                gap_pct = ((pack.day_open - pack.prev_close) / pack.prev_close) * 100
                entry = {"symbol": symbol, "gap_pct": round(gap_pct, 2)}
                if gap_pct >= threshold_pct:
                    gap_up.append(entry)
                elif gap_pct <= -threshold_pct:
                    gap_down.append(entry)

        gap_up.sort(key=lambda x: x["gap_pct"], reverse=True)
        gap_down.sort(key=lambda x: x["gap_pct"])
        return {"gap_up": gap_up, "gap_down": gap_down}

    def get_market_breadth(self) -> dict:
        """Compute advance/decline/unchanged counts."""
        advances = 0
        declines = 0
        unchanged = 0
        for pack in self._data.values():
            if pack.change_pct > 0:
                advances += 1
            elif pack.change_pct < 0:
                declines += 1
            else:
                unchanged += 1

        ratio = round(advances / declines, 2) if declines > 0 else float("inf")
        return {
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "ad_ratio": ratio,
        }

    @property
    def is_booted(self) -> bool:
        return self._boot_complete
