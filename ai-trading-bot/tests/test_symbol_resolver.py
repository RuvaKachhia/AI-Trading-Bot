"""
Tests for Orchestrator._resolve_unresolved_symbols.

The resolver inserts a Haiku call between Sonnet's watchlist parse and
deep_dive to rewrite hallucinated long-form names (ADANITOTALGAS) to
canonical NSE tickers (ATGL). The validation gate
(`instruments.get_token(candidate) is not None`) is the safety story for
the whole feature — these tests pin it down so a future refactor can't
silently break it.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
import pytest

from src.orchestrator import Orchestrator


@pytest.fixture
def orch():
    """Build a bare Orchestrator with mocked dependencies — no real boot."""
    o = Orchestrator.__new__(Orchestrator)  # bypass __init__
    o.instruments = MagicMock()
    o.claude_client = MagicMock()
    o._resolver_universe_text = "ATGL          Adani Total Gas Ltd"  # avoid CSV read
    return o


def _mk_token_map(valid_tickers):
    """Build a get_token side-effect that returns truthy for valid tickers, None otherwise."""
    def _get(exch, sym):
        return 12345 if sym in valid_tickers else None
    return _get


def test_resolve_empty_watchlist_returns_empty(orch):
    """Empty input → empty output, no Haiku call fired."""
    result = orch._resolve_unresolved_symbols([])
    assert result == []
    orch.claude_client.call_haiku.assert_not_called()


def test_resolve_all_valid_skips_haiku_call(orch):
    """If every symbol resolves directly, the resolver short-circuits — no LLM cost."""
    orch.instruments.get_token.side_effect = _mk_token_map({"RELIANCE", "TCS"})
    watchlist = [
        {"symbol": "RELIANCE", "exchange": "NSE", "reason": "uptrend"},
        {"symbol": "TCS", "exchange": "NSE", "reason": "earnings"},
    ]
    result = orch._resolve_unresolved_symbols(watchlist)
    assert [w["symbol"] for w in result] == ["RELIANCE", "TCS"]
    orch.claude_client.call_haiku.assert_not_called()


def test_resolve_substitutes_valid_haiku_response(orch):
    """Haiku returns a valid ticker → original symbol is rewritten to canonical."""
    orch.instruments.get_token.side_effect = _mk_token_map({"ATGL", "RELIANCE"})
    orch.claude_client.call_haiku.return_value = {"ADANITOTALGAS": "ATGL"}
    watchlist = [
        {"symbol": "ADANITOTALGAS", "exchange": "NSE", "reason": "Q4 results"},
        {"symbol": "RELIANCE", "exchange": "NSE", "reason": "uptrend"},
    ]
    result = orch._resolve_unresolved_symbols(watchlist)
    assert [w["symbol"] for w in result] == ["RELIANCE", "ATGL"] or \
           [w["symbol"] for w in result] == ["ATGL", "RELIANCE"]  # order: kept iterates input
    # Reason and exchange preserved on the rewritten entry
    rewritten = next(w for w in result if w["symbol"] == "ATGL")
    assert rewritten["reason"] == "Q4 results"
    assert rewritten["exchange"] == "NSE"


def test_resolve_drops_on_unknown_response(orch):
    """Haiku returns 'UNKNOWN' → symbol is dropped, no rewrite attempted."""
    orch.instruments.get_token.side_effect = _mk_token_map({"RELIANCE"})
    orch.claude_client.call_haiku.return_value = {"FAKECOMPANY": "UNKNOWN"}
    watchlist = [
        {"symbol": "FAKECOMPANY", "exchange": "NSE", "reason": "..."},
        {"symbol": "RELIANCE", "exchange": "NSE", "reason": "..."},
    ]
    result = orch._resolve_unresolved_symbols(watchlist)
    assert [w["symbol"] for w in result] == ["RELIANCE"]


def test_resolve_drops_on_hallucinated_ticker(orch):
    """
    Critical safety test: Haiku invents a fake ticker that doesn't exist
    in the instrument cache. The validation gate must catch it and drop
    the symbol — never let a fake ticker reach deep_dive.
    """
    # JIOFIN is the real NSE ticker; FAKEXYZ is what Haiku hallucinated
    orch.instruments.get_token.side_effect = _mk_token_map({"JIOFIN", "RELIANCE"})
    orch.claude_client.call_haiku.return_value = {"JIOFINL": "FAKEXYZ"}
    watchlist = [
        {"symbol": "JIOFINL", "exchange": "NSE", "reason": "..."},
        {"symbol": "RELIANCE", "exchange": "NSE", "reason": "..."},
    ]
    result = orch._resolve_unresolved_symbols(watchlist)
    # JIOFINL doesn't resolve, FAKEXYZ doesn't validate → JIOFINL dropped
    assert [w["symbol"] for w in result] == ["RELIANCE"]


def test_resolve_falls_back_on_haiku_exception(orch):
    """Haiku call raises → all unresolved symbols dropped (current behavior preserved)."""
    orch.instruments.get_token.side_effect = _mk_token_map({"RELIANCE"})
    orch.claude_client.call_haiku.side_effect = RuntimeError("API down")
    watchlist = [
        {"symbol": "ADANITOTALGAS", "exchange": "NSE", "reason": "..."},
        {"symbol": "VEDANTA", "exchange": "NSE", "reason": "..."},
        {"symbol": "RELIANCE", "exchange": "NSE", "reason": "..."},
    ]
    result = orch._resolve_unresolved_symbols(watchlist)
    assert [w["symbol"] for w in result] == ["RELIANCE"]


def test_resolve_dedupes_after_rewrite(orch):
    """
    The held-stock injection adds ATGL (canonical) before the resolver runs;
    Sonnet also picks ADANITOTALGAS (hallucinated form of the same stock).
    After the resolver rewrites ADANITOTALGAS → ATGL, the watchlist must
    not contain two ATGL entries — deep_dive would double-process.
    First occurrence wins.
    """
    orch.instruments.get_token.side_effect = _mk_token_map({"ATGL"})
    orch.claude_client.call_haiku.return_value = {"ADANITOTALGAS": "ATGL"}
    watchlist = [
        # Held-stock injection (added before resolver) — comes first
        {"symbol": "ATGL", "exchange": "NSE", "reason": "Currently held"},
        # Sonnet's hallucinated form — collapses onto ATGL after rewrite
        {"symbol": "ADANITOTALGAS", "exchange": "NSE", "reason": "Q4 catalyst"},
    ]
    result = orch._resolve_unresolved_symbols(watchlist)
    assert len(result) == 1
    assert result[0]["symbol"] == "ATGL"
    # First occurrence (held-stock entry) wins
    assert result[0]["reason"] == "Currently held"
