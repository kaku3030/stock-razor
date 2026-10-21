from __future__ import annotations

import argparse
import json
from pathlib import Path

TFS = ("D1", "1H", "15m", "5m", "1m")


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline data-coverage gate for Round28 mixed-market cohort.")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--us-capture-dir", type=Path, action="append", required=True,
                    help="capture root; repeat to combine immutable local capture batches")
    ap.add_argument("--cn-capture-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--opend-quota-used", type=int, required=True)
    ap.add_argument("--opend-quota-remaining", type=int, required=True)
    ap.add_argument("--cn-access-status", choices=("not-tested", "local-opend-denied", "available"), default="not-tested")
    args = ap.parse_args()

    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    markets = cfg["markets"]
    specs = (
        ("us", args.us_capture_dir, "US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv"),
        ("cn", [args.cn_capture_dir], "CN_{symbol}_{tf}_qfq_20190101_20261016.csv"),
    )
    details = []
    counts = {}
    for market, roots, pattern in specs:
        symbols = markets[market]["symbols"]
        present = 0
        missing = []
        for item in symbols:
            symbol = item["symbol"]
            for tf in TFS:
                name = pattern.format(symbol=symbol, tf=tf)
                candidates = [root / name for root in roots]
                path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
                ok = path.is_file() and path.stat().st_size > 0
                present += int(ok)
                if not ok:
                    missing.append({"symbol": symbol, "timeframe": tf, "path": str(path)})
        counts[market] = {
            "symbol_count": len(symbols),
            "expected_files": len(symbols) * len(TFS),
            "present_files": present,
            "missing_files": len(missing),
            "missing_symbols": sorted({row["symbol"] for row in missing}),
            "missing_detail": missing,
        }

    us_missing_symbols = len(counts["us"]["missing_symbols"])
    cn_missing_symbols = len(counts["cn"]["missing_symbols"])
    additional_us_needed = max(0, us_missing_symbols)
    quota_shortfall_us_only = max(0, additional_us_needed - args.opend_quota_remaining)
    total_expected = sum(row["expected_files"] for row in counts.values())
    total_present = sum(row["present_files"] for row in counts.values())

    blockers = []
    if quota_shortfall_us_only:
        blockers.append("LOCAL_OPEND_HISTORY_QUOTA_INSUFFICIENT_FOR_MISSING_US_SYMBOLS")
    if cn_missing_symbols:
        blockers.append("LOCAL_TICKFLOW_CN_HISTORICAL_CACHE_MISSING")
    if args.cn_access_status == "local-opend-denied":
        blockers.append("LOCAL_OPEND_CN_MARKET_ENTITLEMENT_MISSING")
    if cfg.get("membership_controls", {}).get("point_in_time_membership") != "VERIFIED":
        blockers.append("POINT_IN_TIME_UNIVERSE_MEMBERSHIP_UNVERIFIED")
    if cfg.get("strategy_rule_controls", {}).get("S2", "").startswith("UNVALIDATED"):
        blockers.append("OFFICIAL_S2_RULE_UNAVAILABLE")

    status = {
        "schema": "stock-razor-round28-data-gate-v1",
        "universe_id": cfg["universe_id"],
        "as_of": cfg["as_of"],
        "status": "BLOCKED" if blockers else "READY_FOR_BACKTEST",
        "provider_requests_made_by_this_script": 0,
        "market_data_reads_made_by_this_script": 0,
        "cn_local_access_status": args.cn_access_status,
        "opend_history_quota": {
            "used": args.opend_quota_used,
            "remaining": args.opend_quota_remaining,
            "missing_us_symbols": additional_us_needed,
            "us_quota_shortfall": quota_shortfall_us_only,
        },
        "expected_input_files": total_expected,
        "present_input_files": total_present,
        "coverage_pct": round(100 * total_present / total_expected, 2) if total_expected else 0,
        "markets": counts,
        "blockers": blockers,
        "policy": "No paid history request; no market fallback; no strategy promotion. US and CN P&L remain separate.",
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "round28_data_gate_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Round28 70 US + 30 A-share data gate",
        "",
        f"Status: **{status['status']}**",
        "",
        f"- Data files present: {total_present}/{total_expected} ({status['coverage_pct']}%).",
        f"- US: {counts['us']['present_files']}/{counts['us']['expected_files']} files; "
        f"{len(counts['us']['missing_symbols'])} symbols have at least one missing timeframe.",
        f"- A-shares: {counts['cn']['present_files']}/{counts['cn']['expected_files']} files; "
        f"{len(counts['cn']['missing_symbols'])} symbols have at least one missing timeframe.",
        f"- Local OpenD history quota: {args.opend_quota_used} used, {args.opend_quota_remaining} remaining; "
        f"{additional_us_needed} missing US symbols exceed remaining quota by {quota_shortfall_us_only}.",
        "- Local TickFlow A-share historical cache: not found in the inspected local capture/cache roots.",
        f"- Local OpenD A-share entitlement trial: {args.cn_access_status}.",
        "- Provider calls made by this audit: 0. It only checked local filenames and file sizes.",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {item}" for item in blockers)
    lines += [
        "",
        "## Interpretation",
        "",
        "This is a candidate-universe and input-availability audit, not a strategy backtest. "
        "Round27 results for 30 US names cannot be relabeled as a 70 US + 30 A-share result. "
        "S2 remains an unvalidated candidate because its official frozen rules are unavailable. "
        "No USD and CNY P&L, costs, or drawdowns are combined.",
        "",
        "See `round28_data_gate_status.json` for the per-symbol/timeframe missing-input list.",
        "",
    ]
    (args.output_dir / "round28_data_gate.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: status[k] for k in ("status", "expected_input_files", "present_input_files", "coverage_pct", "blockers")}, ensure_ascii=False))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
