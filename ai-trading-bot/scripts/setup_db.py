#!/usr/bin/env python3
"""
Initialize the trading bot database.
Run this script once to create all tables, indexes, and views.
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import yaml
import logging

from src.database.db import Database
from src.database.migrations import run_migrations, initialize_paper_cash

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    # Load config
    config_path = os.path.join(project_root, "config", "config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    db_path = os.path.join(project_root, config["database"]["path"])
    logger.info(f"Initializing database at: {db_path}")

    db = Database(db_path)
    run_migrations(db)

    starting_capital = config["experiment"]["starting_capital"]
    initialize_paper_cash(db, starting_capital)

    # Verify tables
    tables = db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    logger.info(f"Tables created: {[t['name'] for t in tables]}")

    views = db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
    )
    logger.info(f"Views created: {[v['name'] for v in views]}")

    db.close()
    logger.info("Database setup complete!")


if __name__ == "__main__":
    main()
