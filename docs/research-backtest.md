# 独立研究回测机：RS Breakout 验证

\`run_rs_breakout_validation.py\` 是 Research-only 的只读验证入口，和 Radar 生产内容、生产状态、交易执行路径隔离。

## 输入与边界

- 输入只能是带 \`.manifest.json\` 的已记录 EOD OHLCV capture。
- manifest 必须为 \`CAPTURED_NOT_APPROVED\`，且 \`raw_sha256\` 必须匹配；不满足即 fail-closed。
- 规则合同必须保持 \`RESEARCH_ONLY\`，\`production_authorized=false\`。
- 信号只使用决策 bar 及其之前的价格、成交量和横截面 RS；未来 bar 只用于计算 forward outcome。
- 不注册实验、不 claim/burn Never-Seen Holdout，不写生产数据库。

## 运行

\`\`\`bash
python scripts/run_rs_breakout_validation.py \
  --config config/rs_breakout_hypothesis_v0_1.json \
  --input-dir artifacts/universe \
  --output artifacts/universe/rs_breakout_validation.json
\`\`\`

输出 schema 为 \`radar-rs-breakout-validation-v0.1\`，包含：

- \`WITH_RULE\`
- \`WITHOUT_RULE\`
- \`SHUFFLED_PLACEBO\`
- \`DELAYED_RULE\`
- \`REGIME_CONDITIONED\`

每个变体同时提供 overall、development、validation 和 \`never_seen_holdout\` 指标。结果中的 \`guard\` 明确记录 PIT、Holdout 和生产授权状态；它是证据，不是 Promotion verdict。

每日 \`Research Universe Capture\` 在 capture 验证通过后自动生成该 JSON，并将其与原始 capture 一起上传为 Actions artifact。真实数据结果仍需经过 Registry、OOS Ledger 和 Control Tower 的独立裁决，不能仅凭该文件升级规则。
