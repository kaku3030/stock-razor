#!/usr/bin/env python3
"""Bounded AWS EC2 *offline* Paper restart smoke. Synthetic adapter only.

The caller transports this exact reviewed file over fixed-target SSM, pins an
already-installed source SHA, runs against a throwaway SQLite directory and
discards all records afterwards. No external SIM, OpenD, market data, trade
adapter, scheduler, SecretString or notifications are accessed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import re
import socket
import subprocess
import tempfile


ALLOWED_RUNTIME_ROOT = Path("/opt/stock-razor-us-radar/repo")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def run_offline_cloud_soak(*, runtime_root: Path, expected_sha: str) -> dict[str, str]:
    result = {
        "schema": "stock_razor_ec2_paper_noorder_smoke_v0_1",
        "runtime_sha": "NOT_VERIFIED",
        "isolated_paper_restart": "NOT_VERIFIED",
        "duplicate_paper_intent_veto": "NOT_VERIFIED",
        "temporary_store_only": "YES",
        "external_provider_calls": "NONE",
        "external_broker_orders": "NONE",
        "secretstring": "NOT_READ",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "paper_auto_ready": "NO",
        "live_trade": "NO",
        "trade_execution": "NO",
    }
    if runtime_root != ALLOWED_RUNTIME_ROOT or _HEX40.fullmatch(expected_sha) is None:
        return result
    if not runtime_root.is_dir():
        return result

    verified = subprocess.run(
        ["git", "-C", str(runtime_root), "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if verified.returncode != 0 or verified.stdout.strip() != expected_sha:
        return result
    result["runtime_sha"] = "PASS"

    # Defense-in-depth: the script never imports an external broker transport;
    # additionally block standard socket connections *before* any src imports.
    def forbidden_connect(*_args, **_kwargs):
        raise RuntimeError("OFFLINE_NETWORK_FORBIDDEN")

    socket.socket.connect = forbidden_connect
    socket.socket.connect_ex = forbidden_connect
    socket.create_connection = forbidden_connect

    from src.services.execution_engine import (
        ExecutionBlocked, ExecutionEngine, ExecutionStore, OrderState,
        RiskContext, RiskGuard, RiskLimits, Side, create_paper_adapter,
    )
    from src.services.paper_execution_admission import PaperOrderSpec
    from src.services.paper_runtime_orchestrator import (
        PaperRuntimeOrchestrator, PaperRuntimeState,
    )
    from src.services.stock_radar_v2.observation_ledger import Observation

    def risk() -> RiskGuard:
        return RiskGuard(RiskLimits(
            frozenset({"AMD"}), Decimal("5000"), Decimal("100"),
            Decimal("10000"), Decimal("20000"), Decimal("0.01"),
            10, 60, 60,
        ))

    def make_runtime(root: Path):
        capability = create_paper_adapter()
        engine = ExecutionEngine(
            capability, risk(), ExecutionStore(root / "execution.sqlite"),
        )
        owner = PaperRuntimeOrchestrator(
            engine, runtime_generation="ec2-offline-synthetic",
            account_generation="ec2-synthetic-account",
            shadow_store=ExecutionStore(root / "shadow.sqlite"),
        )
        owner.initialize_offline_balance(
            Decimal("100000"), datetime.now(timezone.utc),
        )
        return owner, capability.adapter

    def permission(seq: int, now: datetime) -> Observation:
        return Observation(
            observation_id=f"ec2-offline-obs-{seq}",
            detector_status="CONFIRMED",
            evidence_ids=(f"ec2-offline-snapshot-{seq}",),
            strategy_gate_results={"entry_gate": "PASS"},
            strategy_eligible=True,
            portfolio_admissible=True,
            portfolio_block_reasons=(),
            execution_feasible=True,
            decision_available_at=now.timestamp() - 2,
            confirmed_at=now.timestamp() - 1,
            earliest_executable_at=now.timestamp() - 1,
            canonical_permission="PASS",
        )

    def spec(seq: int, now: datetime) -> PaperOrderSpec:
        return PaperOrderSpec(
            action_id=f"ec2-offline-action-{seq}",
            symbol="AMD", side=Side.BUY,
            qty=Decimal("10"), limit_price=Decimal("100"),
            stop_price=Decimal("97"), max_slippage=Decimal("0.001"),
            invalidation=Decimal("96"), risk_budget_r=Decimal("1"),
            strategy_id="offline-ec2-restart-only",
            evidence_snapshot_id=f"ec2-offline-snapshot-{seq}",
            valid_until=now + timedelta(minutes=5),
            allowed_session="RTH",
        )

    with tempfile.TemporaryDirectory(prefix="stock-razor-paper-noorder-") as td:
        root = Path(td)
        first, paper_one = make_runtime(root)
        assert first.start().state is PaperRuntimeState.READY
        now = datetime.now(timezone.utc)
        first_result = first.process(permission(1, now), spec(1, now), RiskContext(now, now, "RTH"))
        assert first_result.order_state is OrderState.ACCEPTED
        assert first_result.broker_order_id == "paper-order-1"
        assert len(paper_one.calls) == 1
        assert first.stop().state is PaperRuntimeState.STOPPED
        for store in (first._engine.store, first._shadow._store):
            store.connection.close()

        second, paper_two = make_runtime(root)
        assert second.start().state is PaperRuntimeState.READY
        now = datetime.now(timezone.utc)
        try:
            second.process(permission(1, now), spec(1, now), RiskContext(now, now, "RTH"))
        except ExecutionBlocked:
            pass
        else:
            raise AssertionError("DUPLICATE_PAPER_INTENT_NOT_BLOCKED")
        assert paper_two.calls == []
        result["duplicate_paper_intent_veto"] = "PASS"
        second_result = second.process(permission(2, now), spec(2, now), RiskContext(now, now, "RTH"))
        assert second_result.order_state is OrderState.ACCEPTED
        assert second_result.broker_order_id == "paper-order-2"
        assert len(paper_two.calls) == 1
        assert second.stop().state is PaperRuntimeState.STOPPED
        for store in (second._engine.store, second._shadow._store):
            store.connection.close()

        recovered, paper_three = make_runtime(root)
        snap = recovered.start()
        assert snap.state is PaperRuntimeState.READY
        assert snap.order_records == 2
        assert paper_three.calls == []
        assert recovered.stop().state is PaperRuntimeState.STOPPED
        for store in (recovered._engine.store, recovered._shadow._store):
            store.connection.close()
        result["isolated_paper_restart"] = "PASS"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-runtime-sha", required=True)
    parser.add_argument("--runtime-root", default=str(ALLOWED_RUNTIME_ROOT))
    args = parser.parse_args()

    # Fixed-value statuses ONLY; never leak exception details into SSM logs.
    import json
    try:
        report = run_offline_cloud_soak(
            runtime_root=Path(args.runtime_root),
            expected_sha=args.expected_runtime_sha,
        )
    except Exception:
        report = {
            "schema": "stock_razor_ec2_paper_noorder_smoke_v0_1",
            "runtime_sha": "NOT_VERIFIED",
            "isolated_paper_restart": "NOT_VERIFIED",
            "duplicate_paper_intent_veto": "NOT_VERIFIED",
            "external_provider_calls": "NONE",
            "external_broker_orders": "NONE",
            "paper_auto_ready": "NO",
            "radar_admission": "BLOCKED",
            "source_arbiter_admission": "BLOCKED",
            "live_trade": "NO",
            "trade_execution": "NO",
            "secretstring": "NOT_READ",
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if (
        report["runtime_sha"] == "PASS"
        and report["isolated_paper_restart"] == "PASS"
        and report["duplicate_paper_intent_veto"] == "PASS"
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
