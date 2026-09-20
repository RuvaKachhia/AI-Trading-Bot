"""
Risk Monitor Agent.
Runs every 30 min during market hours to analyze portfolio-level risk.
Can tighten guardrail parameters via risk_config.yaml.
"""

import json
import logging
import os
from datetime import datetime

from src.agents.subprocess_runner import AgentSubprocessRunner, AgentRun

logger = logging.getLogger(__name__)


class RiskMonitorAgent:
    """Analyzes portfolio risk and can tighten guardrails."""

    def __init__(self, runner: AgentSubprocessRunner, config: dict):
        self.runner = runner
        self.config = config
        self._project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self._prompts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "prompts"
        )

    def run(self) -> AgentRun:
        """Run risk assessment."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M")
        output_dir = self.runner.get_output_dir(date_str)
        output_path = os.path.join(output_dir, f"risk_assessment_{time_str}.json")

        db_path = os.path.join(
            self._project_root,
            self.config.get("database", {}).get("path", "data/trading_bot.db"),
        )
        risk_config_path = os.path.join(
            self._project_root, "src", "agents", "risk_config.yaml"
        )

        prompt_template = self._load_prompt()
        prompt = (
            prompt_template
            .replace("{db_path}", db_path)
            .replace("{risk_config_path}", risk_config_path)
            .replace("{output_path}", output_path)
        )

        return self.runner.run_agent(
            agent_name="risk_monitor",
            prompt=prompt,
            model="claude-opus-4-7[1M]",
            output_file=output_path,
            timeout_seconds=900,
            max_turns=50,
            effort="max",
        )

    def get_latest_assessment(self) -> dict | None:
        """Read the most recent risk assessment for today."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = self.runner.get_output_dir(date_str)

        if not os.path.exists(output_dir):
            return None

        # Find the latest risk assessment file
        risk_files = sorted([
            f for f in os.listdir(output_dir)
            if f.startswith("risk_assessment_") and f.endswith(".json")
        ], reverse=True)

        if risk_files:
            try:
                with open(os.path.join(output_dir, risk_files[0]), "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read risk assessment: {e}")

        return None

    def _load_prompt(self) -> str:
        path = os.path.join(self._prompts_dir, "risk_monitor.md")
        with open(path, "r") as f:
            return f.read()
