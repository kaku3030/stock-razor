# 文档中心

这里是项目文档入口。README 负责项目概览和快速开始；更完整的配置、部署、功能说明和排障内容从这里进入。

## 按场景选择

| 我想要 | 先看 | 继续看 |
| --- | --- | --- |
| 快速了解项目能做什么 | [README](../README.md) | [完整配置与部署指南](full-guide.md) |
| 第一次把项目跑起来 | [小白客户端安装与配置](beginner-client-setup.md) | [完整配置与部署指南](full-guide.md) |
| 配置大模型渠道 | [LLM 配置指南](LLM_CONFIG_GUIDE.md) | [LLM 服务商配置指南](llm-providers.md)（含 xAI Grok 直连） |
| 配置推送通知 | [通知能力基线](notifications.md) | [完整配置与部署指南](full-guide.md) |
| 部署到服务器或云平台 | [部署指南](DEPLOY.md) | [云端 WebUI 部署](deploy-webui-cloud.md)、[Zeabur 部署](docker/zeabur-deployment.md) |
| 使用 Bot / IM 接入 | [Bot 命令与接入](bot-command.md) | [Bot 平台配置](bot/)、[Grok Bot 集成](grok-bot-integration.md) |
| 排查运行问题 | [FAQ](FAQ.md) | [更新日志](CHANGELOG.md) |
| 处理数据源失败或降级 | [数据源稳定性与故障处理图示](data-source-stability.md) | [FAQ](FAQ.md) |
| 参与开发或提交 PR | [贡献指南](CONTRIBUTING.md) | [API 规格](architecture/api_spec.json) |

## 快速开始

| 文档 | 内容 |
| --- | --- |
| [README](../README.md) | 项目定位、核心能力、快速开始、推送效果 |
| [小白客户端安装与配置](beginner-client-setup.md) | 面向不会代码用户的客户端下载、Anspire Open / AIHubMix 模型配置、新闻源配置和常见问题 |
| [完整配置与部署指南](full-guide.md) | 环境准备、运行方式、配置说明、部署路径和常见问题 |
| [FAQ](FAQ.md) | 常见配置、模型、通知、部署和运行问题 |
| [数据源稳定性与故障处理图示](data-source-stability.md) | Tushare、TickFlow、AkShare、Efinance、YFinance、Longbridge 等已接入源的使用场景、fallback 链路和推荐配置 |
| [更新日志](CHANGELOG.md) | 版本变化、能力调整和迁移说明 |

## 配置

| 文档 | 内容 |
| --- | --- |
| [LLM 配置指南](LLM_CONFIG_GUIDE.md) | 大模型渠道、三层配置、Web 设置页和常见模型配置 |
| [LLM 服务商配置指南](llm-providers.md) | Provider 预设、Actions 映射、错误分类和诊断建议 |
| [LiteLLM YAML 示例](examples/litellm_config.example.yaml) | LiteLLM 多渠道配置示例 |
| [Grok Bot Skill 示例](examples/grok_bot/README.md) | 给 Grok Bot 粘贴的最小 Skill，调用现有 REST |
| [通知能力基线](notifications.md) | 企业微信、飞书、Telegram、Discord、Slack、邮件等通知渠道配置 |
| [Tushare 股票列表指南](TUSHARE_STOCK_LIST_GUIDE.md) | Tushare 股票列表相关配置和使用说明 |

## 使用专题

| 文档 | 内容 |
| --- | --- |
| [Bot 命令与接入](bot-command.md) | Bot 命令、Webhook、平台接入和回调说明 |
| [Bot 平台配置](bot/) | 飞书、钉钉、Discord 等 Bot 配置截图和补充说明 |
| [实时告警中心](alerts.md) | EventMonitor 基线、Web 规则管理、通知结果、冷却状态和 Phase 边界 |
| [DecisionSignal 决策信号专题](decision-signals.md) | AI 建议池字段语义、API、Web 展示、告警/通知/组合风险联动、后验评估、脱敏、迁移与回滚 |
| [Strategy Lab V0.1 冻结规格](strategy-lab-v0.1-spec-freeze.md) | Stock Radar 策略验证基础设施的冻结范围、Hard Gate、永久对抗测试、验收矩阵与非目标 |
| [Radar Rule Validation Harness V0.1](radar-rule-validation-harness-v0.1.md) | 规则合同、PIT/anti-leak preflight、原子实验预算 Registry、Never-Seen Holdout 边界、counterfactual 计划与 OSS-first 决策记录 |
| [Radar Rule Validation Harness Day 3–7 closure](radar-rule-validation-harness-day3-7-closure.md) | Dataset Capsule、reservation→OOS 编排、合成 fixture E2E 与真实数据/Promotion 阻塞状态 |
| [ResearchArtifact 结构化研究产物](research-artifact.md) | structured_report 字段、Thesis / Evidence / Invalidation / Next Action / Data Quality 契约和旧报告兼容边界 |
| [资讯 / 情报源](intelligence-sources.md) | RSS/Atom 合规资讯源配置、测试、拉取、去重、存储、查询与安全边界 |
| [分析上下文包契约、运行态消费与可见性](analysis-context-pack.md) | AnalysisContextPack 首版范围、字段质量状态、P1/P2 内部契约、P3 Prompt 摘要消费、P4 历史/API/Web 低敏可见性、P5 数据质量评分、P6 迁移回滚与源码锚点；完整指南补充 #1386 阶段感知分析、迁移与回滚入口 |
| [图片识别 Prompt](image-extract-prompt.md) | 图片识别股票信息的 Prompt 与使用边界 |
| [OpenClaw Skill 集成](openclaw-skill-integration.md) | OpenClaw / Skill 外部集成说明 |
| [Grok Bot 集成](grok-bot-integration.md) | 2026-08-11 Grok Bot（AI teammate）与 DSA REST / DecisionSignal / Skill 的对接边界 |

## 部署与打包

| 文档 | 内容 |
| --- | --- |
| [部署指南](DEPLOY.md) | 服务器部署、Docker、systemd、Supervisor 等部署方式 |
| [云端 WebUI 部署](deploy-webui-cloud.md) | 云服务器访问 WebUI 的部署说明 |
| [Zeabur 部署](docker/zeabur-deployment.md) | Zeabur 平台部署说明 |
| [桌面端打包说明](desktop-package.md) | Electron 桌面端和 Web 构建产物打包说明 |

## 参考与开发

| 文档 | 内容 |
| --- | --- |
| [API 规格](architecture/api_spec.json) | FastAPI OpenAPI 规格产物 |
| [Cloud Fast Path Performance V0.1](architecture/CLOUD_FAST_PATH_PERFORMANCE_V0_1.md) | 云端 OpenD → canonical → Radar → MCP/Main Control 的性能 SLO、分层 telemetry、P50/P95/P99 与 FAST+FRESH+COMPLETE+CORRECT+FULL-QUALITY 验收门禁 |
| [Cloud Fast Path Metrics V0.1](architecture/CLOUD_FAST_PATH_METRICS_V0_1.md) | US/CN 云端 fast path 的 fail-closed 性能样本与 P50/P95/P99 汇总；严格区分 provider/canonical/Radar compute/read/MCP/E2E，缺失证据保持 UNKNOWN |
| [Provider Lifecycle / Cost Guard V0.1](architecture/PROVIDER_LIFECYCLE_COST_GUARD_V0_1.md) | Self-Survival Layer：Provider 生命周期、额度/费用、凭据、fallback 质量门禁、主动提醒与禁止自动付费合同 |
| [Runtime Provider Observer / Evidence Provenance V0.1](architecture/PROVIDER_RUNTIME_OBSERVER_V0_1.md) | 运行时 provider 证据、field-level provenance、observed_at/source/error code/repo/runtime 追踪，以及 Provider Health 与 Data Admission 分离 |
| [OpenD Runtime Evidence Ingest V0.1](architecture/PROVIDER_OPEND_RUNTIME_INGEST_V0_1.md) | 将现有云端 US OpenD heartbeat 保守映射为 Provider Lifecycle evidence；保留 exact SHA/runtime provenance，不把 REALTIME/closure 升级为 Data Admission 或 HEALTHY |
| [CN Runtime Evidence Ingest V0.1](architecture/PROVIDER_CN_RUNTIME_INGEST_V0_1.md) | 将 A 股云端 Eastmoney-primary/Tencent-fallback per-frame lineage 拆成 provider-specific runtime evidence；fallback 不反向证明 Eastmoney 健康，currentness/route latency 不冒充 provider freshness/latency |
| [Alpaca Runtime Evidence Ingest V0.1](architecture/PROVIDER_ALPACA_RUNTIME_INGEST_V0_1.md) | 将 Alpaca adapter 生命周期事件映射为 fallback-provider evidence；feed=SIP 不等于 SIP entitlement，worker/registration 不升级 HEALTHY，Bar/Quote freshness 仍属 Data Admission |
| [Negative Provider Probe Ingest V0.1](architecture/PROVIDER_NEGATIVE_PROBE_INGEST_V0_1.md) | OpenAI/Anthropic/Tavily/Twelve Data/EODHD/AWS 的标准化负向 auth/quota/rate-limit/failure evidence；仅允许降级/失败，不接受 raw response/密钥，也不产生 HEALTHY/余额/Admission 证据 |
| [Provider Alert Engine V0.1](architecture/PROVIDER_ALERT_ENGINE_V0_1.md) | 将 Provider Guard assessment 转为 OPEN/UPDATED/RESOLVED typed transitions；UNKNOWN/HEALTHY 不发 generic alert，specific guard code 优先去重，旧 evidence fail-closed |
| [Provider Notification Gateway V0.1](architecture/PROVIDER_NOTIFICATION_GATEWAY_V0_1.md) | 将 Provider Alert transition 薄桥接到现有 route_type=alert 通知栈；复用 dedup/cooldown/渠道诊断，RESOLVED 独立 cooldown，通知失败不回写 lifecycle/Radar 状态 |
| [Provider Alert Shadow Validation V0.1](architecture/PROVIDER_ALERT_SHADOW_VALIDATION_V0_1.md) | 对真实 Provider snapshots 运行 Alert Engine 但禁用通知发送，记录 deterministic shadow journal/覆盖统计；shadow 永远不能自行升级 active notification |
| [贡献指南](CONTRIBUTING.md) | Issue、PR、测试、文档同步和协作要求 |

## 多语言

| 文档 | 内容 |
| --- | --- |
| [英文文档索引](INDEX_EN.md) | English documentation index |
| [英文 README](README_EN.md) | English project overview and quick start |
| [繁中 README](README_CHT.md) | 繁體中文項目概覽與快速開始 |
