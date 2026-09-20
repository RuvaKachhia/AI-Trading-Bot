"""
Agent Subprocess Runner.
Spawns Claude Code CLI subprocesses for agentic tasks.
Handles lifecycle management, timeout, output collection, and logging.
"""

import json
import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentRun:
    """Record of a single agent execution."""
    agent_name: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0
    output_file: Optional[str] = None
    output_data: Optional[dict] = None
    status: str = "RUNNING"
    error_message: Optional[str] = None


class AgentSubprocessRunner:
    """
    Spawns Claude Code CLI subprocesses for agentic tasks.
    Each agent gets a prompt, optional context files, and a timeout.
    Output is collected via stdout and optional output files.
    """

    def __init__(self, config: dict, db=None, notifier=None):
        self.config = config
        self.db = db
        self.notifier = notifier
        self._project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self._outputs_dir = os.path.join(self._project_root, "src", "agents", "outputs")

    def get_output_dir(self, date_str: str = None) -> str:
        """Get the output directory for a given date."""
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        path = os.path.join(self._outputs_dir, date_str)
        os.makedirs(path, exist_ok=True)
        return path

    def run_agent(
        self,
        agent_name: str,
        prompt: str,
        model: str = "claude-opus-4-7[1M]",
        output_file: Optional[str] = None,
        timeout_seconds: int = 300,
        max_turns: int = 20,
        effort: str = "max",
    ) -> AgentRun:
        """
        Run a single Claude Code agent subprocess.

        Args:
            agent_name: Name for logging/tracking
            prompt: The full prompt to send to Claude
            model: Claude model to use (opus, sonnet, haiku)
            output_file: Path where the agent should write structured output
            timeout_seconds: Max execution time before killing
            max_turns: Max tool-use turns for the agent
            effort: Effort level (low, medium, high, max)

        Returns:
            AgentRun with results
        """
        run = AgentRun(
            agent_name=agent_name,
            started_at=datetime.now(),
            output_file=output_file,
        )

        cmd = self._build_command(prompt, model, max_turns, effort)
        logger.info(f"Agent '{agent_name}' starting (model={model}, timeout={timeout_seconds}s)")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self._project_root,
                env={**os.environ, "CLAUDE_CODE_ENTRYPOINT": "agent"},
            )

            # Set up timeout
            timer = threading.Timer(timeout_seconds, self._kill_process, [process, agent_name])
            timer.start()

            try:
                stdout, stderr = process.communicate()
                run.stdout = stdout or ""
                run.stderr = stderr or ""
                run.exit_code = process.returncode
            finally:
                timer.cancel()

            run.finished_at = datetime.now()
            run.duration_seconds = (run.finished_at - run.started_at).total_seconds()

            if process.returncode == 0:
                run.status = "SUCCESS"
                # Try to read structured output file
                if output_file and os.path.exists(output_file):
                    try:
                        with open(output_file, "r") as f:
                            run.output_data = json.load(f)
                    except Exception as e:
                        logger.warning(f"Failed to parse output file for {agent_name}: {e}")
            elif process.returncode == -9 or process.returncode == 137:
                run.status = "TIMEOUT"
                run.error_message = f"Agent timed out after {timeout_seconds}s"
            else:
                run.status = "ERROR"
                run.error_message = run.stderr[:500] if run.stderr else f"Exit code: {run.exit_code}"

        except FileNotFoundError:
            run.status = "ERROR"
            run.error_message = "claude CLI not found. Ensure Claude Code is installed."
            run.finished_at = datetime.now()
            run.duration_seconds = (run.finished_at - run.started_at).total_seconds()
        except Exception as e:
            run.status = "ERROR"
            run.error_message = str(e)[:500]
            run.finished_at = datetime.now()
            run.duration_seconds = (run.finished_at - run.started_at).total_seconds()

        # Log to DB
        self._log_agent_run(run)

        logger.info(
            f"Agent '{agent_name}' finished: {run.status} "
            f"({run.duration_seconds:.1f}s)"
        )

        return run

    def run_agents_parallel(
        self,
        agent_specs: list[dict],
        max_concurrent: int = 3,
    ) -> list[AgentRun]:
        """
        Run multiple agents in parallel.

        Args:
            agent_specs: List of dicts with keys matching run_agent params
            max_concurrent: Max parallel subprocesses

        Returns:
            List of AgentRun results
        """
        results = []

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {}
            for spec in agent_specs:
                future = executor.submit(self.run_agent, **spec)
                futures[future] = spec.get("agent_name", "unknown")

            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    run = future.result()
                    results.append(run)
                except Exception as e:
                    logger.error(f"Agent '{agent_name}' raised exception: {e}")
                    results.append(AgentRun(
                        agent_name=agent_name,
                        started_at=datetime.now(),
                        finished_at=datetime.now(),
                        status="ERROR",
                        error_message=str(e),
                    ))

        return results

    def _build_command(self, prompt: str, model: str, max_turns: int, effort: str = "max") -> list[str]:
        """Build the claude CLI command."""
        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--model", model,
            "--effort", effort,
            "--max-turns", str(max_turns),
            "-p", prompt,
        ]
        return cmd

    def _kill_process(self, process: subprocess.Popen, agent_name: str):
        """Kill a timed-out process."""
        try:
            process.kill()
            logger.warning(f"Agent '{agent_name}' killed due to timeout")
        except Exception:
            pass

    def _log_agent_run(self, run: AgentRun):
        """Log agent run to database."""
        if not self.db:
            return

        try:
            self.db.execute(
                """INSERT INTO agent_runs
                   (agent_name, started_at, finished_at, exit_code,
                    duration_seconds, output_summary, status, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.agent_name,
                    run.started_at.strftime("%Y-%m-%d %H:%M:%S"),
                    run.finished_at.strftime("%Y-%m-%d %H:%M:%S") if run.finished_at else None,
                    run.exit_code,
                    run.duration_seconds,
                    run.stdout[:500] if run.stdout else None,
                    run.status,
                    run.error_message,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to log agent run: {e}")
