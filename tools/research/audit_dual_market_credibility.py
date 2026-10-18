"""Independent, read-only credibility audit for the dual-market replay assets.

The audit consumes generated V1.0/V1.1 assets. It does not infer provider
finality, total-return semantics, or out-of-sample status from successful files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


VALID_STATUSES = {"PASS", "FAIL", "UNKNOWN", "NOT_VERIFIED"}
VALID_STATES = {"RISK_ON", "NEUTRAL", "DEFENSIVE"}
EXPECTED_COSTS = {"5bp_fee_5bp_slippage", "10bp_fee_10bp_slippage"}


def _find(directory: Path, suffix: str) -> Path:
    matches = sorted(directory.glob(f"*_{suffix}"))
    if len(matches) != 1:
        raise ValueError(f"expected one *_{suffix} in {directory}, found {len(matches)}")
    return matches[0]


def _check(name: str, status: str, evidence: str) -> dict[str, str]:
    if status not in VALID_STATUSES:
        raise ValueError(status)
    return {"check": name, "status": status, "evidence": evidence}


def _hash_check(metadata: dict, paths: dict[str, Path]) -> list[dict[str, str]]:
    rows = []
    declared = metadata.get("sha256", {})
    for key in ("metrics", "states", "episodes", "coverage"):
        path = paths.get(key)
        if path is None:
            rows.append(_check(f"hash_{key}", "UNKNOWN", "asset not present"))
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = declared.get(path.name)
        rows.append(_check(
            f"hash_{key}", "PASS" if expected == actual else "FAIL",
            f"file={path.name}; expected={expected}; actual={actual}"))
    return rows


def audit_asset_set(directory: Path, version: str) -> tuple[list[dict[str, str]], dict[str, object]]:
    paths = {key: _find(directory, f"{key}.csv") for key in ("coverage", "metrics", "states")}
    metadata_path = _find(directory, "metadata.json")
    paths["metadata"] = metadata_path
    paths["report"] = _find(directory, "report.md")
    if version == "V1.1":
        paths["episodes"] = _find(directory, "episodes.csv")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    coverage = pd.read_csv(paths["coverage"])
    metrics = pd.read_csv(paths["metrics"])
    states = pd.read_csv(paths["states"], parse_dates=["date"])
    episodes = pd.read_csv(paths["episodes"]) if "episodes" in paths else None
    checks = _hash_check(metadata, paths)

    query = metadata.get("query", {})
    checks.extend([
        _check(f"{version}_source_endpoint", "PASS" if metadata.get("endpoint") == "127.0.0.1:11111" else "FAIL", str(metadata.get("endpoint"))),
        _check(f"{version}_query_contract", "PASS" if query.get("ktype") == "K_DAY" and query.get("session") == "RTH" and query.get("autype") == "QFQ" else "FAIL", str(query)),
        _check(f"{version}_first_readable_dates", "PASS" if coverage["first_readable_date"].notna().all() and (coverage["status"] == "OK").all() else "FAIL", "coverage.csv"),
        _check(f"{version}_sample_window", "PASS" if metrics["start"].notna().all() and metrics["end"].notna().all() else "FAIL", f"{metrics['start'].min()}—{metrics['end'].max()}"),
        _check(f"{version}_closed_bar_timing", "PASS" if metadata.get("signal_timing") == "closed_prior_rows_only_next_day_effective" else "UNKNOWN", str(metadata.get("signal_timing"))),
        _check(f"{version}_qfq_total_return_semantics", "UNKNOWN" if metadata.get("qfq_dividend_semantics") == "UNKNOWN" else "FAIL", str(metadata.get("qfq_dividend_semantics"))),
        _check(f"{version}_provider_finality", "UNKNOWN" if metadata.get("provider_finality") == "UNKNOWN" else "FAIL", str(metadata.get("provider_finality"))),
        _check(f"{version}_independent_calendar", "UNKNOWN" if metadata.get("timezone_exchange_calendar") in {None, "UNKNOWN"} else "FAIL", str(metadata.get("timezone_exchange_calendar"))),
        _check(f"{version}_oos", "NOT_VERIFIED" if metadata.get("oos_status") == "NOT_VERIFIED" else "FAIL", str(metadata.get("oos_status"))),
    ])

    state_group_columns = ["cost_scenario"]
    if "candidate" in states.columns:
        state_group_columns.insert(0, "candidate")
    state_dates = states.groupby(state_group_columns, sort=False)["date"]
    duplicate_groups = [str(k) for k, part in state_dates if part.duplicated().any()]
    unsorted_groups = [str(k) for k, part in state_dates if not part.is_monotonic_increasing]
    invalid_states = sorted(set(states["state"]) - VALID_STATES)
    checks.extend([
        _check(f"{version}_state_dates_unique", "FAIL" if duplicate_groups else "PASS", str(duplicate_groups)),
        _check(f"{version}_state_dates_sorted", "FAIL" if unsorted_groups else "PASS", str(unsorted_groups)),
        _check(f"{version}_state_labels", "FAIL" if invalid_states else "PASS", str(invalid_states)),
        _check(f"{version}_turnover_nonnegative", "FAIL" if (states["turnover"] < 0).any() else "PASS", f"min={states['turnover'].min()}"),
        _check(f"{version}_cost_scenarios", "PASS" if set(states["cost_scenario"]) == EXPECTED_COSTS else "FAIL", str(sorted(set(states["cost_scenario"]))),),
        _check(f"{version}_daily_nav_reconciliation", "UNKNOWN", "daily NAV/asset prices are not included in generated assets"),
    ])

    if version == "V1.1" and episodes is not None:
        bad_boundaries = []
        for key, part in episodes.groupby(["candidate", "cost_scenario"], sort=False):
            part = part.reset_index(drop=True)
            starts = pd.to_datetime(part["start"])
            ends = pd.to_datetime(part["end"])
            if len(part) > 1 and (ends.iloc[:-1].to_numpy() != (starts.iloc[1:] - pd.Timedelta(days=1)).to_numpy()).any():
                bad_boundaries.append(str(key))
            if ends.dt.dayofweek.isin([5, 6]).any():
                bad_boundaries.append(f"non_trading_calendar_end:{key}")
            if len(part) and part["days"].sum() <= 0:
                bad_boundaries.append(f"empty:{key}")
        checks.append(_check("V1.1_episode_calendar_boundaries", "FAIL" if bad_boundaries else "PASS", str(bad_boundaries)))
        checks.append(_check("V1.1_episode_state_count_reconciliation", "UNKNOWN", "episode end dates are calendar-derived and no daily NAV is embedded"))

    cost_groups = metrics.groupby(["strategy", "scope"], sort=False)
    cost_violations = []
    for key, part in cost_groups:
        by_cost = part.set_index("cost_scenario")
        if EXPECTED_COSTS.issubset(by_cost.index) and by_cost.loc["10bp_fee_10bp_slippage", "cumulative_return"] > by_cost.loc["5bp_fee_5bp_slippage", "cumulative_return"] + 1e-12:
            cost_violations.append(str(key))
    checks.append(_check(f"{version}_cost_sensitivity_monotonic", "FAIL" if cost_violations else "PASS", str(cost_violations)))

    stress_scopes = {str(value) for value in metrics["scope"] if any(str(year) in str(value) for year in (2020, 2022, 2025))}
    checks.append(_check(f"{version}_stress_windows_2020_2022_2025", "PASS" if len(stress_scopes) >= 3 else "FAIL", str(sorted(stress_scopes))))

    summary = {
        "version": version,
        "directory": str(directory),
        "asset_files": {key: str(value) for key, value in paths.items()},
        "checks": checks,
        "failure_count": sum(row["status"] == "FAIL" for row in checks),
        "unknown_count": sum(row["status"] in {"UNKNOWN", "NOT_VERIFIED"} for row in checks),
    }
    return checks, summary


def compare_replay_assets(source: Path, replay: Path, version: str) -> list[dict[str, str]]:
    suffixes = ["metrics.csv", "states.csv", "coverage.csv"]
    if version == "V1.1":
        suffixes.append("episodes.csv")
    rows = []
    for suffix in suffixes:
        source_file = _find(source, suffix)
        replay_file = _find(replay, suffix)
        source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
        replay_hash = hashlib.sha256(replay_file.read_bytes()).hexdigest()
        rows.append(_check(
            f"{version}_opend_rerun_{suffix.removesuffix('.csv')}",
            "PASS" if source_hash == replay_hash else "FAIL",
            f"source={source_hash}; replay={replay_hash}"))
    return rows


def write_outputs(results: list[dict[str, object]], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v12_credibility_audit_2026-10-18"
    checks = [row for result in results for row in result["checks"]]
    checks_path = output_dir / f"{prefix}_checks.csv"
    summary_path = output_dir / f"{prefix}_summary.json"
    report_path = output_dir / f"{prefix}_report.md"
    pd.DataFrame(checks).to_csv(checks_path, index=False, encoding="utf-8-sig")
    summary = {"audit": "V1.2 independent credibility audit", "results": results}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# STOCK RAZOR Dual-Market Strategy V1.2 独立可信度审计", "", "审计只读核对 V1.0/V1.1 生成资产；UNKNOWN 与 NOT_VERIFIED 不视为 PASS。", ""]
    for result in results:
        lines.extend([f"## {result['version']}", "", f"- FAIL={result['failure_count']}; UNKNOWN/NOT_VERIFIED={result['unknown_count']}", ""])
        for row in result["checks"]:
            lines.append(f"- `{row['status']}` `{row['check']}`：{row['evidence']}")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {"checks": str(checks_path), "summary": str(summary_path), "report": str(report_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v11-dir", type=Path, required=True)
    parser.add_argument("--v10-dir", type=Path, required=True)
    parser.add_argument("--replay-v10-dir", type=Path)
    parser.add_argument("--replay-v11-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for directory, version in ((args.v10_dir, "V1.0"), (args.v11_dir, "V1.1")):
        _, summary = audit_asset_set(directory, version)
        replay = args.replay_v10_dir if version == "V1.0" else args.replay_v11_dir
        if replay:
            summary["checks"].extend(compare_replay_assets(directory, replay, version))
            summary["failure_count"] = sum(row["status"] == "FAIL" for row in summary["checks"])
            summary["unknown_count"] = sum(row["status"] in {"UNKNOWN", "NOT_VERIFIED"} for row in summary["checks"])
        results.append(summary)
    print(json.dumps(write_outputs(results, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
