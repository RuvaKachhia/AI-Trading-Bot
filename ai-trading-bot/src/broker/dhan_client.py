"""
Dhan API wrapper for market data.
Provides: live quotes, OHLC candles (5min, daily), instrument lookup.
Rate limits: 1 req/sec, 20K requests/day.
No order execution — paper trading only.
"""

import logging
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


class RateLimiter:
    """Token-bucket rate limiter."""

    def __init__(self, max_calls: int, period_seconds: float):
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls: list[float] = []
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < self.period]
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self.calls.append(time.time())


class DhanDataClient:
    """
    Market data client using Dhan API.
    Provides the same interface as KiteClientWrapper (data methods only).
    Handles symbol-to-security_id translation internally.
    """

    def __init__(self, client_id: str, access_token: str, notifier=None):
        from dhanhq import dhanhq as DhanHQ
        self.dhan = DhanHQ(client_id=client_id, access_token=access_token)
        self.notifier = notifier

        # Rate limiter: Dhan market-feed endpoints are sticky when bursted;
        # 1 req / 2s across all market-feed endpoints avoids "805 too many requests"
        self._limiter = RateLimiter(max_calls=1, period_seconds=2.0)

        # Symbol mapping: "NSE:RELIANCE" -> (security_id, dhan_segment)
        # dhan_segment is NSE_EQ / BSE_EQ / IDX_I / NSE_CURRENCY / BSE_CURRENCY
        self._symbol_info: dict[str, tuple[int, str]] = {}
        # Reverse: security_id -> "NSE:RELIANCE"
        self._secid_to_symbol: dict[int, str] = {}
        # Equity-only view kept for backwards-compat callers
        self._symbol_to_secid: dict[str, int] = {}

        # Aliases — the pulse code uses Kite-style names; Dhan uses different ones.
        # Keys are "EXCHANGE:SYMBOL" as passed in; values are the Dhan
        # trading-symbol key we look up.
        self._aliases: dict[str, str] = {
            "NSE:NIFTY 50": "NSE:NIFTY",
            "NSE:NIFTY BANK": "NSE:BANKNIFTY",
            "NSE:NIFTY IT": "NSE:NIFTYIT",
            "NSE:INDIA VIX": "NSE:INDIA VIX",
        }

    def _ensure_mapping(self, keys: list[str]) -> None:
        """Ensure all keys have security_id mappings. Load instruments if needed."""
        missing = [k for k in keys if k not in self._symbol_to_secid]
        if missing and not self._symbol_to_secid:
            logger.info("Loading Dhan instrument list for symbol mapping...")
            self._load_instrument_mapping()

    def _load_instrument_mapping(self) -> None:
        """
        Load the full instrument list and build symbol -> (sec_id, segment) map.
        Supports equity (E), indices (I), and currency (C) segments.
        Derivatives (D) are skipped — we don't trade F&O.
        """
        try:
            df = self.dhan.fetch_security_list(mode='compact')
            if df is None or df.empty:
                logger.error("Failed to fetch Dhan security list")
                return

            eq_count = idx_count = cur_count = 0
            for _, row in df.iterrows():
                exchange = str(row.get("SEM_EXM_EXCH_ID", ""))
                symbol = str(row.get("SEM_TRADING_SYMBOL", "")).strip()
                seg_letter = str(row.get("SEM_SEGMENT", "")).strip()
                try:
                    sec_id = int(row.get("SEM_SMST_SECURITY_ID", 0))
                except (ValueError, TypeError):
                    continue

                if not symbol or sec_id == 0:
                    continue

                # Determine Dhan segment code
                dhan_seg = None
                if seg_letter == "E":
                    dhan_seg = "NSE_EQ" if exchange == "NSE" else "BSE_EQ"
                    eq_count += 1
                elif seg_letter == "I":
                    dhan_seg = "IDX_I"
                    idx_count += 1
                elif seg_letter == "C":
                    dhan_seg = (
                        "NSE_CURRENCY" if exchange == "NSE" else "BSE_CURRENCY"
                    )
                    cur_count += 1
                else:
                    continue  # skip derivatives

                key = f"{exchange}:{symbol}"
                # Only set if not already present — avoids currency futures
                # clobbering the spot symbol (there are many USDINR-FUT rows).
                if key not in self._symbol_info:
                    self._symbol_info[key] = (sec_id, dhan_seg)
                    self._secid_to_symbol[sec_id] = key
                    if seg_letter == "E":
                        self._symbol_to_secid[key] = sec_id

            logger.info(
                f"Loaded Dhan symbols — equity:{eq_count} index:{idx_count} "
                f"currency:{cur_count} (total distinct keys: {len(self._symbol_info)})"
            )
        except Exception as e:
            logger.error(f"Failed to load Dhan instrument mapping: {e}")

    def _resolve(self, key: str) -> Optional[tuple[int, str]]:
        """
        Resolve a user-facing key like "NSE:NIFTY 50" to (sec_id, dhan_segment).
        Applies alias table so orchestrator can keep Kite-style names.
        """
        self._ensure_mapping([key])
        # Direct hit first
        info = self._symbol_info.get(key)
        if info:
            return info
        # Try alias
        alias = self._aliases.get(key)
        if alias:
            return self._symbol_info.get(alias)
        return None

    def _get_secid(self, key: str) -> Optional[int]:
        """Back-compat: return just the security_id."""
        info = self._resolve(key)
        return info[0] if info else None

    def _retry(self, func, max_retries: int = 3, delay: float = 1.0):
        """Retry with exponential backoff."""
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Final retry failed: {e}")
                    raise
                wait = delay * (2 ** attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} after {wait:.1f}s: {str(e)[:100]}"
                )
                time.sleep(wait)

    def _is_rate_limit_response(self, resp: dict) -> bool:
        """Detect Dhan's '805 too many requests' soft failure."""
        if resp.get("status") == "success":
            return False
        data = resp.get("data", {})
        if isinstance(data, dict):
            inner = data.get("data", {})
            if isinstance(inner, dict) and "805" in inner:
                return True
        return False

    def _call_market_feed(self, method_name: str, seg_groups: dict) -> dict:
        """
        Call a Dhan market-feed method (ticker_data / ohlc_data) with
        rate-limit awareness. Retries up to 3 times on HTTP 805 with
        2 s, 4 s, 8 s backoff. Returns the SDK's wrapped response dict.
        """
        method = getattr(self.dhan, method_name)
        backoff = 2.0
        for attempt in range(3):
            self._limiter.wait()
            resp = method(seg_groups)
            if resp.get("status") == "success":
                return resp
            if self._is_rate_limit_response(resp):
                logger.warning(
                    f"Dhan {method_name} rate-limited (805), "
                    f"backing off {backoff:.0f}s (attempt {attempt + 1}/3)"
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            # Non-rate-limit failure: return immediately so caller can log it
            return resp
        return resp

    # ─── QUOTES ───

    def get_quote(self, instruments: list[str]) -> dict:
        """
        Get OHLC quotes for instruments (LTP + open/high/low/close + volume).
        Uses Dhan's ohlc_data endpoint — not the heavier quote_data (depth)
        endpoint, which may require a higher subscription tier.
        instruments: list of "EXCHANGE:SYMBOL" strings, e.g. ["NSE:RELIANCE"]
        Returns: {"NSE:RELIANCE": {"last_price": ..., "ohlc": {...}, "volume": ...}}
        """
        self._ensure_mapping(instruments)

        # Group by proper Dhan segment (NSE_EQ / IDX_I / NSE_CURRENCY / ...)
        seg_groups: dict[str, list[int]] = {}
        key_by_secid: dict[int, str] = {}

        for key in instruments:
            info = self._resolve(key)
            if not info:
                continue
            sec_id, segment = info
            seg_groups.setdefault(segment, []).append(sec_id)
            key_by_secid[sec_id] = key

        if not seg_groups:
            return {}

        resp = self._call_market_feed("ohlc_data", seg_groups)

        if resp.get("status") != "success":
            logger.error(f"Dhan ohlc_data failed: {resp.get('remarks', '')}")
            return {}

        # Dhan wraps: {"status": "success", "data": {"data": {"NSE_EQ": {...}}, "status": "success"}}
        inner = resp.get("data", {}).get("data", {})
        result = {}

        for segment, sec_data in inner.items():
            if not isinstance(sec_data, dict):
                continue
            for sec_id_str, quote in sec_data.items():
                try:
                    sec_id = int(sec_id_str)
                except (ValueError, TypeError):
                    continue
                key = key_by_secid.get(sec_id, "")
                if not key:
                    continue
                result[key] = {
                    "last_price": quote.get("last_price", 0),
                    "ohlc": quote.get("ohlc", {}),
                    "volume": quote.get("volume", 0),
                    "last_quantity": quote.get("last_quantity", 0),
                    "net_change": quote.get("net_change", 0),
                }

        return result

    def get_ltp(self, instruments: list[str]) -> dict:
        """
        Get last traded prices (lighter than full quote).
        Returns: {"NSE:RELIANCE": {"last_price": 2500.0}}
        """
        self._ensure_mapping(instruments)

        seg_groups: dict[str, list[int]] = {}
        key_by_secid: dict[int, str] = {}

        for key in instruments:
            info = self._resolve(key)
            if not info:
                continue
            sec_id, segment = info
            seg_groups.setdefault(segment, []).append(sec_id)
            key_by_secid[sec_id] = key

        if not seg_groups:
            return {}

        resp = self._call_market_feed("ticker_data", seg_groups)

        if resp.get("status") != "success":
            logger.error(f"Dhan ticker_data failed: {resp.get('remarks', '')}")
            return {}

        inner = resp.get("data", {}).get("data", {})
        result = {}

        for segment, sec_data in inner.items():
            if not isinstance(sec_data, dict):
                continue
            for sec_id_str, quote in sec_data.items():
                try:
                    sec_id = int(sec_id_str)
                except (ValueError, TypeError):
                    continue
                key = key_by_secid.get(sec_id, "")
                if not key:
                    continue
                result[key] = {"last_price": quote.get("last_price", 0)}

        return result

    # ─── HISTORICAL DATA ───

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict]:
        """
        Fetch historical candle data. Matches KiteClientWrapper interface.
        instrument_token is actually the Dhan security_id.
        interval: "day", "5minute", "15minute", etc.
        Returns list of dicts with: date, open, high, low, close, volume
        """
        security_id = str(instrument_token)

        if interval == "day":
            return self._fetch_daily(security_id, from_date, to_date)
        else:
            # Extract minute interval: "5minute" -> 5
            minute_interval = int(interval.replace("minute", ""))
            return self._fetch_intraday(security_id, from_date, to_date, minute_interval)

    def _fetch_daily(
        self, security_id: str, from_date: datetime, to_date: datetime,
        exchange_segment: str = "NSE_EQ", instrument_type: str = "EQUITY",
    ) -> list[dict]:
        """Fetch daily candles from Dhan. Pass IDX_I / INDEX for indices."""
        self._limiter.wait()
        resp = self._retry(lambda: self.dhan.historical_daily_data(
            security_id=security_id,
            exchange_segment=exchange_segment,
            instrument_type=instrument_type,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            expiry_code=0,
        ))

        return self._parse_candle_response(resp)

    def get_index_prev_close(self, key: str) -> float:
        """
        Get yesterday's close for an index like 'NSE:NIFTY 50'.
        Fetches a few days of daily candles via IDX_I segment.
        Returns 0 on any failure.
        """
        info = self._resolve(key)
        if not info:
            return 0.0
        sec_id, segment = info
        if segment != "IDX_I":
            return 0.0
        to_date = datetime.now()
        from_date = to_date - timedelta(days=10)
        try:
            candles = self._fetch_daily(
                str(sec_id), from_date, to_date,
                exchange_segment="IDX_I", instrument_type="INDEX",
            )
            if not candles or len(candles) < 1:
                return 0.0
            from datetime import date as _d
            last = candles[-1]
            last_date = last["date"].date() if hasattr(last["date"], "date") else None
            if last_date is not None and last_date < _d.today():
                return float(last["close"])
            if len(candles) >= 2:
                return float(candles[-2]["close"])
            return 0.0
        except Exception as e:
            logger.warning(f"get_index_prev_close failed for {key}: {e}")
            return 0.0

    def _fetch_intraday(
        self, security_id: str, from_date: datetime, to_date: datetime, interval: int
    ) -> list[dict]:
        """Fetch intraday candles from Dhan."""
        self._limiter.wait()
        resp = self._retry(lambda: self.dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment="NSE_EQ",
            instrument_type="EQUITY",
            from_date=from_date.strftime("%Y-%m-%d %H:%M:%S"),
            to_date=to_date.strftime("%Y-%m-%d %H:%M:%S"),
            interval=interval,
        ))

        return self._parse_candle_response(resp)

    def _parse_candle_response(self, resp: dict) -> list[dict]:
        """
        Parse Dhan's parallel-array candle format into list of dicts.
        Input: {"open": [...], "high": [...], "low": [...], "close": [...], "volume": [...], "timestamp": [...]}
        Output: [{"date": datetime, "open": float, "high": float, "low": float, "close": float, "volume": int}, ...]
        """
        if resp.get("status") != "success":
            logger.error(f"Dhan historical data failed: {resp.get('remarks', '')}")
            return []

        # Dhan nests historical data inside resp["data"]["data"] too
        outer = resp.get("data", {})
        if not isinstance(outer, dict):
            return []
        # Try nested structure first, fall back to flat
        data = outer.get("data", outer) if isinstance(outer.get("data"), dict) else outer

        opens = data.get("open", [])
        highs = data.get("high", [])
        lows = data.get("low", [])
        closes = data.get("close", [])
        volumes = data.get("volume", [])
        timestamps = data.get("timestamp", [])

        if not timestamps:
            return []

        candles = []
        for i in range(len(timestamps)):
            dt = datetime.fromtimestamp(timestamps[i], tz=IST)
            candles.append({
                "date": dt,
                "open": opens[i] if i < len(opens) else 0,
                "high": highs[i] if i < len(highs) else 0,
                "low": lows[i] if i < len(lows) else 0,
                "close": closes[i] if i < len(closes) else 0,
                "volume": volumes[i] if i < len(volumes) else 0,
            })

        return candles

    def get_daily_candles(self, instrument_token: int, days: int = 30) -> list[dict]:
        """Fetch daily OHLCV candles for the last N days."""
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days + 5)  # buffer for weekends
        return self.get_historical_data(instrument_token, from_date, to_date, "day")

    def get_intraday_candles(
        self, instrument_token: int, interval: str = "5minute"
    ) -> list[dict]:
        """Fetch today's intraday candles."""
        today = datetime.now().replace(hour=9, minute=15, second=0)
        return self.get_historical_data(instrument_token, today, datetime.now(), interval)

    # ─── INSTRUMENTS ───

    def get_instruments(self, exchange: str = "NSE") -> list[dict]:
        """
        Get instrument list in Kite-compatible format.
        Returns list of dicts with: exchange, tradingsymbol, instrument_token, instrument_type, etc.
        """
        try:
            df = self.dhan.fetch_security_list(mode='compact')
            if df is None or df.empty:
                return []

            # Filter by exchange
            df = df[df["SEM_EXM_EXCH_ID"] == exchange]

            instruments = []
            for _, row in df.iterrows():
                segment = str(row.get("SEM_SEGMENT", ""))
                inst_type = str(row.get("SEM_EXCH_INSTRUMENT_TYPE", ""))

                # Determine if equity
                is_eq = segment == "E"

                instruments.append({
                    "exchange": exchange,
                    "tradingsymbol": str(row.get("SEM_TRADING_SYMBOL", "")),
                    "instrument_token": int(row.get("SEM_SMST_SECURITY_ID", 0)),
                    "instrument_type": "EQ" if is_eq else inst_type,
                    "segment": f"{exchange}-EQ" if is_eq else f"{exchange}-{segment}",
                    "tick_size": float(row.get("SEM_TICK_SIZE", 0.05)),
                    "lot_size": int(row.get("SEM_LOT_UNITS", 1)),
                    "name": str(row.get("SM_SYMBOL_NAME", "")),
                })

            return instruments
        except Exception as e:
            logger.error(f"Failed to fetch Dhan instruments: {e}")
            return []
