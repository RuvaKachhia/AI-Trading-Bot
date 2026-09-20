"""
Main Orchestrator.
Ties all components together and runs the daily trading schedule.
Uses APScheduler for cron-based job scheduling.
"""

import json
import logging
import os
import shutil
import time
from datetime import datetime, date, timedelta
from typing import Optional

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from src.database.db import Database
from src.database.migrations import run_migrations, initialize_paper_cash
from src.broker.dhan_client import DhanDataClient
from src.broker.dhan_auth import DhanAuth
from src.broker.instruments import InstrumentManager
from src.data.indicators import IndicatorEngine
from src.data.levels import LevelCalculator
from src.data.patterns import PatternDetector
from src.data.market_data import MarketDataFetcher
from src.data.universe import UniverseFilter
from src.data.data_warehouse import DataWarehouse
from src.data.market_pulse import MarketPulseAggregator
from src.data.deep_dive import DeepDiveAssembler
from src.news.news_fetcher import NewsFetcher
from src.news.macro_data import MacroDataFetcher
from src.ai.claude_client import ClaudeClient
from src.ai.prompt_formatter import PromptFormatter
from src.ai.response_parser import ResponseParser, PromptSizeManager
from src.ai.llm_logger import LLMInteractionLogger
from src.trading.portfolio_state import PortfolioStateManager
from src.trading.guardrails import GuardrailEngine
from src.trading.paper_broker import PaperBroker
from src.trading.execution_engine import ExecutionEngine, GuardrailLogger as GRLogger
from src.trading.order_reconciler import OrderReconciler
from src.trading.mis_exit import MISAutoExitEngine
from src.trading.sl_health_check import SLHealthCheck
from src.trading.performance import PerformanceTracker
from src.trading.trade_logger import TradeLogger, GuardrailLogger, PnLLogger
from src.notifications.telegram_bot import create_notifier
from src.agents.subprocess_runner import AgentSubprocessRunner
from src.agents.premarket_agent import PreMarketResearchAgent
from src.agents.watchlist_research_agent import WatchlistResearchAgent
from src.agents.risk_monitor_agent import RiskMonitorAgent
from src.agents.strategy_agent import PostMarketStrategyAgent

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Central coordinator for the entire trading bot.
    Manages the daily lifecycle: boot, market pulse loop,
    trading decisions, MIS exits, EOD review.
    """

    def __init__(self, config_path: str = "config/config.yaml"):
        # Load environment and config
        load_dotenv("config/.env")
        self.config = self._load_config(config_path)
        self._resolve_env_vars(self.config)

        # Session tracking
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._previous_watchlist: list[str] = []
        self._current_watchlist: list[dict] = []
        self._watchlist_reasons: dict[str, str] = {}
        self._is_running = False
        self._scheduler: Optional[BackgroundScheduler] = None

        # Setup logging
        self._setup_logging()

        # Initialize all components
        self._init_components()

        logger.info(f"Orchestrator initialized. Session: {self.session_id}")

    def _load_config(self, path: str) -> dict:
        """Load YAML config."""
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def _resolve_env_vars(self, config: dict):
        """Replace ${ENV_VAR} placeholders with actual values."""
        for key, value in config.items():
            if isinstance(value, dict):
                self._resolve_env_vars(value)
            elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_key = value[2:-1]
                config[key] = os.environ.get(env_key, "")

    def _setup_logging(self):
        """Configure Python logging."""
        log_dir = self.config.get("logging", {}).get("log_dir", "logs")
        os.makedirs(log_dir, exist_ok=True)

        log_level = self.config.get("logging", {}).get("level", "INFO")
        log_file = os.path.join(log_dir, "app.log")

        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )

    def _init_components(self):
        """Initialize all bot components."""
        # Database
        db_path = self.config.get("database", {}).get("path", "data/trading_bot.db")
        self.db = Database(db_path)
        run_migrations(self.db)

        # Notifications
        self.notifier = create_notifier(self.config)

        # Data client + auth (initialized in boot)
        self.data_client = None
        self.dhan_auth: Optional[DhanAuth] = None

        # Instruments
        self.instruments = InstrumentManager(data_client=None)

        # Data layer
        self.indicator_engine = IndicatorEngine()
        self.level_calculator = LevelCalculator()
        self.pattern_detector = PatternDetector()
        self.market_data: Optional[MarketDataFetcher] = None
        self.warehouse: Optional[DataWarehouse] = None
        self.pulse_aggregator: Optional[MarketPulseAggregator] = None
        self.deep_dive: Optional[DeepDiveAssembler] = None
        self.universe_filter: Optional[UniverseFilter] = None

        # News
        self.news_fetcher: Optional[NewsFetcher] = None
        self.macro_fetcher: Optional[MacroDataFetcher] = None

        # AI
        self.llm_logger = LLMInteractionLogger(self.db, self.config)
        self.claude_client: Optional[ClaudeClient] = None
        self.prompt_formatter = PromptFormatter(self.config)
        self.response_parser = ResponseParser(self.config)
        self.prompt_size_mgr = PromptSizeManager(self.config)

        # Trading
        self.portfolio_state: Optional[PortfolioStateManager] = None
        self.guardrails: Optional[GuardrailEngine] = None
        self.execution_engine: Optional[ExecutionEngine] = None
        self.order_reconciler: Optional[OrderReconciler] = None
        self.mis_exit: Optional[MISAutoExitEngine] = None
        self.sl_health: Optional[SLHealthCheck] = None
        self.performance = PerformanceTracker(self.db, self.config)

        # Lazy-loaded ticker → company-name table fed into the symbol
        # resolver (Haiku call). Built on first need from
        # config/nifty500.csv and cached for the lifetime of the run.
        self._resolver_universe_text: Optional[str] = None

        # Loggers
        self.trade_logger = TradeLogger(
            log_dir=os.path.join(
                self.config.get("logging", {}).get("log_dir", "logs"), "trades"
            )
        )
        self.guardrail_logger = GuardrailLogger(
            log_dir=os.path.join(
                self.config.get("logging", {}).get("log_dir", "logs"), "guardrails"
            )
        )
        self.pnl_logger = PnLLogger(
            log_dir=os.path.join(
                self.config.get("logging", {}).get("log_dir", "logs"), "pnl"
            )
        )

        # Agents
        self.agent_runner = AgentSubprocessRunner(self.config, self.db, self.notifier)
        self.premarket_agent = PreMarketResearchAgent(self.agent_runner, self.config)
        self.watchlist_research = WatchlistResearchAgent(self.agent_runner, self.config)
        self.risk_monitor = RiskMonitorAgent(self.agent_runner, self.config)
        self.strategy_agent = PostMarketStrategyAgent(self.agent_runner, self.config)

    # ─── BOOT SEQUENCE ───

    def boot(self):
        """
        Full system boot. Called at 8:30 AM or on manual start.
        Loads data client, universe, boots data warehouse.
        """
        logger.info("=" * 60)
        logger.info("ORCHESTRATOR BOOT SEQUENCE STARTING")
        logger.info("=" * 60)

        # Step 1: Initialize data client
        self._init_data_client()

        # Step 2: Initialize broker-dependent components
        self._init_broker_components()

        # Step 3: Universe filter
        logger.info("Step 3: Building tradeable universe...")
        universe = self._build_universe()

        # Step 4: Boot data warehouse
        logger.info("Step 4: Booting data warehouse...")
        sector_map = self._load_sector_map()
        self.warehouse.boot(universe, sector_map)

        # Share the sector map with guardrails so sector-concentration check works
        if self.guardrails and sector_map:
            self.guardrails.set_sector_map(sector_map)

        # Step 5: Fetch pre-market data
        logger.info("Step 5: Fetching pre-market data...")
        self._fetch_premarket_data()

        # Step 6: Initialize paper trading
        initialize_paper_cash(
            self.db,
            self.config.get("experiment", {}).get("starting_capital", 100000),
        )

        self._is_running = True
        logger.info("BOOT SEQUENCE COMPLETE")
        self.notifier.send_message(
            f"Bot started (Paper Mode). "
            f"Universe: {len(universe)} stocks. "
            f"Session: {self.session_id}"
        )

    def _init_data_client(self):
        """Initialize the Dhan market data client with TOTP-based auto-auth."""
        logger.info("Step 1: Initializing Dhan data client...")
        try:
            dhan_config = self.config.get("dhan", {})
            client_id = dhan_config.get("client_id", "")
            pin = dhan_config.get("pin", "")
            totp_secret = dhan_config.get("totp_secret", "")
            fallback_token = dhan_config.get("access_token", "")

            if not client_id:
                logger.warning("Dhan client_id not configured. Data client unavailable.")
                return

            # TOTP-based auto-auth: generates a fresh 24h token on boot and
            # refreshes daily via the scheduler. Falls back to DHAN_ACCESS_TOKEN
            # env if PIN/TOTP not configured (manual mode).
            self.dhan_auth = DhanAuth(
                client_id=client_id,
                pin=pin,
                totp_secret=totp_secret,
                fallback_token=fallback_token,
            )
            access_token = self.dhan_auth.get_token()

            self.data_client = DhanDataClient(
                client_id=client_id,
                access_token=access_token,
                notifier=self.notifier,
            )
            logger.info("Dhan data client initialized")
        except Exception as e:
            logger.warning(f"Dhan data client initialization failed: {e}")

    def _init_broker_components(self):
        """Initialize components that depend on data client."""
        logger.info("Step 2: Initializing components...")

        self.instruments = InstrumentManager(data_client=self.data_client)
        self.market_data = MarketDataFetcher(
            data_client=self.data_client,
            instrument_manager=self.instruments,
        )

        self.warehouse = DataWarehouse(
            market_data=self.market_data,
            indicator_engine=self.indicator_engine,
            level_calculator=self.level_calculator,
            pattern_detector=self.pattern_detector,
            config=self.config,
        )

        self.pulse_aggregator = MarketPulseAggregator(self.warehouse, self.config)
        self.deep_dive = DeepDiveAssembler(self.warehouse, self.config)

        self.universe_filter = UniverseFilter(
            instrument_manager=self.instruments, config=self.config,
        )

        self.macro_fetcher = MacroDataFetcher(
            data_client=self.data_client,
            config=self.config,
        )

        # AI client
        self.claude_client = ClaudeClient(
            config=self.config,
            llm_logger=self.llm_logger,
            notifier=self.notifier,
            session_id=self.session_id,
        )

        self.news_fetcher = NewsFetcher(
            config=self.config,
            claude_client=self.claude_client,
        )

        # Portfolio state
        self.portfolio_state = PortfolioStateManager(
            data_client=self.data_client,
            db=self.db,
            config=self.config,
        )

        # Guardrails
        self.guardrails = GuardrailEngine(
            config=self.config,
            portfolio_state=self.portfolio_state,
            instrument_manager=self.instruments,
            notifier=self.notifier,
        )

        # Paper broker
        self.paper_broker = PaperBroker(
            db=self.db,
            data_client=self.data_client,
            market_data=self.market_data,
            notifier=self.notifier,
        )

        # Execution
        self.execution_engine = ExecutionEngine(
            db=self.db,
            config=self.config,
            notifier=self.notifier,
            trade_logger=self.trade_logger,
            paper_broker=self.paper_broker,
        )

        # Order reconciler
        self.order_reconciler = OrderReconciler(
            db=self.db,
            notifier=self.notifier,
            market_data=self.market_data,
            paper_broker=self.paper_broker,
        )

        # MIS exit engine
        self.mis_exit = MISAutoExitEngine(
            portfolio_state=self.portfolio_state,
            config=self.config,
            notifier=self.notifier,
            db=self.db,
            paper_broker=self.paper_broker,
            data_client=self.data_client,
        )

        # SL health check
        self.sl_health = SLHealthCheck(
            db=self.db,
            notifier=self.notifier,
            config=self.config,
            market_data=self.market_data,
            paper_broker=self.paper_broker,
        )

    def _build_universe(self) -> list[str]:
        """Build the tradeable universe."""
        if self.data_client:
            try:
                self.instruments.refresh_instruments()
            except Exception as e:
                logger.warning(f"Failed to refresh instruments: {e}")
                self.instruments.load_cache()

        if self.universe_filter:
            return self.universe_filter.refresh()
        return []

    def _load_sector_map(self) -> dict[str, str]:
        """
        Load stock-to-sector mapping. Combines:
          1. Nifty 500 CSV (NSE's official industry tagging — covers ~500 stocks)
          2. Curated sector_mapping.yaml (fine-grained categories — overrides CSV)
        The yaml takes precedence so our existing NIFTY sector index groupings
        (Banking, IT, Pharma) are preserved for the heatmap.
        """
        sector_map: dict[str, str] = {}

        # 1. Load broad Nifty 500 "Industry" tags
        import os
        import csv
        csv_path = "config/nifty500.csv"
        if os.path.exists(csv_path):
            try:
                with open(csv_path, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sym = (row.get("Symbol") or "").strip()
                        industry = (row.get("Industry") or "").strip()
                        if sym and industry:
                            sector_map[sym] = industry
            except Exception as e:
                logger.warning(f"Failed to read nifty500.csv for sectors: {e}")

        # 2. Overlay curated sector map (stocks in the yaml get the refined tag)
        try:
            with open("config/sector_mapping.yaml", "r") as f:
                data = yaml.safe_load(f)
            for sector_name, info in (data or {}).get("sectors", {}).items():
                for stock in (info or {}).get("stocks", []) or []:
                    sector_map[stock] = sector_name
        except Exception as e:
            logger.warning(f"Failed to load curated sector map: {e}")

        logger.info(f"Sector map assembled: {len(sector_map)} stocks tagged")
        return sector_map

    def _fetch_premarket_data(self):
        """Fetch pre-market data: news, macro, global cues."""
        try:
            self.macro_fetcher.get_macro_snapshot()
        except Exception as e:
            logger.warning(f"Pre-market macro fetch failed: {e}")

        try:
            # Warm the RSS cache — the first Market Pulse cycle will reuse these
            # entries (15-min TTL) rather than re-fetching 200 items from scratch.
            self.news_fetcher.fetch_market_headlines(max_headlines=200, per_source=60)
        except Exception as e:
            logger.warning(f"Pre-market news fetch failed: {e}")

    # ─── TRADING CYCLE ───

    def run_market_pulse_cycle(self):
        """
        Complete Market Pulse cycle:
        1. Refresh data
        2. Send Market Pulse to Sonnet -> get watchlist
        3. Assemble deep dive data for watchlist
        4. Send Trading Decision to Opus -> get decisions
        5. Validate through guardrails
        6. Execute valid orders
        """
        if not self._is_running:
            return

        if self.claude_client and self.claude_client.circuit_breaker.is_safe_mode():
            logger.warning("SAFE MODE: Skipping trading cycle")
            return

        cycle_id = datetime.now().strftime("%H%M%S")
        logger.info(f"--- Market Pulse Cycle {cycle_id} ---")

        try:
            # Step 1: Refresh data
            self._refresh_data()

            # Step 2: Market Pulse (Sonnet)
            watchlist = self._run_market_pulse()
            if not watchlist:
                logger.info("No watchlist returned. Skipping trading decision.")
                return

            # Step 3: Deep dive + watchlist research IN PARALLEL
            symbols = [w["symbol"] for w in watchlist]

            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as executor:
                deep_future = executor.submit(self.deep_dive.assemble, symbols)
                research_future = executor.submit(self._run_watchlist_research, symbols)

                deep_packs = deep_future.result()
                supplementary_research = research_future.result()

            # Step 4: Trading Decision (Opus)
            held = self.portfolio_state.get_held_symbols()
            batches = self.prompt_size_mgr.split_watchlist(symbols, held)

            all_decisions = []
            for i, batch in enumerate(batches):
                batch_packs = [p for p in deep_packs if p["symbol"] in batch]
                decisions = self._run_trading_decision(
                    batch_packs, i, len(batches),
                    supplementary_research=supplementary_research,
                )
                if decisions:
                    all_decisions.extend(decisions.get("decisions", []))

            # Step 5 & 6: Validate and execute
            if all_decisions:
                self._validate_and_execute(all_decisions)

            # Mark-to-market snapshot so the dashboard reflects live portfolio value
            # between EOD snapshots. Non-critical — never crash the cycle on failure.
            try:
                self.performance.save_portfolio_snapshot(
                    self.portfolio_state.get_portfolio_state()
                )
            except Exception as e:
                logger.warning(f"Portfolio snapshot failed (non-critical): {e}")

        except Exception as e:
            logger.error(f"Market Pulse cycle failed: {e}", exc_info=True)

    def _refresh_data(self):
        """Refresh quotes, indicators, and aggregations."""
        if not self.warehouse or not self.warehouse.is_booted:
            return

        try:
            universe = self.warehouse.get_loaded_symbols()
            self.warehouse.refresh_quotes(universe)

            # Refresh intraday for watchlist stocks
            if self._previous_watchlist:
                self.warehouse.refresh_intraday(self._previous_watchlist)
        except Exception as e:
            logger.error(f"Data refresh failed: {e}")

    def _run_market_pulse(self) -> list[dict]:
        """Run Market Pulse call to Sonnet. Returns watchlist."""
        try:
            # Build indices data
            indices = self._fetch_index_quotes()

            # Build pulse data
            pulse_data = self.pulse_aggregator.build_pulse()

            # Sector heatmap
            sector_heatmap = self.pulse_aggregator.build_sector_heatmap(indices)

            # Macro
            macro = self.macro_fetcher.get_macro_snapshot()

            # News: raw fetch + mechanical pre-filter + Haiku India-relevance filter
            headlines = self.news_fetcher.fetch_and_filter_headlines(
                max_raw=200, per_source=60,
            )

            # ETF snapshot
            etf_quotes = self._fetch_etf_quotes()
            etf_snapshot = self.pulse_aggregator.build_etf_snapshot(etf_quotes)

            # Portfolio state
            portfolio = self.portfolio_state.get_portfolio_state()

            # Pre-market research (from the 7:30 AM agent, if it ran)
            premarket_brief = self.premarket_agent.get_latest_brief()
            if premarket_brief:
                logger.info("Attaching pre-market research to Market Pulse prompt")

            # Format prompt
            prompt = self.prompt_formatter.format_market_pulse(
                indices=indices,
                pulse_data=pulse_data,
                sector_heatmap=sector_heatmap,
                macro=macro,
                news_headlines=headlines,
                etf_snapshot=etf_snapshot,
                portfolio_state=portfolio,
                previous_watchlist=self._previous_watchlist,
                premarket_research=premarket_brief,
            )

            # Call Sonnet
            response = self.claude_client.call_market_pulse(prompt)
            if not response:
                return []

            # Parse response
            parsed = self.response_parser.parse_market_pulse(response)
            if not parsed:
                return []

            watchlist = parsed.get("watchlist", [])

            # Ensure held stocks are included
            held = self.portfolio_state.get_held_symbols()
            watchlist_symbols = {w["symbol"] for w in watchlist}
            for sym in held:
                if sym not in watchlist_symbols:
                    watchlist.append({
                        "symbol": sym,
                        "exchange": "NSE",
                        "reason": "Currently held — need updated data for position management",
                    })

            # Resolve any symbols that don't match a tradeable instrument.
            # Sonnet occasionally writes long-form names (ADANITOTALGAS,
            # JIOFINL, VEDANTA) instead of the canonical NSE ticker. We
            # batch all unresolved symbols into one Haiku call asking for
            # the correct tickers, validate each response against the
            # instrument cache, then rewrite or drop accordingly.
            watchlist = self._resolve_unresolved_symbols(watchlist)

            # Update tracking
            self._previous_watchlist = [w["symbol"] for w in watchlist]
            self._current_watchlist = watchlist
            self._watchlist_reasons = {
                w["symbol"]: w.get("reason", "") for w in watchlist
            }

            logger.info(
                f"Market Pulse: {parsed.get('market_read', '')[:100]}... "
                f"Watchlist: {len(watchlist)} stocks"
            )

            return watchlist

        except Exception as e:
            logger.error(f"Market Pulse failed: {e}", exc_info=True)
            return []

    def _resolve_unresolved_symbols(self, watchlist: list[dict]) -> list[dict]:
        """
        Fix Sonnet's symbol hallucinations before deep_dive sees them.

        Sonnet sometimes outputs long-form names (ADANITOTALGAS, JIOFINL,
        VEDANTA) instead of the canonical NSE ticker (ATGL, JIOFIN, VEDL).
        Anything that doesn't resolve in the instrument cache is batched
        into a single Haiku call asking for the correct tickers, with the
        full Nifty 500 ticker → company name table embedded in the prompt
        so Haiku is selecting from a constrained set, not generating from
        memory. Each response is then validated against the instrument
        cache — successful matches replace the original symbol; everything
        else is dropped. Zero LLM cost on cycles where every symbol
        resolves; ~₹0.50 per fire on cycles where one or more don't.
        """
        if not watchlist:
            return watchlist

        unresolved = [
            w for w in watchlist
            if self.instruments.get_token(w.get("exchange", "NSE"), w.get("symbol", "")) is None
        ]
        if not unresolved:
            return watchlist

        original_symbols = [w["symbol"] for w in unresolved]
        logger.info(
            f"Watchlist has {len(original_symbols)} unresolved symbol(s): "
            f"{original_symbols} — calling Haiku for resolution"
        )

        universe_text = self._get_resolver_universe_text()
        prompt = (
            "You will see a list of mistyped or long-form Indian company "
            "references. For each, identify the correct NSE ticker symbol "
            "from the canonical table provided below. The TICKER MUST APPEAR "
            "IN THE TABLE — do not invent tickers. If no entry in the table "
            "matches with high confidence, return UNKNOWN.\n\n"
            "═══ CANONICAL NSE TICKER TABLE (Nifty 500) ═══\n"
            f"{universe_text}\n"
            "═══ END TABLE ═══\n\n"
            "Inputs to resolve:\n"
            + "\n".join(f"- {s}" for s in original_symbols)
            + '\n\nRespond ONLY as a JSON object: '
            '{"INPUT_STRING": "TICKER_FROM_TABLE_OR_UNKNOWN", ...}'
        )

        try:
            response = self.claude_client.call_haiku(
                prompt, call_type="SYMBOL_RESOLUTION"
            )
        except Exception as e:
            logger.warning(f"Haiku symbol-resolution call failed: {e}")
            response = None

        mapping: dict[str, str] = {}
        if isinstance(response, dict):
            mapping = {
                str(k): str(v).strip().upper()
                for k, v in response.items()
                if isinstance(v, str)
            }

        resolved_log: list[str] = []
        dropped_log: list[str] = []
        kept: list[dict] = []
        for w in watchlist:
            sym = w.get("symbol", "")
            exch = w.get("exchange", "NSE")
            if self.instruments.get_token(exch, sym) is not None:
                kept.append(w)
                continue
            candidate = mapping.get(sym, "")
            if (
                candidate
                and candidate != "UNKNOWN"
                and self.instruments.get_token(exch, candidate) is not None
            ):
                resolved_log.append(f"{sym}→{candidate}")
                kept.append({**w, "symbol": candidate})
            else:
                dropped_log.append(sym)

        if resolved_log or dropped_log:
            logger.info(
                f"Symbol resolution: resolved={resolved_log or 'none'}, "
                f"dropped={dropped_log or 'none'}"
            )

        # Dedupe by (exchange, symbol). After resolution, two entries can
        # collapse onto the same canonical ticker — e.g., the held-stock
        # injection added ATGL while Sonnet's hallucinated ADANITOTALGAS
        # also rewrote to ATGL. Without this, deep_dive would double-process
        # and Opus would see the same stock twice with conflicting reasons.
        # First occurrence wins so held-stock entries (added before the
        # resolver) take precedence over hallucinated duplicates.
        seen: set[tuple[str, str]] = set()
        deduped: list[dict] = []
        for w in kept:
            key = (w.get("exchange", "NSE"), w.get("symbol", ""))
            if key in seen:
                logger.info(f"Symbol resolution: deduped {key[1]} (duplicate after rewrite)")
                continue
            seen.add(key)
            deduped.append(w)
        return deduped

    def _get_resolver_universe_text(self) -> str:
        """
        Build the canonical ticker → company name table fed into the symbol
        resolver. Read once from config/nifty500.csv, cached on the instance
        for the lifetime of the orchestrator.
        """
        if self._resolver_universe_text is not None:
            return self._resolver_universe_text
        import csv as _csv
        rows: list[str] = []
        try:
            with open("config/nifty500.csv") as f:
                for row in _csv.DictReader(f):
                    sym = (row.get("Symbol") or "").strip()
                    name = (row.get("Company Name") or "").strip()
                    if sym and name:
                        rows.append(f"{sym:<14}{name}")
        except Exception as e:
            logger.warning(f"Could not load nifty500 universe for resolver: {e}")
        self._resolver_universe_text = "\n".join(rows)
        return self._resolver_universe_text

    def _run_trading_decision(
        self, deep_packs: list, batch_idx: int, total_batches: int,
        supplementary_research: list = None,
    ) -> Optional[dict]:
        """Run Trading Decision call to Opus for a batch of stocks."""
        try:
            indices = self._fetch_index_quotes()
            macro = self.macro_fetcher.get_macro_snapshot()
            portfolio = self.portfolio_state.get_portfolio_state()
            existing = self.portfolio_state.get_existing_positions_for_prompt()
            open_orders = self.portfolio_state.get_working_orders()
            perf = self.performance.get_rolling_performance(days=5)

            etf_quotes = self._fetch_etf_quotes()
            etf_snapshot = self.pulse_aggregator.build_etf_snapshot(etf_quotes) if self.pulse_aggregator else []

            # Filter supplementary research to the stocks in this batch
            batch_symbols = {p["symbol"] for p in deep_packs}
            batch_research = None
            if supplementary_research:
                batch_research = [
                    r for r in supplementary_research
                    if r.get("symbol") in batch_symbols
                ]

            prompt = self.prompt_formatter.format_trading_decision(
                indices=indices,
                macro=macro,
                portfolio_state=portfolio,
                watchlist_reasons=self._watchlist_reasons,
                deep_dive_packs=deep_packs,
                etf_snapshot=etf_snapshot,
                existing_positions=existing,
                performance_context=perf,
                supplementary_research=batch_research,
                open_orders=open_orders,
            )

            response = self.claude_client.call_trading_decision(prompt)
            if not response:
                return None

            parsed = self.response_parser.parse_trading_decision(response)
            if parsed:
                logger.info(
                    f"Trading Decision (batch {batch_idx+1}/{total_batches}): "
                    f"{len(parsed.get('decisions', []))} decisions, "
                    f"bias={parsed.get('market_assessment', {}).get('bias', 'N/A')}"
                )
            return parsed

        except Exception as e:
            logger.error(f"Trading Decision failed: {e}", exc_info=True)
            return None

    def _validate_and_execute(self, decisions: list[dict]):
        """Validate decisions through guardrails and execute valid ones."""
        for decision in decisions:
            action = decision.get("action", "").upper()
            if action in ("NO_ACTION", "HOLD"):
                continue

            # Validate
            result = self.guardrails.validate_order(decision)

            # Log guardrail result
            gr_logger = GRLogger(self.db, self.guardrail_logger)
            gr_logger.log_validation(decision, result)

            if result.is_valid:
                # Execute the validated (potentially modified) order
                exec_result = self.execution_engine.execute_order(
                    result.order, self.session_id
                )

                logger.info(
                    f"Executed: {action} {decision.get('symbol')} "
                    f"-> {exec_result.get('status')}"
                )
            else:
                logger.warning(
                    f"BLOCKED: {action} {decision.get('symbol')} — "
                    f"{'; '.join(result.errors)}"
                )

                # Log blocked trade to CSV too
                if self.trade_logger:
                    self.trade_logger.log_trade({
                        **decision,
                        "status": "REJECTED",
                        "guardrail_result": "FAILED",
                        "guardrail_errors": "; ".join(result.errors),
                        "mode": "PAPER",
                    })

    # ─── EOD SEQUENCE ───

    def run_eod_review(self):
        """End-of-day review and summary."""
        logger.info("--- EOD Review ---")

        try:
            # Save portfolio snapshot
            portfolio = self.portfolio_state.get_portfolio_state()
            self.performance.save_portfolio_snapshot(portfolio)

            # Rebuild LLM daily costs
            self.llm_logger.rebuild_daily_costs()

            # Save daily summary
            self.performance.save_daily_summary(
                portfolio_value=portfolio.get("total_value", 0)
            )

            # Send Telegram summary
            summary = self.performance.get_daily_summary()
            daily_cost = self.llm_logger.get_daily_cost()

            msg = (
                f"EOD Summary — Day {self._get_day_number()}\n"
                f"Trades: {summary.get('trades_count', 0)} "
                f"(W:{summary.get('wins', 0)} L:{summary.get('losses', 0)})\n"
                f"Day P&L: INR {summary.get('total_pnl', 0):+,.0f}\n"
                f"Cumulative: INR {summary.get('cumulative_pnl', 0):+,.0f}\n"
                f"Portfolio: INR {portfolio.get('total_value', 0):,.0f}\n"
                f"LLM cost: ${daily_cost.get('total_cost_usd', 0):,.4f}"
            )
            self.notifier.send_daily_summary(msg)

            logger.info("EOD review complete")

        except Exception as e:
            logger.error(f"EOD review failed: {e}", exc_info=True)

        # Force-refresh the daily candle parquet cache for the full universe
        # AFTER the user-facing summary has been sent. Bypasses the cache
        # freshness check and re-fetches via Dhan so tomorrow's 09:00
        # refresh_quotes hits a fresh cache instead of stampeding the API
        # for ~22 minutes. Bounded by Dhan's 1-req-per-2s rate limit
        # (~17 min wall time for ~510 stocks). Non-critical — never crash
        # EOD on failure.
        try:
            if self.warehouse:
                logger.info("Refreshing daily candle cache for tomorrow...")
                self.warehouse.warm_universe(force_refresh=True)
        except Exception as e:
            logger.warning(f"Universe cache refresh failed (non-critical): {e}")

    def run_daily_backup(self):
        """Back up database, logs, and config."""
        backup_dir = self.config.get("backup", {}).get("local_dir", "backups")
        today = date.today().isoformat()
        dest = os.path.join(backup_dir, today)

        try:
            os.makedirs(dest, exist_ok=True)

            # Backup database
            db_path = self.config.get("database", {}).get("path", "data/trading_bot.db")
            if os.path.exists(db_path):
                shutil.copy2(db_path, os.path.join(dest, "trading_bot.db"))

            # Backup config
            shutil.copytree("config", os.path.join(dest, "config"), dirs_exist_ok=True)

            # Backup today's logs
            log_dir = self.config.get("logging", {}).get("log_dir", "logs")
            if os.path.exists(log_dir):
                shutil.copytree(log_dir, os.path.join(dest, "logs"), dirs_exist_ok=True)

            logger.info(f"Daily backup saved to {dest}")
        except Exception as e:
            logger.error(f"Backup failed: {e}")

    # ─── SCHEDULER ───

    def start_scheduler(self):
        """Start the APScheduler with all scheduled jobs."""
        self._scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

        # Market Pulse cycle: every 30 min during market hours
        pulse_interval = self.config.get("pipeline", {}).get(
            "market_pulse_interval_minutes", 30
        )
        self._scheduler.add_job(
            self.run_market_pulse_cycle,
            CronTrigger(
                day_of_week="mon-fri",
                hour="9-14",
                minute=f"*/{pulse_interval}",
                timezone="Asia/Kolkata",
            ),
            id="market_pulse_cycle",
            replace_existing=True,
        )

        # SL health check: every 5 min
        sl_interval = self.config.get("resilience", {}).get(
            "sl_health_check_interval_min", 5
        )
        self._scheduler.add_job(
            lambda: self.sl_health.check() if self.sl_health else None,
            CronTrigger(
                day_of_week="mon-fri",
                hour="9-15",
                minute=f"*/{sl_interval}",
                timezone="Asia/Kolkata",
            ),
            id="sl_health_check",
            replace_existing=True,
        )

        # Paper OHLC-based SL/target/LIMIT fill reconciliation every 5 min
        self._scheduler.add_job(
            lambda: self.order_reconciler.reconcile_paper_sl_targets()
            if self.order_reconciler else None,
            CronTrigger(
                day_of_week="mon-fri",
                hour="9-15",
                minute="*/5",
                timezone="Asia/Kolkata",
            ),
            id="paper_sl_target_reconcile",
            replace_existing=True,
        )

        # MIS Auto-Exit stages (INDEPENDENT jobs)
        if self.mis_exit:
            self._scheduler.add_job(
                self.mis_exit.stage_1_graceful_exit,
                CronTrigger(day_of_week="mon-fri", hour=15, minute=0, timezone="Asia/Kolkata"),
                id="mis_exit_stage_1", replace_existing=True,
            )
            self._scheduler.add_job(
                self.mis_exit.stage_2_retry_unfilled,
                CronTrigger(day_of_week="mon-fri", hour=15, minute=5, timezone="Asia/Kolkata"),
                id="mis_exit_stage_2", replace_existing=True,
            )
            self._scheduler.add_job(
                self.mis_exit.stage_3_force_market_close,
                CronTrigger(day_of_week="mon-fri", hour=15, minute=10, timezone="Asia/Kolkata"),
                id="mis_exit_stage_3", replace_existing=True,
            )
            self._scheduler.add_job(
                self.mis_exit.stage_4_emergency_check,
                CronTrigger(day_of_week="mon-fri", hour=15, minute=12, timezone="Asia/Kolkata"),
                id="mis_exit_stage_4", replace_existing=True,
            )

        # EOD review
        self._scheduler.add_job(
            self.run_eod_review,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=40, timezone="Asia/Kolkata"),
            id="eod_review", replace_existing=True,
        )

        # Daily backup — runs at 4:30 PM (not 4:00) to give the EOD
        # cache refresh (~17 min wall time) a comfortable buffer before
        # the backup snapshots files. Avoids any race between the
        # warm_universe parquet writer and the backup tarball.
        self._scheduler.add_job(
            self.run_daily_backup,
            CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone="Asia/Kolkata"),
            id="daily_backup", replace_existing=True,
        )

        # ─── AGENT JOBS ───

        # Pre-Market Research Agent: 7:30 AM on weekdays
        self._scheduler.add_job(
            self._run_premarket_research,
            CronTrigger(day_of_week="mon-fri", hour=7, minute=30, timezone="Asia/Kolkata"),
            id="premarket_research", replace_existing=True,
        )

        # Risk Monitor Agent: every 30 min during market hours
        self._scheduler.add_job(
            self._run_risk_monitor,
            CronTrigger(
                day_of_week="mon-fri", hour="9-15", minute="*/30",
                timezone="Asia/Kolkata",
            ),
            id="risk_monitor", replace_existing=True,
        )

        # Post-Market Strategy Agent: 4:00 PM on weekdays
        self._scheduler.add_job(
            self._run_strategy_review_daily,
            CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone="Asia/Kolkata"),
            id="strategy_review_daily", replace_existing=True,
        )

        # Weekly Strategy Review: Saturday 9:00 AM
        self._scheduler.add_job(
            self._run_strategy_review_weekly,
            CronTrigger(day_of_week="sat", hour=9, minute=0, timezone="Asia/Kolkata"),
            id="strategy_review_weekly", replace_existing=True,
        )

        # Daily Dhan token refresh: every day at 06:30 IST (well before 08:30 boot)
        # Generates a fresh 24h access token via TOTP and caches it on disk.
        self._scheduler.add_job(
            self._run_token_refresh,
            CronTrigger(hour=6, minute=30, timezone="Asia/Kolkata"),
            id="dhan_token_refresh", replace_existing=True,
        )

        self._scheduler.start()
        logger.info("Scheduler started with all jobs")

    # ─── AUTH ───

    def _run_token_refresh(self):
        """
        Daily scheduled Dhan token refresh. Generates a fresh 24h access token
        via TOTP and re-points the DhanDataClient at it. Runs at 06:30 IST so
        the new token is in place before the 08:30 boot sequence / 09:15 open.
        """
        if not self.dhan_auth:
            logger.warning("Token refresh skipped: DhanAuth not configured")
            return
        try:
            new_token = self.dhan_auth.force_refresh()
            if self.data_client and hasattr(self.data_client, "dhan"):
                # The dhanhq SDK caches the token in TWO places on its client:
                # self.access_token (attribute) and self.header['access-token']
                # (the dict passed to every requests.Session.get/post call).
                # Setting only the attribute leaves the old token in every HTTP
                # header — authenticated endpoints like historical_daily_data
                # then return DH-901 Invalid_Authentication for the rest of the
                # day, which is exactly what we saw on 2026-04-23 (1,591
                # failures between 09:00 and 15:55). Update both, plus any
                # session-level default headers, so the refresh actually lands.
                dhan = self.data_client.dhan
                dhan.access_token = new_token
                if isinstance(getattr(dhan, "header", None), dict):
                    dhan.header["access-token"] = new_token
                session = getattr(dhan, "session", None)
                if session is not None and hasattr(session, "headers"):
                    session.headers["access-token"] = new_token
                logger.info("Dhan token refreshed and wired into data client")
            else:
                logger.info("Dhan token refreshed (data client will pick it up on next init)")
        except Exception as e:
            logger.error(f"Dhan token refresh failed: {e}")
            if self.notifier:
                self.notifier.send_error_alert("Dhan token refresh failed", str(e))

    # ─── AGENT RUNNERS ───

    def _run_premarket_research(self):
        """Run pre-market research agent."""
        try:
            result = self.premarket_agent.run()
            logger.info(f"Pre-market research: {result.status} ({result.duration_seconds:.1f}s)")
        except Exception as e:
            logger.error(f"Pre-market research agent failed: {e}")

    def _run_risk_monitor(self):
        """Run risk monitor agent."""
        try:
            result = self.risk_monitor.run()
            logger.info(f"Risk monitor: {result.status} ({result.duration_seconds:.1f}s)")
            # Alert on high risk
            if result.output_data and result.output_data.get("risk_level") in ("HIGH", "CRITICAL"):
                msg = f"Risk Alert: {result.output_data.get('risk_level')} — {', '.join(result.output_data.get('findings', [])[:2])}"
                if self.notifier:
                    self.notifier.send_error_alert(msg)
        except Exception as e:
            logger.error(f"Risk monitor agent failed: {e}")

    def _run_strategy_review_daily(self):
        """Run daily strategy review agent."""
        try:
            result = self.strategy_agent.run_daily()
            logger.info(f"Strategy review (daily): {result.status} ({result.duration_seconds:.1f}s)")
        except Exception as e:
            logger.error(f"Strategy review agent failed: {e}")

    def _run_strategy_review_weekly(self):
        """Run weekly strategy review agent."""
        try:
            result = self.strategy_agent.run_weekly()
            logger.info(f"Strategy review (weekly): {result.status} ({result.duration_seconds:.1f}s)")
        except Exception as e:
            logger.error(f"Weekly strategy review agent failed: {e}")

    def _run_watchlist_research(self, symbols: list[str]) -> list[dict]:
        """Run watchlist research agents in parallel. Returns research data."""
        try:
            runs = self.watchlist_research.run_parallel(symbols)
            success = sum(1 for r in runs if r.status == "SUCCESS")
            logger.info(f"Watchlist research: {success}/{len(runs)} batches succeeded")
            return self.watchlist_research.get_all_research()
        except Exception as e:
            logger.error(f"Watchlist research agents failed: {e}")
            return []

    def stop(self):
        """
        Graceful shutdown. Idempotent — safe to call multiple times.

        SIGTERM handler in main.py calls stop() then sys.exit(0); the
        resulting SystemExit unwinds through main()'s `finally` clause,
        which calls stop() a second time. Without the `running` guard,
        the second call hits an already-shut-down scheduler and raises
        SchedulerNotRunningError, exiting the process with code 1.
        """
        self._is_running = False
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self.db:
            self.db.close()
        logger.info("Orchestrator stopped")

    # ─── HELPERS ───

    def _fetch_index_quotes(self) -> dict:
        """
        Fetch index quotes + compute real change_pct using a daily-candle
        lookup for previous close. Index prev_close is cached for the rest
        of the day (indices' previous close doesn't change intraday).
        """
        if not self.data_client:
            return {}

        index_keys = [
            "NSE:NIFTY 50", "NSE:NIFTY BANK", "NSE:NIFTY IT",
            "NSE:NIFTY PHARMA", "NSE:NIFTY AUTO", "NSE:NIFTY METAL",
            "NSE:NIFTY REALTY", "NSE:NIFTY ENERGY", "NSE:NIFTY PSU BANK",
            "NSE:INDIA VIX",
        ]

        # Lazy init intra-day prev_close cache
        if not hasattr(self, "_index_prev_close_cache"):
            self._index_prev_close_cache: dict[str, tuple[str, float]] = {}

        today = date.today().isoformat()

        try:
            quotes = self.data_client.get_quote(index_keys)
            for key, data in quotes.items():
                ltp = data.get("last_price", 0)
                cached = self._index_prev_close_cache.get(key)
                prev_close = cached[1] if cached and cached[0] == today else 0
                if prev_close == 0:
                    # Fetch from daily candles (IDX_I segment)
                    try:
                        prev_close = self.data_client.get_index_prev_close(key)
                        if prev_close > 0:
                            self._index_prev_close_cache[key] = (today, prev_close)
                    except Exception:
                        prev_close = 0

                if prev_close > 0 and ltp > 0:
                    data["change_pct"] = round(((ltp - prev_close) / prev_close) * 100, 2)
                    # Overwrite ohlc.close with actual prev_close so downstream sees it
                    if "ohlc" in data:
                        data["ohlc"]["close"] = prev_close
                else:
                    data["change_pct"] = 0
            return quotes
        except Exception as e:
            logger.warning(f"Failed to fetch index quotes: {e}")
            return {}

    def _fetch_etf_quotes(self) -> dict:
        """Fetch ETF quotes."""
        if not self.data_client:
            return {}

        approved = self.config.get("etfs", {}).get("approved", [])
        keys = [f"NSE:{etf}" for etf in approved]
        try:
            return self.data_client.get_quote(keys)
        except Exception as e:
            logger.warning(f"Failed to fetch ETF quotes: {e}")
            return {}

    def _get_day_number(self) -> int:
        """Get current experiment day number."""
        start_str = self.config.get("experiment", {}).get("start_date", "2026-03-01")
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        return (date.today() - start_date).days + 1
