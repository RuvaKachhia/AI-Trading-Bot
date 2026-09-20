"""
AI Trading Bot — Main Entry Point.

Usage:
    python main.py              # Normal start (boot + scheduler)
    python main.py --once       # Run one Market Pulse cycle then exit
    python main.py --eod        # Run EOD review only
    python main.py --backup     # Run daily backup only
"""

import argparse
import signal
import sys
import time

from src.orchestrator import Orchestrator


def main():
    parser = argparse.ArgumentParser(description="AI Trading Bot")
    parser.add_argument(
        "--config", default="config/config.yaml",
        help="Path to config YAML (default: config/config.yaml)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single Market Pulse cycle and exit",
    )
    parser.add_argument(
        "--eod", action="store_true",
        help="Run EOD review only",
    )
    parser.add_argument(
        "--backup", action="store_true",
        help="Run daily backup only",
    )
    args = parser.parse_args()

    orchestrator = Orchestrator(config_path=args.config)

    # Graceful shutdown on Ctrl+C / SIGTERM
    def shutdown(sig, frame):
        print("\nShutting down...")
        orchestrator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Boot
    orchestrator.boot()

    if args.backup:
        orchestrator.run_daily_backup()
        orchestrator.stop()
        return

    if args.eod:
        orchestrator.run_eod_review()
        orchestrator.stop()
        return

    if args.once:
        orchestrator.run_market_pulse_cycle()
        orchestrator.stop()
        return

    # Normal mode: start scheduler and keep alive
    orchestrator.start_scheduler()

    print("Bot running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        orchestrator.stop()


if __name__ == "__main__":
    main()
