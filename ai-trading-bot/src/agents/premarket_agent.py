"""
Pre-Market Research Agent.
Runs at 7:30 AM to gather overnight news, global cues, and macro context.
Output feeds into the Market Pulse (Sonnet) prompt.
"""

import json
import logging
import os
from datetime import datetime

from src.agents.subprocess_runner import AgentSubprocessRunner, AgentRun

logger = logging.getLogger(__name__)


class PreMarketResearchAgent:
    """Gathers pre-market intelligence via web search."""

    def __init__(self, runner: AgentSubprocessRunner, config: dict):
        self.runner = runner
        self.config = config
        self._prompts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "prompts"
        )

    def run(self) -> AgentRun:
        """Run pre-market research. Returns AgentRun with results."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = self.runner.get_output_dir(date_str)
        output_path = os.path.join(output_dir, "premarket_brief.json")

        # Load and format prompt
        prompt_template = self._load_prompt()
        prompt = prompt_template.replace("{output_path}", output_path)

        return self.runner.run_agent(
            agent_name="premarket_research",
            prompt=prompt,
            model="claude-opus-4-7[1M]",
            output_file=output_path,
            timeout_seconds=600,
            max_turns=25,
            effort="max",
        )

    def get_latest_brief(self) -> dict | None:
        """Read the latest pre-market brief if available."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = self.runner.get_output_dir(date_str)
        path = os.path.join(output_dir, "premarket_brief.json")

        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read premarket brief: {e}")
        return None

    def _load_prompt(self) -> str:
        path = os.path.join(self._prompts_dir, "premarket_research.md")
        with open(path, "r") as f:
            return f.read()
