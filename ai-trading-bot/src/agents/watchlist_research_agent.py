"""
Watchlist Deep Research Agent.
Triggered after Sonnet returns a watchlist. Runs in parallel with deep-dive assembly.
Output feeds into the Trading Decision (Opus) prompt.
"""

import json
import logging
import os
from datetime import datetime

from src.agents.subprocess_runner import AgentSubprocessRunner, AgentRun

logger = logging.getLogger(__name__)


class WatchlistResearchAgent:
    """Per-stock background research for watchlist stocks."""

    def __init__(self, runner: AgentSubprocessRunner, config: dict):
        self.runner = runner
        self.config = config
        self._prompts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "prompts"
        )

    def run(self, symbols: list[str], batch_id: int = 0) -> AgentRun:
        """Research a batch of stocks."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = self.runner.get_output_dir(date_str)
        output_path = os.path.join(output_dir, f"watchlist_research_b{batch_id}.json")

        prompt_template = self._load_prompt()
        prompt = prompt_template.replace(
            "{symbols}", ", ".join(symbols)
        ).replace("{output_path}", output_path)

        return self.runner.run_agent(
            agent_name=f"watchlist_research_b{batch_id}",
            prompt=prompt,
            model="claude-opus-4-7[1M]",
            output_file=output_path,
            timeout_seconds=420,
            max_turns=20,
            effort="max",
        )

    def run_parallel(self, symbols: list[str], batch_size: int = 5) -> list[AgentRun]:
        """Split symbols into batches and run research in parallel."""
        if not symbols:
            return []

        # Split into batches
        batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]

        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = self.runner.get_output_dir(date_str)
        prompt_template = self._load_prompt()

        agent_specs = []
        for idx, batch in enumerate(batches):
            output_path = os.path.join(output_dir, f"watchlist_research_b{idx}.json")
            prompt = prompt_template.replace(
                "{symbols}", ", ".join(batch)
            ).replace("{output_path}", output_path)

            agent_specs.append({
                "agent_name": f"watchlist_research_b{idx}",
                "prompt": prompt,
                "model": "claude-opus-4-7[1M]",
                "output_file": output_path,
                "timeout_seconds": 420,
                "max_turns": 20,
                "effort": "max",
            })

        return self.runner.run_agents_parallel(agent_specs, max_concurrent=3)

    def get_all_research(self) -> list[dict]:
        """Read all watchlist research files for today."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = self.runner.get_output_dir(date_str)
        results = []

        if not os.path.exists(output_dir):
            return results

        for fname in sorted(os.listdir(output_dir)):
            if fname.startswith("watchlist_research_") and fname.endswith(".json"):
                try:
                    with open(os.path.join(output_dir, fname), "r") as f:
                        data = json.load(f)
                        if "stocks" in data:
                            results.extend(data["stocks"])
                except Exception as e:
                    logger.warning(f"Failed to read {fname}: {e}")

        return results

    def _load_prompt(self) -> str:
        path = os.path.join(self._prompts_dir, "watchlist_research.md")
        with open(path, "r") as f:
            return f.read()
