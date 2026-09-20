"""Tests for the Indicator Engine."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
import numpy as np
from src.data.indicators import IndicatorEngine


@pytest.fixture
def engine():
    return IndicatorEngine()


@pytest.fixture
def sample_df():
    """Create sample OHLCV data (30 rows)."""
    np.random.seed(42)
    n = 30
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.5,
        "high": close + abs(np.random.randn(n)) * 2,
        "low": close - abs(np.random.randn(n)) * 2,
        "close": close,
        "volume": np.random.randint(100000, 1000000, n),
    })


class TestIndicatorEngine:
    def test_compute_sma(self, engine, sample_df):
        result = engine.compute_all(sample_df)
        assert "sma_20" in result.columns
        assert not result["sma_20"].isna().all()

    def test_compute_rsi(self, engine, sample_df):
        result = engine.compute_all(sample_df)
        assert "rsi_14" in result.columns
        # RSI should be between 0 and 100 where computed
        valid = result["rsi_14"].dropna()
        if not valid.empty:
            assert valid.min() >= 0
            assert valid.max() <= 100

    def test_compute_volume_sma(self, engine, sample_df):
        result = engine.compute_all(sample_df)
        assert "vol_sma_20" in result.columns

    def test_empty_df(self, engine):
        empty = pd.DataFrame()
        result = engine.compute_all(empty)
        assert result.empty

    def test_short_df_returns_as_is(self, engine):
        short = pd.DataFrame({
            "open": [100, 101],
            "high": [102, 103],
            "low": [98, 99],
            "close": [101, 102],
            "volume": [50000, 60000],
        })
        result = engine.compute_all(short)
        # len < 5, returns as-is
        assert len(result) == 2

    def test_get_latest_indicators(self, engine, sample_df):
        df = engine.compute_all(sample_df)
        snapshot = engine.get_latest_indicators(df)
        assert isinstance(snapshot, dict)
        assert "rsi_14" in snapshot

    def test_compute_vwap(self, engine, sample_df):
        vwap = engine.compute_vwap(sample_df)
        assert vwap is not None
        assert vwap > 0

    def test_compute_vwap_empty(self, engine):
        vwap = engine.compute_vwap(pd.DataFrame())
        assert vwap is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
