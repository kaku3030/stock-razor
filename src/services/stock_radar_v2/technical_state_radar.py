"""Publish persisted multi-timeframe state as research-only radar reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.repositories.stock_radar_technical_state_repo import (
    StockRadarTechnicalStateRepository,
    technical_state_snapshot_to_dict,
)

from .technical_state import StockRadarTechnicalState


class StockRadarTechnicalStateRadar:
    """Persist one run and emit deterministic JSON/Markdown artifacts."""

    def __init__(self, repository: StockRadarTechnicalStateRepository | None = None) -> None:
        self.repository = repository or StockRadarTechnicalStateRepository()

    def publish(
        self,
        *,
        market: str,
        run_id: str,
        states: Sequence[StockRadarTechnicalState],
        output_dir: str | Path,
        runtime_metadata: Mapping[str, Any] | None = None,
        read_only_facts: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        market = market.strip().lower()
        run_id = run_id.strip()
        if not market:
            raise ValueError("market is required")
        if not run_id:
            raise ValueError("run_id is required")

        inserted = self.repository.sync_run(market, run_id, states)
        rows = [
            technical_state_snapshot_to_dict(record)
            for record in self.repository.list_run(market, run_id)
        ]
        payload = {
            "market": market,
            "run_id": run_id,
            "research_only": True,
            "can_confirm_signal": False,
            "inserted": inserted,
            "material_count": sum(bool(row.get("material")) for row in rows),
            "rows": rows,
        }
        if runtime_metadata is not None:
            payload["runtime"] = dict(runtime_metadata)
        if read_only_facts is not None:
            payload["read_only_export"] = {
                "schema": "stock-razor-read-only-market-facts-v1",
                "research_only": True,
                "trading_capability": False,
                "facts": [dict(item) for item in read_only_facts],
            }
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        stem = output / f"{market}_stock_radar_technical_state_radar"
        json_path = stem.with_suffix(".json")
        markdown_path = stem.with_suffix(".md")
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        markdown_path.write_text(
            technical_state_radar_markdown(
                rows,
                market=market,
                run_id=run_id,
                runtime_metadata=runtime_metadata,
            ),
            encoding="utf-8",
        )
        readonly_path = output / f"{market}_stock_radar_read_only_market_facts.json"
        if read_only_facts is not None:
            readonly_path.write_text(
                json.dumps(payload["read_only_export"], ensure_ascii=False, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
        return {
            **payload,
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "read_only_export_path": str(readonly_path) if read_only_facts is not None else None,
        }


def technical_state_radar_markdown(
    rows: list[dict[str, Any]],
    *,
    market: str,
    run_id: str,
    runtime_metadata: Mapping[str, Any] | None = None,
) -> str:
    lines = [
        "# Stock Radar V2 多周期技术状态变化",
        "",
        "> 仅记录多周期状态与数据质量变化，不构成交易建议或交易指令。",
        "",
        f"- 市场：{market}",
        f"- Run ID：{run_id}",
    ]
    if runtime_metadata is not None:
        lines.extend(
            [
                f"- 请求标的：{runtime_metadata.get('requested_count', 0)}",
                f"- 成功评估：{runtime_metadata.get('evaluated_count', 0)}",
                f"- 失败：{runtime_metadata.get('failed_count', 0)}",
                f"- 降级：{runtime_metadata.get('warning_count', 0)}",
            ]
        )
    lines.extend(
        [
            "",
            "| 股票 | 变化状态 | 关注度 | 数据权限 | 日线 | 1H | 15m | 多周期 |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    if not rows:
        lines.append("| 暂无技术状态 | - | - | - | - | - | - | - |")
        return "\n".join(lines) + "\n"

    for row in rows:
        evidence = row.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        technical = evidence.get("technical")
        technical = technical if isinstance(technical, dict) else {}
        lines.append(
            f"| {row.get('code', '')} | {row.get('state', 'unchanged')} | "
            f"{row.get('attention', 'none')} | {evidence.get('signal_permission', 'blocked')} | "
            f"{_trend(technical, 'daily')} | {_trend(technical, 'hourly')} | "
            f"{_trend(technical, 'intraday')} | {technical.get('alignment', 'unknown')} |"
        )
    return "\n".join(lines) + "\n"


def _trend(technical: dict[str, Any], key: str) -> str:
    value = technical.get(key)
    return str(value.get("trend") or "unknown") if isinstance(value, dict) else "unknown"
