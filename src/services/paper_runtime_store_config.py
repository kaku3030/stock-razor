"""Fail-closed configuration contract for paper runtime stores.

This module only parses and validates paths. It never opens SQLite, creates
directories, or performs runtime/provider/broker I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from .execution_engine import ExecutionBlocked


@dataclass(frozen=True)
class PaperRuntimeStoreConfig:
    execution_path: Path
    shadow_path: Path

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "PaperRuntimeStoreConfig":
        source = os.environ if env is None else env
        execution_raw = source.get("PAPER_EXECUTION_STORE_PATH", "").strip()
        shadow_raw = source.get("PAPER_SHADOW_STORE_PATH", "").strip()
        if not execution_raw or not shadow_raw:
            raise ExecutionBlocked(
                "paper execution and shadow store paths are required"
            )
        if execution_raw == ":memory:" or shadow_raw == ":memory:":
            raise ExecutionBlocked("paper runtime stores must be durable")
        execution_path = Path(execution_raw).expanduser()
        shadow_path = Path(shadow_raw).expanduser()
        if execution_path == shadow_path:
            raise ExecutionBlocked(
                "paper execution and shadow store paths must be separate"
            )
        return cls(execution_path, shadow_path)

    def status(self) -> str:
        return "CONFIGURED_DISTINCT_DURABLE_PATHS"
