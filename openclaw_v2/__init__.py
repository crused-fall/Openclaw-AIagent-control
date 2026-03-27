"""OpenClaw v2 hybrid orchestration package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppConfig
    from .orchestrator import HybridOrchestrator

__all__ = ["AppConfig", "HybridOrchestrator", "load_app_config"]


def __getattr__(name: str):
    if name in {"AppConfig", "load_app_config"}:
        from .config import AppConfig, load_app_config

        exports = {
            "AppConfig": AppConfig,
            "load_app_config": load_app_config,
        }
        return exports[name]
    if name == "HybridOrchestrator":
        from .orchestrator import HybridOrchestrator

        return HybridOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
