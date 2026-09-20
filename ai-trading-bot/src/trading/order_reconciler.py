"""
Order Reconciliation Loop.
Paper mode: delegates OHLC-based fill simulation to PaperBroker.
"""

import logging

logger = logging.getLogger(__name__)


class OrderReconciler:
    """
    Paper trading order reconciliation.
    Delegates OHLC-based SL/target/LIMIT fill simulation to PaperBroker.
    """

    def __init__(self, db, notifier=None, market_data=None, paper_broker=None):
        self.db = db
        self.notifier = notifier
        self.market_data = market_data
        self.paper_broker = paper_broker

    def reconcile_paper_sl_targets(self):
        """
        Paper mode: delegate OHLC-based SL/target/LIMIT fill simulation
        to PaperBroker. Called every 5 minutes via APScheduler.
        """
        try:
            self.paper_broker.reconcile_sl_orders()
            self.paper_broker.reconcile_limit_orders()
        except Exception as e:
            logger.error(f"Paper SL/target reconciliation error: {e}")
