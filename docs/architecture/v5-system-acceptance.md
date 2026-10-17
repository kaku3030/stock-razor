# STOCK RAZOR V5.1 系统需求、所有权与验收矩阵

本文件是系统验收的唯一索引，治理规则以 [AGENTS.md](../../AGENTS.md) 为准。
需求来源：[Owner V5.1 Charter](https://github.com/kaku3030/stock-razor/pull/71#issuecomment-6229969610)。
内部 L3 是能力目标，不是外部认证，也不是当前就绪状态。

## 责任和集成约定

一个窗口、一个统一主控、七条工程路线。未另行分派前，当前统一主控是各路线工程任务的默认责任主体；表中的 owner 是职责角色，不表示七个 Agent 或后台服务已启动。每个实际任务必须记录唯一 task ID、具名执行者、branch/worktree、基线/HEAD SHA、状态及关联反馈。重复反馈关联同一主任务。独立任务并行；公共接口与最终集成由统一主控负责。

| 路线 / owner 职责 | 优先级 | 复用的现有实现 | 本路线必须提供的验收结果 | 阻塞依赖 |
| --- | --- | --- | --- | --- |
| A / TickFlow 数据负责人 | P0 | [TickFlow cache](../../data_provider/cn_tickflow_research_cache.py)、[worker](../../scripts/run_cn_tickflow_research_worker.py)、[subscription manager](../../src/services/live_feed/tickflow_subscription_manager.py) | A1 五周期有限 OHLCV、时区/交易日历、连续性/新鲜度/闭合证据；A2 有界动态订阅、重连补缺、权益与成本；A3 Windows Native / AWS 同口径实盘时段证据 | 无；向 C/D 提供合格数据，G 只读观察 |
| B / OpenD 数据负责人 | P0 | [stream adapter](../../data_provider/futu_k1m_streaming_adapter.py)、[closure pipeline](../../src/services/live_feed/futu_k1m_closure_pipeline.py)、[subscription manager](../../src/services/live_feed/opend_subscription_manager.py)、[canonical reader](../../data_provider/us_canonical_runtime_reader.py) | B1 五周期、QOT 权限、US 盘前/盘中/盘后及 DST；B2 有界候选、保护 baseline、重连补缺；B3 精确部署 SHA、闭合与实时交付的云端证据 | 无；不得把 preview 当作实际订阅执行 |
| C / Autonomous Radar 负责人 | P0 | [Radar](../../src/services/stock_radar_v2/)、[notification router](../../src/services/stock_radar_v2/runtime_notifications.py)、[latency audit](../../src/services/stock_radar_v2/notification_latency_audit.py) | C1 AWS 每 30 分钟按交易日历独立运行；C2 D1/1H/15m 确认、5m 按需触发、reason codes 与确定性风险；C3 去重、可追踪提醒送达、失败恢复及电脑关闭时持续运行 | A/B 数据准入 + F 调度/版本 + G 证据；先完成 30m 真实验收再评估 15m/5m |
| D / Paper & Replay 负责人 | P1 | [paper admission](../../src/services/paper_execution_admission.py)、[execution engine](../../src/services/execution_engine.py)、[closed-bar replay](../../src/services/closed_bar_paper_replay.py)、[Strategy Lab](../../src/services/strategy_lab/) | D1 隔离 Paper 订单/资金/持仓/回执对账、重启与幂等；D2 先做约两周、5–10 标的逐根 PIT 回放，含费用/滑点、MFE/MAE/R/回撤及误报漏报；D3 冻结数据版本与 OOS 记录 | 真实数据实验依赖 A/B；合成 fixture 和失败注入可独立进行 |
| E / Engineering Autonomy 负责人 | P1 | [coding gate](../../engineering_autonomy/coding_gate.py)、[queue loop](../../engineering_autonomy/loop.py)、[engineering CLI](../../scripts/engineering_autonomy.py) | E1 有界授权任务队列→隔离修改→回归→PR/CI；E2 预算、超时、次数、停止开关、检查点与恢复；E3 不自动合并/部署，不扩权 | 可独立离线开发；G 监控 E，但不能借监控接口执行代码 |
| F / Operations 与集成负责人 | P0/P1 | [CI gate](../../scripts/ci_gate.sh)、[cloud audit](../../scripts/audit_cloud_runtime_readonly.py)、[CI](../../.github/workflows/ci.yml)、[Feedback Hub proposal #873](https://github.com/kaku3030/stock-razor/pull/873) | F1 反馈发现→去重→owner→复现→修复→回归→PR/CI→授权集成/部署→运行证据→关闭；F2 main/HEAD/deployed SHA 与回滚；F3 调度/权限/凭据/日志脱敏与故障恢复 | 统一集成门禁；同一生产环境、调度器、供应商订阅状态的修改串行化 |
| G / Autonomy Monitoring 负责人 | P0 | [billing/renewal watch](../../scripts/provider_billing_renewal_watch.py)、[watch workflow](../../.github/workflows/provider-billing-renewal-watch.yml)、[budget guard](../../engineering_autonomy/deepseek_budget.py)、[systemd notify](../../src/services/stock_radar_v2/systemd_notify.py) | G1 独立观测心跳、任务进度/卡死、重试/恢复和 PR/CI；G2 DeepSeek/OpenAI 用量、费用、余额、额度/续期、AWS 服务/成本；G3 缺失/过期证据标记 UNKNOWN/NOT_VERIFIED 并产生可行动告警 | 与 E 共用任务/审计标识、复用现有通知路由；不得新建平行执行器或额外收费轮询 |

## 数据契约与边界

数据面复用 [Bar / Quote](../../data_provider/market_data_adapter.py)、[bar builder](../../data_provider/market_bar_builder.py)、[canonical export](../../src/services/live_feed/canonical_snapshot_export.py)；不另建第二区别不明的 canonical schema。工程控制面、行情/交易面、只读监控面保持能力隔离。

| V5.1 必需证据 | 当前映射 / 差距 |
| --- | --- |
| symbol、exchange、source、timeframe、OHLCV | Bar 的 symbol/market/provider/feed/timeframe/OHLCV；market 不是 exchange，exchange 的跨源显式映射仍需验证 |
| provider / exchange / ingest 时间、session、timezone、closed | source_timestamp / received_at / bar_start / bar_end / session / is_closed / is_complete；时区是 aware datetime，exchange timestamp 语义、节假日/DST 与 entitlement 不得由字段存在推断合格 |
| 权益、quality、source/deployed version | quality_flags / health，QOT 权益独立证据；export 带 repo_sha/runtime_instance_id/sequence；source version、entitlement 与部署指纹的跨源完整关联仍未统一验收 |
| D1 / 1H / 15m，5m / 1m 触发 | TickFlow 研究缓存有 1m/5m/15m/60m/1d；US canonical export 有 1m/5m/15m/1h，D1 走独立 daily history 路径，不能宣称已是统一五周期 schema |
| durable cache / event store / provenance | 现有原子快照、ledger 和 SQLite 组件可复用；全链路留存、correlation ID、提醒幂等和故障恢复仍须端到端验收 |

研究缓存可用、历史回放通过、心跳刷新、经过一个时钟边界，均不能证明交易时段数据新鲜或 K 线已闭合。有限价格、连续性、闭合、权限、来源或版本任一 UNKNOWN 时不得提升相关信号/执行权限。研究专用容差不授予实时 finality。

## 离线 CI：可执行契约入口

运行：

~~~bash
./scripts/ci_gate.sh system-contracts
~~~

该阶段复用既有 pytest 公共入口；不请求行情、模型或账单 API，不发送真实提醒，不更改订阅。CI 在 backend shard 1、完整离线分片之前强制执行；shell 任一失败返回非零，backend-gate 随之失败。完整离线套件仍保留。AGENTS.md 与本目录文档变更也必须触发 backend。

| 离线风险 / 覆盖路线 | 既有行为回归文件（tests/） |
| --- | --- |
| Bar/Quote、来源混合、缺分钟、未闭合与时间戳新鲜度 / A/B/C | test_market_data_adapter.py、test_market_data_quality_invariants.py、test_alpaca_data_quality_invariants.py |
| 五周期、finite/重复/未来时间、旧数据不能借心跳变新、研究容差不证明 finality / A | test_cn_tickflow_research_cache.py |
| forming→closed 写入边界、乱序/队列溢出、session/currentness / B | test_futu_k1m_streaming_adapter.py、test_futu_k1m_closure_pipeline.py、test_futu_k1m_currentness.py、test_futu_k1m_history.py、test_futu_research_aggregation_gates.py |
| 云端只读 cache 的安全字段、SHA/新鲜度与闭合证据 / B/F | test_us_canonical_runtime_reader.py |
| UNKNOWN 准入阻断、因果时间、订单幂等与 PIT/费用/滑点 / D | test_paper_execution_admission.py、test_closed_bar_paper_replay.py |
| 通知路由、去重标识、失败及脱敏 / C/F | test_stock_radar_v2_runtime_notifications.py |
| 外部观测与电脑关闭窗口，禁止自证、代次变化和证据不足 / C/G | test_cloud_runtime_evidence.py |
| 队列白名单、重试/检查点、停止与预算 / E | test_engineering_autonomy.py（禁止 workflow self-merge）、test_engineering_autonomy_loop.py、test_engineering_deepseek_budget.py |
| 账单缺失/非法/部分响应、估算不能冒充余额、通知失败回退 / G | test_provider_billing_renewal_watch.py |

此入口是回归集合，不是七路线全部目标的自动认证。只有 offline contracts PASS 可以从本阶段得出；主线 CI、部署、cloud-live、持续调度和 Discord 实际送达各自独立记录。新增功能的准入测试须补进同一入口，不通过删除失败用例或放宽数据校验换取绿色。

## 云端证据、阈值与晋级

每个验收记录至少包含 requirement ID、task ID、单一 owner、PASS/FAIL/BLOCKED/NOT_VERIFIED、UTC 与 JST 时间、观察区间、source/bar 时间及 age/closure、各阶段耗时、main/HEAD/deployed SHA、PR/确切 CI run URL、云端 run/correlation ID、脱敏日志和回滚方式。缺失证据不得填 PASS。

阈值必须在验收运行前记录其配置来源、单位、值、交易 session、采样窗口与标的覆盖；记录实测行情获取/分析/提醒耗时、数据延迟、成功率、费用及资源消耗。沿用代码已有的数据门限；不能把默认读缓存 TTL 当作整套系统 SLO。以下整体验收指标尚未校准，状态均为 NOT_VERIFIED：30m 调度抖动与成功率观察窗口、跨市场五周期数据 age/连续性指标、提醒送达时延/回执、恢复时间、每轮费用预算。不得临时编造 PASS 阈值或提前缩短到 15m/5m。

进入主线、生产部署、研究 Radar 准入、Paper 自动执行、真实交易是不同决定。保持 LIVE_TRADE=NO、RADAR_ADMISSION=BLOCKED、SOURCE_ARBITER_ADMISSION=BLOCKED、PAPER_AUTO_READY=NO；单独授权前不自动合并 AI 代码、不部署、不发生新增付费调用或真实订单。回滚本改动采用 revert，不需要数据/配置迁移。

## 已知状态快照与关键路径

以下是 2026-10-17 的审计快照，不是持续更新的状态服务。再次验收必须重取现况：

| 路线 | 快照状态及证据 | 下一项可验证结果 |
| --- | --- | --- |
| A | BLOCKED：05:16–05:17 UTC / 14:16–14:17 JST [只读云端审计 39005647057](https://github.com/kaku3030/stock-razor/actions/runs/39005647057) 观测到 BLOCKED_VALUE_ERROR；collector SHA 匹配 3ae2a01590f3104e0499ac97a885eb9acb4032bc。不是已证明 JSON 损坏。[#874](https://github.com/kaku3030/stock-razor/pull/874) 是尚未合并的 baseline/诊断修复 | 授权部署诊断后定位真实 ValueError；交易窗口重新验证五周期，不能凭本 PR 宣称恢复 |
| B | NOT_VERIFIED：[精确云端探测 39005674433](https://github.com/kaku3030/stock-razor/actions/runs/39005674433) 失败；runtime SHA c5e476ea742a1d64d1542c2350518185d57c41ba 与 main 不一致，闭合/实时交付未证实 | 授权部署后的 exact SHA + 盘前/盘中/盘后证据；动态订阅 preview→受控 runtime 仍有实现缺口 |
| C | NOT_VERIFIED：本地 Radar/通知测试不证明 AWS 30m 持续运行或 Discord 用户侧送达 | 记录已校准窗口内 scheduler run IDs、端到端提醒与独立 PC-off 观察 |
| D | NOT_VERIFIED：离线 PIT fixture 已有；最近 US research capture 因非有限 close fail-closed | 取得合格且可追踪的近两周数据；费用/滑点/PIT/OOS 可复现实验 |
| E/F | NOT_VERIFIED：[#873](https://github.com/kaku3030/stock-razor/pull/873) Feedback Hub preflight/租约审计尚未合并；队列测试不能证明持续 AI 编程或云端数据库可达 | 单一任务从反馈→修复→PR/CI→授权集成/部署→云端复验闭环；持久化 ingress 与 worker 进度证据 |
| G | NOT_VERIFIED（部分证据）：[账单监控 38858227886](https://github.com/kaku3030/stock-razor/actions/runs/38858227886) 记录 ALERT_DISPATCHED，仅证明应用 dispatch，非当前余额或用户侧收件；OpenAI 实际 prepaid 余额 UNKNOWN；AWS 付费 Cost Explorer 默认关闭 | 独立 liveness/stuck-task 与 stale-evidence 告警，续期/预算可追踪，最终通知回执单独验证 |

关键路径是 A/B 合格云端行情 → C 30m 调度/分析 → 可核验主动提醒与恢复。F 统一版本和证据，G 独立监督。D/E 的离线实验与保护机制可并行推进，不阻塞 P0。已提交 PR 或 CI 通过不能关闭实际云端故障。
