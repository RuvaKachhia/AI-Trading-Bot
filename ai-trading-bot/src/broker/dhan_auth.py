"""
Dhan authentication — programmatic access-token refresh via TOTP.

Dhan access tokens are capped at 24-hour validity (SEBI rule). Running an
autonomous bot past that requires regenerating the token daily.

Flow:
  1. One-time setup on web.dhan.co: Profile -> DhanHQ Trading APIs ->
     Setup TOTP. Capture the base32 secret shown at enrollment.
  2. Bot stores DHAN_CLIENT_ID, DHAN_PIN, DHAN_TOTP_SECRET in config/.env.
  3. DhanAuth generates a fresh token by hitting
     POST https://auth.dhan.co/app/generateAccessToken with a current
     TOTP code computed from the base32 secret.
  4. Token is cached to data/dhan_token.json so a bot restart within 24h
     doesn't need another regeneration.
  5. Orchestrator calls refresh_if_needed() on boot and schedules a daily
     refresh at 07:00 IST (before 08:30 boot + 09:15 market open).

Endpoint reference: https://dhanhq.co/docs/v2/authentication/
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"
_DEFAULT_TOKEN_FILE = Path("data/dhan_token.json")
# Regenerate proactively if <N hours left (don't wait to expire mid-day).
_PROACTIVE_REFRESH_HOURS = 4
_IST = timezone(timedelta(hours=5, minutes=30))


class DhanAuth:
    """
    Manages Dhan access-token lifecycle.

    Call get_token() to read the current valid token (refreshing if expired or
    close to expiry). Call force_refresh() from the scheduled daily job.
    """

    def __init__(
        self,
        client_id: str,
        pin: str,
        totp_secret: str,
        token_file: Path = _DEFAULT_TOKEN_FILE,
        fallback_token: Optional[str] = None,
    ):
        self.client_id = client_id
        self.pin = pin
        self.totp_secret = totp_secret
        self.token_file = Path(token_file)
        self.fallback_token = fallback_token  # Optional manually-set token
        self._cached: Optional[dict] = None
        self.token_file.parent.mkdir(parents=True, exist_ok=True)

    # ─── PUBLIC ───

    def get_token(self) -> str:
        """
        Return a valid Dhan access token. Refresh if close to expiry.
        Falls back to DHAN_ACCESS_TOKEN env if refresh is not possible
        (missing PIN/TOTP secret) — useful for local dev / one-off runs.
        """
        self._load_cache_if_missing()
        if self._cached and self._is_fresh(self._cached):
            return self._cached["accessToken"]

        # Try to refresh
        if self._can_refresh():
            return self.force_refresh()

        # No TOTP configured — use the manually-set env token as-is
        if self.fallback_token:
            logger.warning(
                "DhanAuth: using fallback access token from env "
                "(TOTP not configured — token will expire in 24h and "
                "require manual refresh)."
            )
            return self.fallback_token

        raise RuntimeError(
            "DhanAuth: no valid token and cannot refresh. "
            "Set DHAN_PIN + DHAN_TOTP_SECRET in config/.env, or provide "
            "DHAN_ACCESS_TOKEN manually."
        )

    def force_refresh(self) -> str:
        """
        Unconditionally call Dhan's token endpoint and cache the new token.
        Use this from a scheduled daily job.

        Retries once on `Invalid TOTP` to absorb the 30-second TOTP window
        boundary race: if the bot generates a code right at the end of one
        window but the request lands in Dhan's clock during the next, the
        codes won't match. Observed in production on 2026-05-07 06:30:00,
        which collapsed the entire trading day. Retry advances past the
        boundary and re-issues with a fresh code.
        """
        if not self._can_refresh():
            raise RuntimeError(
                "Cannot refresh: DHAN_PIN and DHAN_TOTP_SECRET must both be set."
            )

        try:
            import pyotp
        except ImportError:
            raise RuntimeError(
                "pyotp not installed. Run: pip install pyotp"
            )

        import time

        last_payload = None
        for attempt in (1, 2):
            if attempt == 2:
                # Sleep until ~3s into the next 30-sec TOTP window so the
                # regenerated code is unambiguously aligned with Dhan's
                # validation window.
                now = time.time()
                next_window_start = ((int(now) // 30) + 1) * 30
                sleep_s = (next_window_start + 3) - now
                logger.warning(
                    f"DhanAuth: retrying TOTP refresh after {sleep_s:.1f}s "
                    f"to clear window boundary..."
                )
                time.sleep(sleep_s)

            totp = pyotp.TOTP(self.totp_secret).now()
            logger.info(
                f"DhanAuth: requesting fresh access token via TOTP "
                f"(attempt {attempt}/2)..."
            )

            try:
                r = requests.post(
                    _AUTH_URL,
                    params={
                        "dhanClientId": self.client_id,
                        "pin": self.pin,
                        "totp": totp,
                    },
                    timeout=20,
                )
            except Exception as e:
                raise RuntimeError(
                    f"DhanAuth: HTTP error calling token endpoint: {e}"
                )

            if r.status_code != 200:
                raise RuntimeError(
                    f"DhanAuth: token endpoint returned {r.status_code}: "
                    f"{r.text[:300]}"
                )

            try:
                payload = r.json()
            except Exception:
                raise RuntimeError(
                    f"DhanAuth: non-JSON response from token endpoint: "
                    f"{r.text[:300]}"
                )

            if "accessToken" in payload:
                self._cached = payload
                self._save_cache(payload)
                expiry = payload.get("expiryTime", "unknown")
                logger.info(
                    f"DhanAuth: new token obtained, expires {expiry}"
                )
                return payload["accessToken"]

            # Not in success path. Decide whether to retry.
            last_payload = payload
            msg = str(payload.get("message", "")).upper()
            if attempt == 1 and "TOTP" in msg:
                # Window-boundary race — retry once.
                continue

            # Either a non-retryable error, or we're out of attempts.
            break

        raise RuntimeError(
            f"DhanAuth: unexpected response (no accessToken) "
            f"after {attempt} attempt(s): {last_payload}"
        )

    # ─── INTERNALS ───

    def _can_refresh(self) -> bool:
        return bool(self.client_id and self.pin and self.totp_secret)

    def _is_fresh(self, payload: dict) -> bool:
        """True if cached token still has > _PROACTIVE_REFRESH_HOURS remaining."""
        exp_str = payload.get("expiryTime")
        if not exp_str:
            return False
        try:
            exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            # Dhan returns IST-flavored timestamps without tz offset — assume IST.
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=_IST)
            now_ist = datetime.now(tz=_IST)
            hours_left = (exp_dt - now_ist).total_seconds() / 3600
            return hours_left > _PROACTIVE_REFRESH_HOURS
        except Exception as e:
            logger.warning(f"DhanAuth: could not parse expiryTime='{exp_str}': {e}")
            return False

    def _load_cache_if_missing(self) -> None:
        if self._cached is not None:
            return
        if not self.token_file.exists():
            return
        try:
            self._cached = json.loads(self.token_file.read_text())
        except Exception as e:
            logger.warning(f"DhanAuth: could not read token cache: {e}")
            self._cached = None

    def _save_cache(self, payload: dict) -> None:
        """Atomic write: tmp → rename."""
        try:
            tmp = self.token_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.token_file)
        except Exception as e:
            logger.warning(f"DhanAuth: could not write token cache: {e}")
