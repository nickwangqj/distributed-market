"""Shared service plumbing: settings, structured logging, and the health app factory.

Deliberately separate from `market_core`: that package is pure domain logic with no framework
imports (.claude/docs/01-domain-model.md K4), while everything here knows about FastAPI, the
environment, and the process it runs in.
"""

from service_common.app import Readiness, bootstrap, create_app
from service_common.logging import configure_logging
from service_common.settings import Settings, load_settings

__all__ = [
    "Readiness",
    "Settings",
    "bootstrap",
    "configure_logging",
    "create_app",
    "load_settings",
]
