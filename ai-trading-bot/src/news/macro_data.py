"""
Macro data fetcher.
FII/DII flows, global cues (US markets, SGX Nifty), VIX, USD/INR, crude.
"""

import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class MacroDataFetcher:
    """
    Fetches macro context data: FII/DII, global cues, commodity prices.
    Uses Kite quotes for VIX/USD-INR where available, scraping as fallback.
    """

    def __init__(self, data_client=None, config: dict = None):
        self.data_client = data_client
        self.config = config or {}
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        self._cache: dict[str, dict] = {}
        self._last_fetch: dict[str, datetime] = {}

    def get_macro_snapshot(self) -> dict:
        """
        Build a complete macro snapshot for the Market Pulse prompt.
        Returns dict with all macro fields.
        """
        snapshot = {
            "fii_dii": self.get_fii_dii(),
            "global_cues": self.get_global_cues(),
            "vix": self.get_india_vix(),
            "usd_inr": self.get_usd_inr(),
            "crude": self.get_crude_oil(),
            "gold": self.get_gold_price(),
        }
        return snapshot

    def get_fii_dii(self) -> dict:
        """
        Fetch FII/DII activity data.
        Returns {fii_net, dii_net, fii_buy, fii_sell, dii_buy, dii_sell}.
        """
        cache_key = "fii_dii"
        if self._is_cached(cache_key, ttl_minutes=60):
            return self._cache[cache_key]

        result = {
            "fii_net": 0, "dii_net": 0,
            "fii_buy": 0, "fii_sell": 0,
            "dii_buy": 0, "dii_sell": 0,
            "source": "unavailable",
        }

        try:
            url = "https://www.moneycontrol.com/stocks/marketinfo/fii_dii_activity/"
            resp = requests.get(url, headers=self._headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                tables = soup.find_all("table")
                if tables:
                    # Parse the FII/DII table — structure varies
                    result["source"] = "moneycontrol"
                    result = self._parse_fii_dii_table(tables, result)
        except Exception as e:
            logger.warning(f"FII/DII fetch failed: {e}")

        self._cache[cache_key] = result
        self._last_fetch[cache_key] = datetime.now()
        return result

    def _parse_fii_dii_table(self, tables, result: dict) -> dict:
        """Parse FII/DII values from MoneyControl HTML tables."""
        try:
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 4:
                        label = cells[0].get_text(strip=True).upper()
                        if "FII" in label or "FPI" in label:
                            result["fii_buy"] = self._parse_crore(cells[1].get_text())
                            result["fii_sell"] = self._parse_crore(cells[2].get_text())
                            result["fii_net"] = self._parse_crore(cells[3].get_text())
                        elif "DII" in label:
                            result["dii_buy"] = self._parse_crore(cells[1].get_text())
                            result["dii_sell"] = self._parse_crore(cells[2].get_text())
                            result["dii_net"] = self._parse_crore(cells[3].get_text())
        except Exception as e:
            logger.warning(f"FII/DII table parse error: {e}")
        return result

    def _parse_crore(self, text: str) -> float:
        """Parse a crore amount string like '1,234.56' or '-1234.56'."""
        try:
            cleaned = text.strip().replace(",", "").replace("(", "-").replace(")", "")
            return round(float(cleaned), 2)
        except (ValueError, AttributeError):
            return 0.0

    def get_india_vix(self) -> dict:
        """Get India VIX — LTP from quote + real prev_close from daily candles."""
        if self.data_client:
            try:
                quote = self.data_client.get_quote(["NSE:INDIA VIX"])
                data = quote.get("NSE:INDIA VIX", {})
                ltp = data.get("last_price", 0)
                # Use the same index prev_close helper we use for market indices
                prev_close = 0
                try:
                    prev_close = self.data_client.get_index_prev_close("NSE:INDIA VIX")
                except Exception:
                    pass
                change_pct = 0
                if prev_close > 0 and ltp > 0:
                    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)
                return {"value": ltp, "change_pct": change_pct}
            except Exception as e:
                logger.warning(f"VIX fetch failed: {e}")
        return {"value": 0, "change_pct": 0}

    def get_usd_inr(self) -> dict:
        """Get USD/INR rate from Kite if available."""
        if self.data_client:
            try:
                quote = self.data_client.get_quote(["NSE:USDINR"])
                data = quote.get("NSE:USDINR", {})
                ohlc = data.get("ohlc", {})
                prev_close = ohlc.get("close", 0)
                ltp = data.get("last_price", 0)
                change_pct = 0
                if prev_close > 0:
                    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)
                return {"rate": ltp, "change_pct": change_pct}
            except Exception as e:
                logger.warning(f"USD/INR fetch failed: {e}")
        return {"rate": 0, "change_pct": 0}

    def get_crude_oil(self) -> dict:
        """Get crude oil price. Tries Kite MCX first, falls back to scraping."""
        cache_key = "crude"
        if self._is_cached(cache_key, ttl_minutes=30):
            return self._cache[cache_key]

        result = {"price": 0, "change_pct": 0, "currency": "USD"}

        if self.data_client:
            try:
                quote = self.data_client.get_quote(["MCX:CRUDEOIL"])
                data = list(quote.values())[0] if quote else {}
                ohlc = data.get("ohlc", {})
                prev_close = ohlc.get("close", 0)
                ltp = data.get("last_price", 0)
                change_pct = 0
                if prev_close > 0:
                    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)
                result = {"price": ltp, "change_pct": change_pct, "currency": "INR"}
            except Exception:
                pass

        self._cache[cache_key] = result
        self._last_fetch[cache_key] = datetime.now()
        return result

    def get_gold_price(self) -> dict:
        """Get gold price via Kite MCX."""
        cache_key = "gold"
        if self._is_cached(cache_key, ttl_minutes=30):
            return self._cache[cache_key]

        result = {"price": 0, "change_pct": 0}

        if self.data_client:
            try:
                quote = self.data_client.get_quote(["MCX:GOLD"])
                data = list(quote.values())[0] if quote else {}
                ohlc = data.get("ohlc", {})
                prev_close = ohlc.get("close", 0)
                ltp = data.get("last_price", 0)
                change_pct = 0
                if prev_close > 0:
                    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)
                result = {"price": ltp, "change_pct": change_pct}
            except Exception:
                pass

        self._cache[cache_key] = result
        self._last_fetch[cache_key] = datetime.now()
        return result

    def get_global_cues(self) -> dict:
        """
        Get global market data (US indices, SGX Nifty).
        Uses scraping since Kite doesn't have international indices.
        """
        cache_key = "global"
        if self._is_cached(cache_key, ttl_minutes=30):
            return self._cache[cache_key]

        result = {
            "sp500": {"price": 0, "change_pct": 0},
            "dow": {"price": 0, "change_pct": 0},
            "nasdaq": {"price": 0, "change_pct": 0},
            "sgx_nifty": {"price": 0, "change_pct": 0},
            "source": "unavailable",
        }

        try:
            # Try yfinance-style lightweight fetch
            import yfinance as yf
            tickers = yf.download(
                "^GSPC ^DJI ^IXIC",
                period="2d", interval="1d",
                progress=False, auto_adjust=True,
            )
            if not tickers.empty:
                for sym, key in [("^GSPC", "sp500"), ("^DJI", "dow"), ("^IXIC", "nasdaq")]:
                    try:
                        closes = tickers["Close"][sym].dropna()
                        if len(closes) >= 2:
                            prev = float(closes.iloc[-2])
                            last = float(closes.iloc[-1])
                            change = round(((last - prev) / prev) * 100, 2) if prev else 0
                            result[key] = {"price": round(last, 2), "change_pct": change}
                    except Exception:
                        pass
                result["source"] = "yfinance"
        except ImportError:
            logger.info("yfinance not installed. Global cues unavailable.")
        except Exception as e:
            logger.warning(f"Global cues fetch failed: {e}")

        self._cache[cache_key] = result
        self._last_fetch[cache_key] = datetime.now()
        return result

    def _is_cached(self, key: str, ttl_minutes: int = 30) -> bool:
        """Check if data is cached and fresh."""
        if key not in self._last_fetch:
            return False
        age = (datetime.now() - self._last_fetch[key]).total_seconds() / 60
        return age < ttl_minutes
