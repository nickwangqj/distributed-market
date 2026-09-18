"""Environment-driven configuration, shared by all four services.

Variable names mirror the ConfigMap keys in .claude/docs/08-deployment.md §5 exactly, so the
compose `.env` and the Kubernetes ConfigMap stay interchangeable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 8080


def _duration_seconds(raw: str) -> float:
    """Parse a duration like `60s`, `1500ms`, or a bare number of seconds."""
    text = raw.strip().lower()
    if text.endswith("ms"):
        return float(text[:-2]) / 1000
    if text.endswith("s"):
        return float(text[:-1])
    return float(text)


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved configuration for one service process."""

    service: str
    data_dir: Path
    log_level: str
    port: int
    engine_url: str
    ledger_url: str
    marketdata_url: str
    fsync_mode: str
    snapshot_every: int
    band_refresh_seconds: float
    reservation_ttl_seconds: float

    @property
    def config_dir(self) -> Path:
        return self.data_dir / "config"


def load_settings(service: str) -> Settings:
    """Build `Settings` for `service` from the environment, applying documented defaults."""
    return Settings(
        service=service,
        data_dir=Path(os.environ.get("DM_DATA_DIR", "./data")),
        log_level=os.environ.get("DM_LOG_LEVEL", "INFO").upper(),
        port=int(os.environ.get("DM_PORT", DEFAULT_PORT)),
        engine_url=os.environ.get("DM_ENGINE_URL", "http://engine:8080"),
        ledger_url=os.environ.get("DM_LEDGER_URL", "http://ledger:8080"),
        marketdata_url=os.environ.get("DM_MARKETDATA_URL", "http://marketdata:8080"),
        fsync_mode=os.environ.get("DM_FSYNC_MODE", "always"),
        snapshot_every=int(os.environ.get("DM_SNAPSHOT_EVERY", "1000")),
        band_refresh_seconds=_duration_seconds(os.environ.get("DM_BAND_REFRESH", "1s")),
        reservation_ttl_seconds=_duration_seconds(os.environ.get("DM_RESERVATION_TTL", "60s")),
    )
