"""
Simulated market day — exercise every scheduled job / API / agent once, in order.

This is what EC2 goes through during a live trading day, compressed to a single
run and pointed at a scratch DB so production state is untouched. On my box it
costs real Anthropic + Dhan calls; there is no mocking.

Stages, in the order they fire on a real day:
    1. Dhan TOTP token refresh           (06:30 on real day)
    2. Orchestrator boot                 (sets up data client, warehouse, all)
    3. Pre-market research agent         (07:30)
    4. Full market-pulse cycle           (every 30 min 09:00-14:59)
       — Sonnet pulse → watchlist research agent → Opus decision
         → guardrails → paper execute → portfolio snapshot
    5. SL health check                   (every 5 min)
    6. Paper SL/target reconciliation    (every 5 min)
    7. Risk-monitor agent                (every 30 min)
    8. MIS exit stages 1-4               (15:00 / 05 / 10 / 12)
    9. EOD review                        (15:40)
   10. Daily backup                      (16:00)
   11. Strategy review agent — daily    (16:00)

Each stage is independently try/except'd — one failure never blocks the rest.

Before exit, restore any agent edits to tracked files (system_prompt.py,
config.yaml, src/agents/risk_config.yaml) so the local repo state matches
what was before the run.

Run:
    conda run -n trading-bot python scripts/e2e_market_day.py

Exits 0 only if every stage is PASS.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

# scripts/ → repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv("config/.env")

import yaml

# INFO-level: we want to see where warehouse/news/agents are actually spending time
# during the run. Downgraded a couple of chatty libs.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
for noisy in ("urllib3", "httpx", "httpcore", "anthropic", "feedparser"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────────────────────
# Result tracking
# ─────────────────────────────────────────────────────────────────────────────

RESULTS: list[tuple[str, str, str]] = []  # (stage, status, detail)


def record(stage: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    RESULTS.append((stage, status, detail))
    print(f"\n[{status}] {stage}" + (f" - {detail}" if detail else ""))


def section(title: str):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# ─────────────────────────────────────────────────────────────────────────────
# Scratch environment setup (don't touch production state)
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRATCH = REPO_ROOT / ".e2e_scratch"
SCRATCH.mkdir(exist_ok=True)

# Files the strategy/risk agents might edit — snapshot for restore
AGENT_EDITABLE = [
    REPO_ROOT / "src" / "ai" / "system_prompt.py",
    REPO_ROOT / "config" / "config.yaml",
    REPO_ROOT / "src" / "agents" / "risk_config.yaml",
]
FILE_SNAPSHOTS: dict[Path, bytes] = {
    p: p.read_bytes() for p in AGENT_EDITABLE if p.exists()
}


def restore_agent_edits():
    """Revert any edits agents made to tracked files during this run."""
    reverted = []
    for p, original in FILE_SNAPSHOTS.items():
        if p.exists() and p.read_bytes() != original:
            p.write_bytes(original)
            reverted.append(str(p.relative_to(REPO_ROOT)))
    return reverted


def cleanup_scratch():
    if SCRATCH.exists():
        try:
            shutil.rmtree(SCRATCH)
        except Exception as e:
            print(f"(scratch cleanup warning: {e})")


def write_scratch_config() -> Path:
    """Copy config.yaml and redirect DB / logs / backups to scratch paths."""
    with open(REPO_ROOT / "config" / "config.yaml") as f:
        cfg = yaml.safe_load(f)

    scratch_db = SCRATCH / "scratch.db"
    scratch_logs = SCRATCH / "logs"
    scratch_backups = SCRATCH / "backups"
    scratch_logs.mkdir(exist_ok=True)
    scratch_backups.mkdir(exist_ok=True)

    cfg.setdefault("database", {})["path"] = str(scratch_db)
    cfg.setdefault("logging", {})["log_dir"] = str(scratch_logs)
    cfg.setdefault("backup", {})["local_dir"] = str(scratch_backups) + "/"

    out = SCRATCH / "config.e2e.yaml"
    with open(out, "w") as f:
        yaml.safe_dump(cfg, f)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# STAGES
# ─────────────────────────────────────────────────────────────────────────────

def stage_dhan_token_refresh():
    section("STAGE 1/11 — Dhan TOTP token refresh")
    from src.broker.dhan_auth import DhanAuth

    # Write to the DEFAULT token cache path so stage-2 orchestrator boot picks
    # it up from cache. Dhan rate-limits token generation to once every 2 min;
    # if we refresh here and then boot refreshes again, we trip the cooldown.
    default_token_file = REPO_ROOT / "data" / "dhan_token.json"
    default_token_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        auth = DhanAuth(
            client_id=os.environ["DHAN_CLIENT_ID"],
            pin=os.environ["DHAN_PIN"],
            totp_secret=os.environ["DHAN_TOTP_SECRET"],
            token_file=default_token_file,
        )
        # get_token(): returns cache if fresh, else refresh — avoids needless calls.
        token = auth.get_token()
        assert len(token) > 100, f"Token suspiciously short: len={len(token)}"
        expiry = (auth._cached or {}).get("expiryTime", "?")
        record("Dhan TOTP refresh", True, f"token len={len(token)}, expires {expiry}")
        return token
    except Exception as e:
        record("Dhan TOTP refresh", False, f"{type(e).__name__}: {e}")
        raise


def stage_boot_orchestrator(config_path: Path):
    section("STAGE 2/11 — Orchestrator boot")
    from src.orchestrator import Orchestrator

    orch = None
    try:
        t0 = time.time()
        orch = Orchestrator(config_path=str(config_path))
        orch.boot()
        dt = time.time() - t0
        assert orch._is_running
        assert orch.data_client is not None
        assert orch.warehouse is not None
        assert orch.warehouse.is_booted
        universe = orch.warehouse.get_loaded_symbols()
        record("Orchestrator boot", True, f"{dt:.1f}s, universe={len(universe)}")
        return orch
    except Exception as e:
        # Close any held DB handle so scratch cleanup doesn't hit WinError 32
        if orch is not None and getattr(orch, "db", None) is not None:
            try:
                orch.db.close()
            except Exception:
                pass
        record("Orchestrator boot", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        raise


def stage_premarket_agent(orch):
    section("STAGE 3/11 — Pre-market research agent")
    try:
        t0 = time.time()
        run = orch.premarket_agent.run()
        dt = time.time() - t0
        ok = run.status == "SUCCESS"
        detail = f"{dt:.1f}s, status={run.status}"
        if run.output_data:
            keys = list(run.output_data.keys())[:5]
            detail += f", output keys: {keys}"
        if run.error_message:
            detail += f", err={run.error_message[:120]}"
        record("Pre-market agent", ok, detail)
    except Exception as e:
        record("Pre-market agent", False, f"{type(e).__name__}: {e}")


def stage_market_pulse_cycle(orch):
    section("STAGE 4/11 — Market pulse cycle (Sonnet + Watchlist Agent + Opus)")
    try:
        t0 = time.time()
        # This single call walks: refresh data → market pulse (Sonnet) → parallel
        # deep-dive + watchlist research agent → trading decision (Opus) →
        # guardrails + paper execute → mark-to-market snapshot.
        orch.run_market_pulse_cycle()
        dt = time.time() - t0

        # Verify the cycle produced a snapshot
        snap = orch.db.fetchone(
            "SELECT timestamp, total_value, cash_available FROM portfolio_snapshots "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        has_snap = snap is not None
        trades = orch.db.fetchone(
            "SELECT COUNT(*) as c FROM trades WHERE mode = 'PAPER'"
        )
        trade_count = trades["c"] if trades else 0

        detail = f"{dt:.1f}s, snapshot_written={has_snap}, trades_logged={trade_count}"
        if snap:
            detail += f", portfolio={snap['total_value']:.0f}"
        record("Market pulse cycle", has_snap, detail)
    except Exception as e:
        record("Market pulse cycle", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()


def stage_sl_health_check(orch):
    section("STAGE 5/11 — SL health check + paper reconcile")
    sl_ok = rec_ok = False
    sl_detail = rec_detail = ""

    try:
        t0 = time.time()
        if orch.sl_health:
            orch.sl_health.check()
        sl_detail = f"{time.time()-t0:.1f}s"
        sl_ok = True
    except Exception as e:
        sl_detail = f"{type(e).__name__}: {e}"

    try:
        t0 = time.time()
        if orch.order_reconciler:
            orch.order_reconciler.reconcile_paper_sl_targets()
        rec_detail = f"{time.time()-t0:.1f}s"
        rec_ok = True
    except Exception as e:
        rec_detail = f"{type(e).__name__}: {e}"

    record("SL health check", sl_ok, sl_detail)
    record("Paper reconcile", rec_ok, rec_detail)


def stage_risk_monitor_agent(orch):
    section("STAGE 6/11 — Risk monitor agent")
    try:
        t0 = time.time()
        run = orch.risk_monitor.run()
        dt = time.time() - t0
        ok = run.status == "SUCCESS"
        detail = f"{dt:.1f}s, status={run.status}"
        if run.error_message:
            detail += f", err={run.error_message[:120]}"
        record("Risk monitor agent", ok, detail)
    except Exception as e:
        record("Risk monitor agent", False, f"{type(e).__name__}: {e}")


def stage_mis_exits(orch):
    section("STAGE 7/11 — MIS exit stages 1-4")
    if not orch.mis_exit:
        record("MIS exit stages", False, "orchestrator.mis_exit is None")
        return
    for i, fn in enumerate([
        orch.mis_exit.stage_1_graceful_exit,
        orch.mis_exit.stage_2_retry_unfilled,
        orch.mis_exit.stage_3_force_market_close,
        orch.mis_exit.stage_4_emergency_check,
    ], start=1):
        try:
            t0 = time.time()
            fn()
            record(f"MIS stage {i}", True, f"{time.time()-t0:.1f}s")
        except Exception as e:
            record(f"MIS stage {i}", False, f"{type(e).__name__}: {e}")


def stage_eod_and_backup(orch):
    section("STAGE 8/11 — EOD review + daily backup")
    try:
        t0 = time.time()
        orch.run_eod_review()
        record("EOD review", True, f"{time.time()-t0:.1f}s")
    except Exception as e:
        record("EOD review", False, f"{type(e).__name__}: {e}")

    try:
        t0 = time.time()
        orch.run_daily_backup()
        record("Daily backup", True, f"{time.time()-t0:.1f}s")
    except Exception as e:
        record("Daily backup", False, f"{type(e).__name__}: {e}")


def stage_strategy_agent(orch):
    section("STAGE 9/11 — Strategy review agent (daily)")
    try:
        t0 = time.time()
        run = orch.strategy_agent.run_daily()
        dt = time.time() - t0
        ok = run.status == "SUCCESS"
        detail = f"{dt:.1f}s, status={run.status}"
        if run.error_message:
            detail += f", err={run.error_message[:120]}"
        record("Strategy review agent", ok, detail)
    except Exception as e:
        record("Strategy review agent", False, f"{type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print(f"E2E MARKET DAY SIMULATION  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 72)
    print(f"Scratch root: {SCRATCH}")
    print(f"Snapshotted files for post-run restore: {len(FILE_SNAPSHOTS)}")

    cfg_path = write_scratch_config()

    orch = None
    try:
        # Stage 1 runs independently (no orchestrator needed)
        try:
            stage_dhan_token_refresh()
        except Exception:
            pass  # recorded already

        # Stages 2-9 require a live orchestrator
        try:
            orch = stage_boot_orchestrator(cfg_path)
        except Exception:
            print("Boot failed — skipping downstream stages.")
            orch = None

        if orch is not None:
            stage_premarket_agent(orch)
            stage_market_pulse_cycle(orch)
            stage_sl_health_check(orch)
            stage_risk_monitor_agent(orch)
            stage_mis_exits(orch)
            stage_eod_and_backup(orch)
            stage_strategy_agent(orch)

            # Cleanly stop scheduler / notifier
            try:
                orch.stop()
            except Exception:
                pass

    finally:
        # Always restore file edits and clean scratch
        reverted = restore_agent_edits()
        if reverted:
            print(f"\nReverted agent edits to: {', '.join(reverted)}")
        cleanup_scratch()

    # ─── REPORT ───
    print("\n" + "=" * 72)
    print("FINAL REPORT")
    print("=" * 72)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    for stage, status, detail in RESULTS:
        print(f"  [{status}] {stage}" + (f"  — {detail}" if detail else ""))
    print(f"\n  TOTAL: {passed} passed, {failed} failed")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
