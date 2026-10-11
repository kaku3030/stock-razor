# STOCK RAZOR 云端三路并行主控计划 V0.1

**基线：** `main@2e1312ad452de92078d78fcd6f41c078aeb02150`（2026-10-11）

**范围：** TickFlow A 股资格、moomoo OpenD 美股动态订阅、US SIM 只读到受控 Paper 试验。

**当前硬门禁：** `PAPER_AUTO_READY=NO`、`RADAR_ADMISSION=BLOCKED`、`SOURCE_ARBITER_ADMISSION=BLOCKED`、`LIVE_TRADE=NO`。

## 结论先行

三路可以并行，但不能共享未验证的“已接入”结论：

- TickFlow 代码与隔离探针已存在；Premium/分钟连续性/历史完整性/跨源一致性仍未验证，正式主源保持关闭。
- AWS OpenD SIM 只读账户发现与四类 readback 已有一次真实云端证据；现有持仓仍需人工复核，OpenD 原生 SIM fills 不支持，Paper 仍阻断。
- OpenD 动态订阅已有 watch ownership、容量审查和 K1M runtime 接口，但审查器明确不发出 subscribe/unsubscribe；下一步必须先完成候选池和限额的只读观测，再评估同一既有 runtime 的受控变更。

## 三路工作包

| 优先级 | 工作包 / owner | 依赖 | 本日可执行范围 | 晋级前不可做 |
|---|---|---|---|---|
| P0 | **A 股 TickFlow 资格**：`data_provider` + `ops/aws` + 数据质量测试 owner | 付费计划、AWS Tokyo 访问、最小预算额度、凭据引用与 provider entitlement 证据 | 复核现有历史/跨源 harness、完善成本/请求计数和报告字段；无凭据时只跑离线测试 | 不得发送收费 REST/WS 请求；不得改 A 股正式路由或 Source Arbiter admission |
| P0 | **美股 OpenD 动态订阅**：既有 US LiveFeed/AI Monitor owner | 既有 OpenD runtime、US subtype quote-right、实际 quota、现有 5/9 流稳定性 | 扫描现有 watch snapshot、离线排序、预算/队列模拟、订阅状态与恢复契约审计 | 不得新建第二 OpenD；不得每次改 CODES 重部署；不得在权限/配额 UNKNOWN 时订阅变更 |
| P1 | **US SIM → Paper**：`src/services/paper_*` + `ops/aws-sim-*` owner | 唯一 ACTIVE US SIM、四项 readback、持仓人工复核、独立成交证据方案 | 只读复核、幂等/重启/撤单/断线测试、成交证据缺失时保持 BLOCKED | 未经单独明确授权不得下首笔模拟单；任何真实账户/真实订单均禁止 |

## 每日验收指标（按事实记录，不以“工作流成功”替代）

### A. TickFlow

每次观察记录 `source_sha`、请求数、响应数、限流/重试数、估算费用、缓存命中率、时间窗、时区和 `data_qualification`。满足以下全部条件才允许提交候选主源评审：

1. 历史回填覆盖目标标的、分钟/日线和明确窗口；缺口、重复、乱序、截断和 PIT 字段均有计数。
2. 至少一个交易时段内，WebSocket 连接、订阅 ACK、事件数、唯一事件、provider timestamp、接收时间、断线恢复和重连后的连续性分别有证据。
3. 与 Tencent/东方财富逐字段对齐；差异必须按时间、价格、成交量、复权、闭合状态分别报告，不能只报总体 PASS。
4. 费用、限流和预算均在预设硬上限内；任一成本或 entitlement 字段 UNKNOWN，结果为 `BLOCKED/NOT_VERIFIED`。

### B. OpenD 动态订阅

每日只读记录 watch snapshot 时间、候选数、优先级、现有订阅数、已验证 quota、剩余 quota、订阅状态、事件新鲜度、断线次数、恢复耗时和五/九只稳定流的变化。候选池、队列和限额审计通过后，才可在**同一既有 runtime**中做小范围人工批准的 add/remove；任何失败必须恢复到上一个已知订阅集合。

### C. US SIM / Paper

每日记录唯一 SIM 账户数量、balance/positions/orders/history 四项 readback、持仓人工复核状态、native fills 能力、订单状态完整性、幂等键、取消/重启/断线测试结果。`deal_list_query` 不支持或任何独立成交证据缺失时，成交结论必须是 `BLOCKED`；订单历史、持仓和现金变化最多是相关性证据，不能冒充 broker-native fill receipt。

## 合并与执行门禁

1. 代码必须从 exact `origin/main` 派生隔离分支；不得在脏的 canonical checkout 上切换、reset、stash 或覆盖。
2. 只读探针、离线 fixture 和测试可以先合并，但不会改变四个硬门禁，也不会自动启用付费源、OpenD 订阅或 Paper 下单。
3. TickFlow Premium 只有在预算、凭据引用、IAM、地域/网络、provider entitlement、限流、REST 历史质量、WS 连续性/恢复和跨源质量全部 `PASS` 后，才进入单独的 provider admission 评审；一次三根 K 线 Smoke 不足以通过。
4. OpenD 只有在 subtype quote-right、实际 quota、候选池、连接 owner、状态回读和恢复演练全部有证据后，才允许受控 add/remove；不得部署第二 runtime。
5. Paper 只有在持仓人工复核、账户/资金/订单/历史 fresh、独立成交证据、订单幂等、取消/恢复和 kill switch 全部通过后，才可请求**另一次明确授权**进行有限 SIM 下单。此文档本身不构成授权。
6. 任一主线 head 移动后，旧 CI、Radar、运行时 SHA 和 review 证据全部失效，必须重新绑定 exact SHA。

## 当前链接与证据边界

- 当前主线：[main@2e1312ad](https://github.com/kaku3030/stock-razor/commit/2e1312ad452de92078d78fcd6f41c078aeb02150)。
- AWS SIM 真实云端只读记录：[workflow run 38135716291](https://github.com/kaku3030/stock-razor/actions/runs/38135716291)；结果是四项 readback PASS、持仓需复核、native fills 不支持、Paper blocked。
- 现有 TickFlow 隔离/质量实现：[PR #480](https://github.com/kaku3030/stock-razor/pull/480)、[PR #519](https://github.com/kaku3030/stock-razor/pull/519)、[PR #520](https://github.com/kaku3030/stock-razor/pull/520)；这些不等于 Premium 云端资格通过。
- 现有 OpenD 订阅研究实现：[PR #483](https://github.com/kaku3030/stock-razor/pull/483)、[PR #485](https://github.com/kaku3030/stock-razor/pull/485)；它们是离线容量/ churn 审查，不是订阅变更授权。
- 用户指出的 [PR #71](https://github.com/kaku3030/stock-razor/pull/71) 仍为 `OPEN + DIRTY` 的旧 Minimal Core 研究 PR，不作为本计划依赖。

**状态声明：** 本计划只编排证据和最小改动，不部署、不购买、不发送 TickFlow 收费请求、不改变正式主源、不发起任何订单。
