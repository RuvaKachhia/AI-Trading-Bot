"""Quick import verification test."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Phase 1: Foundation
from src.database.db import Database
from src.database.models import Trade, LLMCallRecord
from src.database.migrations import run_migrations
from src.trading.trade_logger import TradeLogger, GuardrailLogger, PnLLogger
from src.ai.llm_logger import LLMInteractionLogger
from src.notifications.telegram_bot import TelegramNotifier, DummyNotifier

# Phase 2: Broker + Data Infrastructure
from src.data.indicators import IndicatorEngine
from src.data.levels import LevelCalculator
from src.data.patterns import PatternDetector
from src.data.universe import UniverseFilter
from src.data.market_pulse import MarketPulseAggregator
from src.data.deep_dive import DeepDiveAssembler

# Phase 3: News + AI Pipeline
from src.news.news_fetcher import NewsFetcher
from src.news.macro_data import MacroDataFetcher
from src.ai.system_prompt import build_system_prompt
from src.ai.claude_client import ClaudeClient, ClaudeCircuitBreaker
from src.ai.prompt_formatter import PromptFormatter
from src.ai.response_parser import ResponseParser, PromptSizeManager
from src.trading.guardrails import GuardrailEngine, ValidationResult
from src.trading.portfolio_state import PortfolioStateManager

# Phase 4: Trading Engine
from src.trading.paper_broker import PaperBroker
from src.trading.execution_engine import ExecutionEngine
from src.trading.order_reconciler import OrderReconciler
from src.trading.mis_exit import MISAutoExitEngine
from src.trading.sl_health_check import SLHealthCheck
from src.trading.performance import PerformanceTracker

# Phase 5: Orchestrator + Entry Point
from src.orchestrator import Orchestrator

print("All Phase 1-5 modules import successfully!")
_sp = build_system_prompt({})
print(f"System prompt length: {len(_sp)} chars (~{len(_sp)//4} tokens)")
