# 美股研究数据质量

美股研究扫描会在候选 JSON 的 `valuation_health` 字段和 Markdown 报告中记录估值数据质量。该字段只用于解释研究结果的数据基础，不改变候选评分、发布保护或提醒规则，也不构成交易建议。

健康度使用 PE 与 PB 中较低的一项覆盖率：

- `high`：实时最低覆盖率至少 80%，且没有估值请求错误或缓存回填。
- `medium`：最终有效覆盖率至少 70%，但存在请求错误、缓存回填或实时覆盖不足。
- `low`：最终有效覆盖率低于 70%，或实时最低覆盖率不高于 10% 且至少一半请求失败。

`effective_coverage_ratio` 包含本轮实时值和未过期的历史缓存值；`live_coverage_ratio` 只计算本轮实时值。缓存能够保持筛选连续性，但不能被解释为实时数据。

## Scheduled Research Data Capture fail-closed contract (2026-10-14)

`.github/workflows/research-data-capture.yml` intentionally runs network captures with
`continue-on-error` so source-side failures still produce per-symbol blocked manifests
and uploadable diagnostics. **That does not imply dataset approval or a passing job.**
The mandatory `Validate recorded captures` step checks the complete frozen
17-symbol research universe through `validate_research_universe_capture.py`,
and independently verifies `cn_600000` and `us_SPY` CSV/manifest pairs. Missing,
blocked, tampered or malformed required captures make the workflow fail; the
`Upload recorded captures and manifests` step still runs on failure. No
invalid prices are dropped, rounded, backfilled or silently replaced, and no
live source, Radar, Paper or trade eligibility is inferred from a research artifact.

Observed on 2026-10-14: A-share research EOD was available, but 12 US symbols
were `CAPTURE_BLOCKED` because `yfinance` supplied non-finite `Close` on
2026-10-13. This is **not** an OpenD diagnosis. A successful job after the
change needs real valid captures and separately assessed PIT approval; do not
weaken validation or relabel a blocked manifest to make CI green.
