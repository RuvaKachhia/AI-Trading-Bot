"""
Post-Market Strategy Agent.
Runs daily at 4 PM and weekly on Saturday morning.
Reviews trades, finds patterns, and can modify system prompt + guardrails.
"""

import json
import logging
import os
from datetime import datetime

from src.agents.subprocess_runner import AgentSubprocessRunner, AgentRun

logger = logging.getLogger(__name__)


class PostMarketStrategyAgent:
    """Reviews performance and evolves the trading strategy."""

    def __init__(self, runner: AgentSubprocessRunner, config: dict):
        self.runner = runner
        self.config = config
        self._project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self._prompts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "prompts"
        )

    def run_daily(self) -> AgentRun:
        """Run daily post-market review at 4 PM."""
        return self._run("daily")

    def run_weekly(self) -> AgentRun:
        """Run weekly strategy review on Saturday morning."""
        return self._run("weekly")

    def _run(self, review_type: str) -> AgentRun:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = self.runner.get_output_dir(date_str)
        output_path = os.path.join(output_dir, f"strategy_review_{review_type}.json")
        changelog_path = os.path.join(output_dir, "strategy_changelog.json")

        db_path = os.path.join(
            self._project_root,
            self.config.get("database", {}).get("path", "data/trading_bot.db"),
        )
        system_prompt_path = os.path.join(
            self._project_root, "src", "ai", "system_prompt.py"
        )
        risk_config_path = os.path.join(
            self._project_root, "src", "agents", "risk_config.yaml"
        )
        config_path = os.path.join(
            self._project_root, "config", "config.yaml"
        )

        prompt_template = self._load_prompt()
        prompt = (
            prompt_template
            .replace("{db_path}", db_path)
            .replace("{system_prompt_path}", system_prompt_path)
            .replace("{risk_config_path}", risk_config_path)
            .replace("{config_path}", config_path)
            .replace("{changelog_path}", changelog_path)
            .replace("{output_path}", output_path)
        )

        # Weekly reviews get more time and turns
        timeout = 1500 if review_type == "weekly" else 1200
        max_turns = 60 if review_type == "weekly" else 50

        return self.runner.run_agent(
            agent_name=f"strategy_review_{review_type}",
            prompt=prompt,
            model="claude-opus-4-7[1M]",
            output_file=output_path,
            timeout_seconds=timeout,
            max_turns=max_turns,
            effort="max",
        )

    def get_latest_review(self) -> dict | None:
        """Read the latest strategy review for today."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = self.runner.get_output_dir(date_str)

        for review_type in ["weekly", "daily"]:
            path = os.path.join(output_dir, f"strategy_review_{review_type}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        return json.load(f)
                except Exception:
                    pass

        return None

    def _load_prompt(self) -> str:
        path = os.path.join(self._prompts_dir, "post_market_strategy.md")
        with open(path, "r") as f:
            return f.read()
