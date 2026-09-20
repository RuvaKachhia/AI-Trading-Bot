"""
News Fetcher.
Fetches headlines from RSS feeds, applies mechanical noise filtering,
then optionally uses Haiku for a second pass that drops US-only content
and any noise patterns the regex missed.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# RSS feed sources
RSS_FEEDS = {
    "moneycontrol_market": "https://www.moneycontrol.com/rss/marketreports.xml",
    "moneycontrol_news": "https://www.moneycontrol.com/rss/latestnews.xml",
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "livemint": "https://www.livemint.com/rss/markets",
}

# Google News RSS template for stock-specific news
GOOGLE_NEWS_STOCK_URL = (
    "https://news.google.com/rss/search?q={symbol}+stock+NSE&hl=en-IN&gl=IN&ceid=IN:en"
)

# Mechanical noise patterns — case-insensitive substring match on title.
# These are clear-cut clickbait / non-signal items we drop without Haiku.
_NOISE_PATTERNS = [
    "quote of the day",
    "horoscope",
    "tarot",
    "numerology",
    "zodiac",
    "astro",
    "photos of the day",
    "sponsored",
    "promoted",
    "stock tip of the day",
    "stock of the day",
    "technical call",  # usually "technical call of the day"
    "options strategy of the day",
    "f&o stock",  # we don't trade F&O
    "crypto",
    "bitcoin",
    "ethereum",
    "opinion:",
    "editorial:",
    "watch:",   # video-only links
    "video:",
    "listen:",  # podcast-only
    "podcast:",
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(s: str) -> str:
    """Strip HTML tags, collapse whitespace, trim."""
    if not s:
        return ""
    s = _HTML_TAG_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    # Unescape common entities
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
    s = s.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    return s


def _looks_like_noise(title: str) -> bool:
    """Mechanical pre-filter. Return True if title matches a noise pattern."""
    if not title:
        return True
    t = title.lower()
    for p in _NOISE_PATTERNS:
        if p in t:
            return True
    return False


class NewsFetcher:
    """
    Fetches news headlines from RSS feeds, pre-filters noise, and
    optionally uses Haiku to drop US-only / off-topic items.
    """

    def __init__(self, config: dict, claude_client=None):
        self.config = config
        self.claude_client = claude_client
        self._cache: dict[str, list[dict]] = {}
        self._last_fetch: dict[str, datetime] = {}
        self._cache_ttl_minutes = 15
        self._headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def fetch_market_headlines(
        self, max_headlines: int = 200, per_source: int = 60,
        max_age_days: int = 3,
    ) -> list[dict]:
        """
        Fetch headlines from all RSS sources, pre-filter mechanical noise,
        drop items older than max_age_days (Moneycontrol sometimes serves
        stale 2-year-old entries in its RSS), dedupe, sort by recency.
        Includes the RSS summary field when it has real text (HTML-only
        images are dropped).
        Returns list of {source, title, link, published, summary}.
        """
        all_headlines = []
        cutoff = datetime.now() - timedelta(days=max_age_days)

        stale_dropped = 0
        for source_name, feed_url in RSS_FEEDS.items():
            try:
                entries = self._fetch_feed(feed_url, source_name)
                for entry in entries[:per_source]:
                    title = _clean_text(entry.get("title", ""))
                    if _looks_like_noise(title):
                        continue
                    pub_str = self._parse_date(entry)
                    # Recency filter
                    try:
                        pub_dt = datetime.strptime(pub_str, "%Y-%m-%d %H:%M")
                        if pub_dt < cutoff:
                            stale_dropped += 1
                            continue
                    except Exception:
                        pass  # If we can't parse date, keep the item
                    raw_summary = entry.get("summary", "") or entry.get("description", "")
                    summary = _clean_text(raw_summary)
                    # Moneycontrol summaries are just <img> tags — skip if it's garbage-short
                    if len(summary) < 40:
                        summary = ""
                    all_headlines.append({
                        "source": source_name,
                        "title": title,
                        "link": entry.get("link", ""),
                        "published": pub_str,
                        "summary": summary[:500],
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch {source_name}: {e}")

        all_headlines.sort(key=lambda x: x["published"], reverse=True)
        all_headlines = self._deduplicate(all_headlines)
        if stale_dropped:
            logger.info(f"Recency filter dropped {stale_dropped} stale (>{max_age_days}d) headlines")
        return all_headlines[:max_headlines]

    def fetch_and_filter_headlines(
        self, max_raw: int = 200, per_source: int = 60,
    ) -> list[dict]:
        """
        Full pipeline: fetch + mechanical pre-filter + Haiku relevance filter.
        Headlines that survive both filters are returned. Use this in the
        Market Pulse cycle to get a clean, India-relevant stream.
        """
        raw = self.fetch_market_headlines(max_headlines=max_raw, per_source=per_source)
        if not self.claude_client or not raw:
            return raw
        kept = self._haiku_filter(raw)
        logger.info(
            f"News filter: {len(raw)} raw -> "
            f"{len(kept)} after Haiku (dropped {len(raw) - len(kept)})"
        )
        return kept

    def fetch_stock_news(self, symbol: str, max_headlines: int = 5) -> list[dict]:
        """Fetch news for a specific stock via Google News RSS."""
        cache_key = f"stock_{symbol}"
        if self._is_cached(cache_key):
            return self._cache[cache_key][:max_headlines]

        url = GOOGLE_NEWS_STOCK_URL.format(symbol=symbol)
        try:
            entries = self._fetch_feed(url, cache_key)
            headlines = []
            for entry in entries[:max_headlines]:
                headlines.append({
                    "source": "google_news",
                    "title": _clean_text(entry.get("title", "")),
                    "link": entry.get("link", ""),
                    "published": self._parse_date(entry),
                    "summary": "",
                })
            self._cache[cache_key] = headlines
            self._last_fetch[cache_key] = datetime.now()
            return headlines
        except Exception as e:
            logger.warning(f"Failed to fetch news for {symbol}: {e}")
            return []

    def _haiku_filter(self, headlines: list[dict]) -> list[dict]:
        """
        Ask Haiku which indices to keep. Returns the filtered list.
        Single binary classification — no tagging, no sentiment, no
        symbols. Those are Sonnet's job.
        """
        if not self.claude_client or not headlines:
            return headlines

        # Build compact numbered list for Haiku
        lines = []
        for i, h in enumerate(headlines):
            src = h.get("source", "")
            ts = h.get("published", "")
            title = h.get("title", "")
            lines.append(f"{i}. [{src} {ts}] {title}")
        headlines_text = "\n".join(lines)

        prompt = (
            "You are a news filter for an Indian equity paper trading bot. "
            "For each numbered headline, decide whether to KEEP it for the "
            "trading model to consider.\n\n"
            "KEEP if the headline is:\n"
            "- About Indian markets, Indian companies, NSE/BSE stocks, "
            "Indian sectors, Indian macro (RBI, GDP, inflation, FII/DII)\n"
            "- Global macro with direct India impact (Fed decisions, oil, "
            "USD/INR, global recession signals)\n\n"
            "DROP if it is:\n"
            "- US-only company news with no India angle (e.g. Adobe, Marvell, "
            "Delta Airlines) — unless macro-significant\n"
            "- Quote-of-the-day, Warren Buffett quotes, horoscopes, tarot, "
            "astrology, numerology\n"
            "- Clickbait 'trading guide of the day', 'top 10 tips', "
            "'stock of the day' puff pieces\n"
            "- Cryptocurrency news (the bot does not trade crypto)\n"
            "- Sponsored or promotional content\n"
            "- Sports, entertainment, lifestyle, movie reviews\n\n"
            "Respond with ONLY a JSON object of the form:\n"
            '{"keep": [<zero-indexed integers to KEEP>]}\n\n'
            f"Headlines:\n{headlines_text}"
        )

        try:
            response = self.claude_client.call_haiku(
                prompt=prompt, call_type="NEWS_SUMMARY",
            )
            keep_idx: list[int] = []
            if isinstance(response, dict) and "keep" in response:
                keep_idx = [int(i) for i in response["keep"] if isinstance(i, (int, float))]
            elif isinstance(response, list):
                # Backward compat — if Haiku returns a bare list, assume it's the keep indices
                keep_idx = [int(i) for i in response if isinstance(i, (int, float))]
            keep_set = set(keep_idx)
            filtered = [h for i, h in enumerate(headlines) if i in keep_set]
            return filtered if filtered else headlines  # safety: if filter produced zero, fall back to all
        except Exception as e:
            logger.warning(f"Haiku filter failed, passing all headlines through: {e}")
            return headlines

    def _fetch_feed(self, url: str, source_name: str) -> list:
        """Fetch and parse an RSS feed."""
        if self._is_cached(source_name):
            return self._cache.get(source_name, [])

        feed = feedparser.parse(url)
        entries = feed.entries if feed.entries else []

        self._cache[source_name] = entries
        self._last_fetch[source_name] = datetime.now()

        return entries

    def _is_cached(self, key: str) -> bool:
        """Check if data is cached and still fresh."""
        if key not in self._last_fetch:
            return False
        age = (datetime.now() - self._last_fetch[key]).total_seconds() / 60
        return age < self._cache_ttl_minutes

    def _parse_date(self, entry) -> str:
        """Parse the published date from an RSS entry."""
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            try:
                dt = datetime(*published[:6])
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    def _deduplicate(self, headlines: list[dict]) -> list[dict]:
        """Remove duplicate headlines based on title similarity."""
        seen_titles = set()
        unique = []
        for h in headlines:
            title_key = h["title"].lower().strip()[:60]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(h)
        return unique
