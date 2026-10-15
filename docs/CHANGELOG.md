Warning: truncated output (original token count: 62955)
Total output lines: 2375

Total output lines: 400

# 变更记录

## 2026-09-14 — PR #120 governance incident record

- PR #120 已进入 `main`，但 merge authorization 没有被 durable evidence 证明。
- `PR120_MERGE_AUTHORIZATION = NOT_PROVEN`。
- `PRODUCTION_PROMOTION_AUTHORIZATION = NO`，直到 Production Owner 完成逐项 adjudication。
- Research harness、PIT/Replay/Holdout、Registry 和 capture 能力保留；未经批准的 production routing 与 runtime semantic changes 执行 selective restoration。
- Merged code 不构成 retrospective authorization。

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) page.

## [Unreleased]
- [修复] 允许 TickFlow 收盘后进度模式读取受限的同日供应商浮点证据，保持研究级、未确认闭合和交易门禁关闭
- [修复] OpenD canonical 快照区分发布心跳与最新行情源时间戳；运行时可持续推进只读快照序列，同时 MCP 仍按真实 K 线源时间判定新鲜度，避免缓存停滞或心跳刷新掩盖旧数据。
- [修复] TickFlow 暂时性网络超时按15至300秒有界退避恢复，成功后重置；鉴权、限流及数据错误仍保留300秒退避，周末900秒，失败缓存不冒充有效行情。
- [修复] Context Manager 使用跨进程写入锁避免事件版本冲突；显式恢复仅修正经校验的连续重复版本，先保留0600原始备份，不改变任何交易门禁。
- [改进] MCP 部署失败仅导出固定错误分类，用于定位事件日志完整性、序列、依赖或权限问题；原始 SSM 和安装输出仍不公开，失败继续阻断。
- [修复] OpenD 收盘末根分钟线仅以完整390分钟历史网格作受限补齐，保留历史来源和闭合未验证状态；失败最多30分钟后重试一次。
- [修复] Paper 现金预留按意图隔离，模拟成交批次先校验身份、限价、资金及持仓再记账，覆盖重启与部分成交回归。
- [改进] Paper 半小时调度审计须具备48个独立配置时段，仅报告配置状态，实际调度执行仍需运行证据。
- [性能] TickFlow AWS研究Worker盘中最小轮询间隔降至15秒；按每周期8次K线请求计算，单Worker上限约32次/分钟，失败与非交易时段退避保持不变，账号共享额度仍待核验。
- [修复] OpenD 聚合K线仅在全部源分钟成交额完整且推导VWAP位于该K线价格区间内时发布VWAP；越界或部分成交额均降级并阻断信号。
- [改进] TickFlow 历史缓存拒收增加固定枚举诊断；AWS 审计仅导出白名单原因，不暴露行情值且维持 fail-closed。
- [监控] AWS TickFlow 两ETF 5m/15m/60m SSM+MCP 每整点/半点只读审计，Windows 本地独立半小时凭据安全取数；仅公开脱敏状态，不开放交易准入。
- [修复] 云端到期提醒 Discord/Telegram 请求添加应用身份 User-Agent，Telegram 拒绝仅输出预定义 HTTP 状态码，避免混淆配置失效与网络阻断。
- [修复] Discord 两路 Webhook 均发生 HTTP 403 时才使用已配置 Telegram 用户聊天凭据发送一次安全费用提醒；两路均失败仍返回红灯，不扩大交易/云端权限。
- [修复] 费用/续费通知增加已配置的标准 Discord Webhook 单次回退，并在云端保留不含敏感信息的 HTTP 失败状态码供排障。
- [修复] 云端供应商费用提醒发送失败时仅输出离散错误分类，不泄露 Webhook/API 错误正文，保留通知失败时的 CI 红灯。
- [新功能] 云端 OpenAI API 成本/token 使用量及 TickFlow 月费到期安全提醒（只读 Admin API、Discord、余额非真实值明确标注）；OpenD 免费不监控。
- [研究数据] TickFlow 5m 盘中微小 OHLC vendor float（<=1e-5，ETF tick-grid 一致）仅保留原值用于受限研究；5m 全部到期K线逐一校验，缺口和大误差仍拒绝，交易门禁不变。
- [修复] TickFlow盘中MCP读取不再因最新到期时间戳存在而掩盖同日中间缺失K线；读取前完整检查受限缓存，即使 limit=1 也拒绝未验证的历史污染，仍保持研究数据与交易门禁隔离。
- [改进] 现有 ChatGPT A股 MCP 明确新增 `TICKFLOW:PROGRESS:<ETF>` 只读盘中到期网格研究入口（5m/15m/60m），不依赖新增连接工具；严格与历史研究、默认腾讯/东方财富、交易所最终闭合及交易权限隔离。
- [性能] TickFlow云端新增 `TICKFLOW:FULL` 一次MCP调用返回两ETF各5m/15m/60m/D1历史研究数据，统一源版本对齐，任何周期失效均整组拒绝，无交易权限晋级。
- [改进] TickFlow 云端隔离研究缓存补齐受限5m（48根/完整交易日）及1d日期K线，保持两ETF白名单、无下单权限、未知闭合、日线仅历史研究；原有15m/60m调用兼容不变。
- [测试] 增加 AWS OpenD 原生已订阅 K线深度与速度的有界只读验收（至2000请求，最多65次），并严格区分 native、Radar缓存、ChatGPT MCP 与报告生成耗时。
- [修复] 现有 CN TickFlow 研究服务允许仅在东京固定 Ubuntu EC2 实例上经 SSM 已在线、研究服务已运行、部署工作树干净且美股 LiveFeed/MCP 运行正常的独立验证后更新；其他 Ubuntu 实例、交易准入及默认 dry-run 保持阻断。
- [性能] 云端 TickFlow 新增 `TICKFLOW:FAST` 精简行情快照，利用已连接的 `get_cn_market_data` 一次返回 2 ETF×(15m,60m) 最近一根原生 OHLCV、K线质量与缓存同源版本，并返回 AWS 本地读耗时；不要求新增 MCP 安装、不修改原始行情、交易门禁不变。
- [修复] TickFlow 当日盘后（15:02 上海时间后）仅在原始 ETF 价格全部贴合最小跳动、OHLC 偏差不超过 1e-5 时保留微小浮点误差的历史研究 K 线，保持原始价、不证明终态，盘中与 Session Progress 仍严格阻断。
- [改进] 云端 ChatGPT 已连接 MCP 的 `TICKFLOW:BATCH` 显式只读别名可一次获取两只 ETF 的 15m/60m 四组历史研究 K 线，严格要求缓存 SHA/sequence 同源；不改变普通行情路径、数据最终闭合、Radar 或交易门禁。
- [改进] ChatGPT 现有 `get_cn_market_data` 只读工具支持显式 `TICKFLOW:159611.SZ` / `TICKFLOW:518880.SH` 前缀，读取 AWS 原生 TickFlow 15m/60m 历史研究缓存；普通行情路径、最终闭合和全部交易门禁均不变。
- [改进] 为 CN Worker/TickFlow 增加显式目标、默认 dry-run、SSM 身份预检、受控回滚和独立版本/来源读回的安全部署入口

- [修复] 研究 EOD 定时采集要求完整 universe 与独立 A/US 样本验证，缺失或供应商非有限 OHLCV 时整条工作流 fail-closed，仍保留失败 manifest 与 artifact；不混淆研究采集与 OpenD/交易准入。

- [修复] TickFlow 官方绝对 1e-5 OHLC 浮点精度容差仅在研究缓存与只读消费者中双重校验，保留原始价格及异常标记；超限仍拒绝，K 线终态、数据源/雷达/Paper/实盘门禁不变。

- [改进] 受限只读 MCP/Context Manager 代码变更合入受保护 main 时，沿用仓库 Owner、OIDC、固定 AWS 目标与精确 SHA 校验自动触发云端只读服务部署；无关 PR 不触发服务重启，失败继续阻断。

- [改进] 美股 AWS exact-main 云端只读验收探针增加 GitHub Owner 专属 PR 指令入口，可在个人电脑关机时独立观察行情序列/时间新鲜度及闭合；旧云端 SHA、无 D1、MCP 未认证仍严格阻断验收与交易。

- [测试] TickFlow 历史 OHLC 硬拒绝新增官方绝对 1e-5 精度差异的有限枚举审计，不打印价格或原始异常、不修正报价、不解除任何数据源与交易准入。

- [改进] Paper AWS 只读 SIM 账户验收增加经 GitHub 仓库 Owner 严格授权的固定 PR 指令入口；仅在 latest main + OIDC + 固定 EC2 上查询模拟账户，不读取 REAL 账户或调用下单，不解锁 Paper 和 Radar。

- [修复] Context Manager 对所有非成功 CI 结论 fail-closed；区分 PR-head CI 与 main 验收，标记最近已记录的 PR 合并与部署 SHA 不一致。

- [修复] AWS OpenD/MCP 只读 SSM 失败时仅脱敏回传固定阶段状态码，保留失败退出码，隐藏原始 stdout、stderr、账户和密钥；探针诊断不构成行情或交易准入。

- [运维] 在受保护 main 的 AWS SSM 只读路由更新后，由 GitHub 云端自主派发唯一固定 `us_livefeed_status` 脱敏数据探针；仅标记已派发、不把工作流成功当作行情闭合或交易准入，不依赖用户电脑持续开机。

- [修复] AWS US LiveFeed SSM 只读状态探针改为单条有界脱敏元数据（心跳、QOT_RIGHT、时间周期 K 线数量及结束时间），不再被大型原始服务日志或 SSM stdout 截断遮蔽；仍为研究状态、不解锁数据源或交易。

- [改进] Context Manager 新增按 CI、PR、部署、Radar、阻塞和优先事项分域的可恢复快照，并通过 owner/OIDC/固定 SSM/exact-main 守卫自动接收合并 PR 与 main CI 完成事件；恢复入口明确保留 provenance、TTL、未验收和关闭状态，不改变交易门禁。
- [修复] AWS OpenD SSM 只读探针日志采用有限状态枚举、严格时间戳与行情周期白名单；隐藏私有路径、端点、任意数值及成交数据，脱敏成功不等于实时行情准入。

- [新功能] 新增可持续 Context Manager MVP：工程、部署、CI 与 Radar 事件可通过统一 append-only JSONL 记录，当前状态原子落盘并带版本、时间戳、来源、TTL、幂等与凭据过滤；现有只读 MCP 新增 `get_context_manager_state` 恢复入口，失效、损坏和失败状态保持阻断，不改变交易权限。
- [修复] TickFlow云端只读审计并发锁从工作流级移到授权后的job级，防止无权限GitHub评论替换已排队的Owner验收请求。
- [修复] Paper SIM 私有回读将超过 JSON 解析嵌套深度的结构归类为 PRIVATE_SCHEMA_INVALID；语法错误继续归类为 PRIVATE_INPUT_INVALID，严格脱敏与禁交易不变。

- [改进] GitHub仓库Owner可用固定PR精确评论触发TickFlow AWS只读历史/分钟行情质量复验，无需个人电脑；双重Owner与最新main核验，交易门禁保持关闭。

- [chore] Trigger protected AWS TickFlow read-only research re-audit after scoped main-branch audit changes without paid ingestion or trading changes.

- [修复] AWS 只读 MCP 手动部署新增仓库 Owner 与最新 main SHA 双阶段守卫、固定安装脚本校验和、禁止原始远端安装日志外泄；不自动部署或解锁交易门禁。

- [改进] 云端 MCP 既有 `get_market_analysis` 接口支持精确只读 Cloud Ops 兼容参数，不需新增 ChatGPT 客户端工具；其他美股分析与所有交易门禁保持不变，必须经 AWS 实际部署后验收。

- [改进] 在冻结的 ChatGPT STOCK RAZOR 工具清单中通过原有 `get_cn_market_analysis(symbols=["__QUICK_SCAN__"])` 复用已部署的 CN 单次紧凑研究快报，无需更新应用工具目录；普通符号调用保持旧语义、所有交易门禁不变。
- [test] Independently cross-check historical Eastmoney and qualified Tencent Kline clock grids/price values on AWS without source promotion.

- [chore] Run the existing cloud-only TickFlow research acceptance audit on weekday Shanghai market sessions; keep all source, Radar and trading gates closed.

- [修复] 修正 CN Quick Scan AWS SSM 审计使用 dash 不支持的 `set -o pipefail` 导致返回码 2；改为 POSIX `set -eu`，并增加回归契约检查。

- [测试] AWS SSM Ops 增加有界只读 CN Quick Scan 云端验收入口：核对实际部署 SHA、MCP 工具注册、研究输出与服务端缓存读取耗时，输出白名单遥测，保持行情与交易安全门禁不变。
- [改进] AWS 只读审计新增部署中的 MCP 服务状态、Git SHA 与 Cloud Ops 工具源码声明检查；明确协议可调用性仍未验收，不访问凭据、不执行维护命令。

- [修复] AWS 只读心跳审计及 Cloud Ops 健康检查按单个缓存读取完成时间判断，避免高频 US Radar 心跳虚假时钟回拨；实际时间回拨仍阻断。

- [改进] GitHub 仓库 Owner 可通过固定 PR 的精确评论命令触发原有 AWS 只读 SSM 审计；执行前双重身份检查与 main SHA 校验，禁止任意命令、实盘及变更权限，不新增定时任务或 IAM 权限。

- [修复] AWS 只读云端运行审计在申请 OIDC 权限前及发送 SSM 命令前两次校验 main 当前 SHA，拒绝过期任务，不读取密钥、不改服务或交易门禁。

- [新功能] 现有只读 MCP 新增固定四项 AWS EC2 本机 systemd/心跳健康查看入口，使用严格安全字段白名单；不执行 AWS API、SSM 命令、服务重启或交易，ChatGPT 远程管理权限仍待独立授权。

- [chore] 统一 STOCK RAZOR 常规工程的零人工审批执行规则：按最新主分支与必需自动化 CI 门禁通过后推进 PR 合并，取消对逐次用户批准、Code Owner 签字、人工 reviewer/ACK 的隐式依赖，保持生产行情与交易安全准入独立阻断。

- [改进] 选股接口新增 `cache_only` 研究模式：只读取现有快照缓存，缓存缺失或超过有效期时 fail-closed，不访问外部行情源；结果明确标记为 research-only、需要实时候选确认且不可直接确认信号。数据库/CNEquity 不参与该路径。

- [新功能] 新增只读运行控制台 `/operations` 与 `GET /api/v1/operations/status`，集中展示 Radar/Source Arbiter、通知渠道、Paper Auto 与 LIVE_TRADE 门禁；接口不能解锁真实交易，手机接收、TickFlow 实盘连续性和 Paper 独立验收仍保持待验收。

- [改进] AWS TickFlow 隔离探针新增 `premium-contract` fail-closed 合约检查；仅审计凭据引用、IAM、供应商授权、区域/并发、WebSocket、额度和数据资格门禁，不读取 secrets、不发起 Premium 请求，并保持 Radar/交易阻断。

- [修复] AWS Source Arbiter Shadow 审计允许已存在的 READ_SURFACE_NOT_FRESH_UNQUALIFIED 诊断标签，防止 US Radar expected-source 重新绑定后将正常 fail-closed 状态误报为云端执行失败。

- [诊断] US AWS Shadow 只读比对 LiveFeed、Canonical、Radar expected-source 的 commit/runtime 身份，区分生产源不一致与 Radar 旧版本 pin；仅输出布尔值并保持所有准入阻断。

- [修复] Cloud Fast Path 缓存重复读取不再将同一笔 Provider/Radar 历史耗时伪装为 30 次独立事件的 P50/P95/P99，同时补充 Futu 实际市场时段识别与一次性缓存遥测标注。

- [改进] AWS US Cloud Shadow 只读双采样增加 Canonical↔Radar 缓存序列证据、runtime identity 连续性与重复轮询识别，保持 Radar increment、Source Qualification 及交易权限未验证/阻断。

- [修复] AWS US Cloud OpenD Shadow 审计复用真实 Futu 交易时段枚举，区分服务心跳、Canonical 导出状态与过期缓存；诊断保持 UNKNOWN/BLOCKED、只读和零交易权限。

- [修复] US OpenD persistent livefeed 通过现有 RuntimeBridge 记录 controller 接收事件，修复 heartbeat 的 event_count 与 last_push_utc 不更新问题；保持 UNKNOWN/BLOCKED/NO 保护边界。
- [修复] Eastmoney 只读适配器的仅结束时间查询改用有界 history_n，避免空 StartTime 导致 Daily 数据查询失败。

- [修复] 独立 RS Breakout 验证器改为下一交易日开盘执行决策日收盘信号，避免使用同一根 K 线收盘价造成执行时序高估。

- [改进] 独立 RS Breakout 验证器支持 `--round-trip-cost-bps` 成本压力测试，同时输出 gross/net 收益与胜率指标，并在 guard 中记录成本假设。

- [测试] Research Universe Capture 工作流新增 100/150/200 bps 往返成本压力场景，生成独立 JSON 证据文件，不改变默认 Research-only 与 Holdout 保护边界。

- [修复] RS Breakout 验证器对 capture 内混合 symbol 与无可执行观察窗口执行 fail-closed，避免生成可误读的空结果。

- [修复] capture 输入进一步校验完整 OHLC 几何关系与非空 symbol，异常行情在进入回测前直接拒绝。

- [测试] 每日 Research Universe Capture 增加 +1 bar / +2 bar 执行延迟压力场景，与 100/150/200 bps 成本矩阵组合输出独立证据。

- [新功能] 新增独立 RS Breakout 研究回测入口：只读消费已记录 capture，校验 manifest hash/PIT 边界，输出五类反事实与 development/validation/Never-Seen Holdout 分段证据；不接入生产 routing，不消费 Holdout。

- [测试] Radar Rule Validation Harness 完成 Day 3–7 合成 fixture 工程闭环：冻结 ResearchDatasetCapsule（source/adapter/event hash/causal timestamps）、匹配 reservation 才能进入既有 OOS Ledger、五类 counterfactual 计划确定性执行，并新增从 RS-breakout 合成 fixture 到 OOS BURNED 的端到端测试；明确无获批 EOD OHLCV CSV 时只能作为 synthetic-fixture validation，真实数据 OOS 与 Promotion 仍阻断。
- [新功能] Radar Rule Validation Harness V0.1 增加持久化 Experiment Registry 与原子预算 reservation：按 rule family 冻结首见 budget policy，SQLite `BEGIN IMMEDIATE` 内重读已用量、执行 PIT/contract preflight、检查并写入不可变 reservation；operation_id 严格幂等、experiment_id 不可重复注册、超预算或 preflight 失败零持久化副作用，且该 Registry 不读取或修改 Never-Seen Holdout，OOS Consumption Ledger 继续是唯一权威。
- [新功能] Radar Rule Validation Harness V0.1 新增研究专用合同与 fail-closed preflight：把规则、数据分割、PIT policy、实验预算和五类 counterfactual 计划冻结为可绑定 `ExperimentManifest` 的确定性指纹；PIT `UNKNOWN`/晚到、缺失/冲突绑定或任一预算维度超限均阻断 Never-Seen Holdout claim 资格；纯 preflight 的用量输入只是 snapshot，执行级原子 reservation 由持久化 Registry 提供。
- [新功能] 项目正式命名为 Stock Razor，并以兼容方式引入 Radar、Realtime Monitor、Shared、Strategy Lab 与 Infra 顶层边界；纳入已验证的 Moomoo MCP 盯盘候选，账户与运行状态改由本地环境管理。
- [新功能] Strategy Lab V0.1 新增 Parameter Drift——正式概念名为 **Parameter Selection Identity Drift**（文件/模块名保持 `parameter_drift.py`）：度量跨 fold 的**所选参数集合身份**变化，仅消费不透明 `selected_parameter_hash` 证据。刻意不度量参数距离、数值 delta、方向、per-field 漂移、类别距离或归一化移动——仓库不存在参数 payload/schema/search-space 契约，任何数值距离都是伪精度。公开 API `evaluate_parameter_drift(walk_forward_report, fold_parameter_selection_evidence=(), fixed_parameter_evidence=None)`：`WalkForwardValidationReport` 不保留 hash，故证据必须单独供应，且模块**诚实声明**无法证明该证据就是原 `validate_walk_forward` 调用所用（仅按 fold_id 域 / 资格 / canonical 序绑定，swap 不可检测）。结构误用（报告内重复 fold_id、证据重复/未知 fold_id、模式不兼容证据）一律 `ValueError`，绝不折入 resolution。模式契约：`FIXED` → `NOT_APPLICABLE`，全部 drift 指标 `None`、observations/transitions 为空、仅暴露 `fixed_parameter_hash` 作上下文——绝不伪造 `unique=1/transition=0` 的零漂移测量；`TRAIN_ONLY`/`TRAIN_VALIDATION` 共用同一套身份漂移逻辑（不接受 fixed evidence）。冻结 gap 语义：仅 `VALID` fold 贡献身份；非 VALID fold 不破连续性但计入每条 transition 的 `skipped_non_valid_fold_count`；VALID 缺证据**打断**连续性（不生成跨 gap transition，stable-run 重置）。五个冻结指标：`transition_opportunity_count`/`transition_count`（恒 int）、`transition_rate`（opportunity=0 时为 None，绝不用 0.0）、`unique_parameter_hash_count`（跨 segment）、`longest_observed_stable_run`（0 observed=None，单观测=1）；**无** revisit_count/drift_score/severity label/归一化 unique。Resolution 优先级冻结：FIXED → NOT_APPLICABLE；any VALID missing → INCOMPLETE_EVIDENCE；observed<2 → INSUFFICIENT_DATA；否则 RESOLVED（missing 先于 insufficient——完整性缺口优先于观测不足）。四个 finding 码（`FIXED_MODE_NOT_APPLICABLE` 报告级、`VALID_FOLD_SELECTION_EVIDENCE_MISSING`/`NON_VALID_SELECTION_EVIDENCE_IGNORED` per-fold、`INSUFFICIENT_OBSERVED_SELECTIONS` 报告级）按 `(code.value, fold_id or "", message)` 确定性排序、无 severity。纯计算叶子节点：仅 stdlib + 封闭 Walk-Forward 类型，无 storage/repositories/SQLAlchemy/OOS ledger，无 `parameter_stability.py` 算法依赖（参数稳定性=标量邻域鲁棒性，是另一回事）。防御性 canonical 排序 `(oos.start, train.start, fold_id)`，证据按 fold_id 映射后迭代 canonical fold，与输入序无关。永久对抗测试 34 项覆盖 FIXED 全 None、结构误用、shuffle 不变性、分母不变量、gap/continuity 各形态、指标确定性、finding 排序、无 score/label/revisit 字段、无 persistence import（AST 级）、信任边界文档化与 swap-不可检测行为钉住。
- [修复] OOS Consumption Ledger 聚焦修复第二轮（5 项冻结语义修订）：(1) **覆盖图校验先于任何写入**——任何 Ledger 写操作在 mutate 前必须构造"已持久化身份注册表 + target-reachable 候选定义"的暂态覆盖图并整体验证：不得引入 self-parent、谱系环、根不变量破坏或 child/root 不匹配；已知结构矛盾直接整体拒绝并回滚（无 identity、无 event、不预留 operation_id），两个各自 INDETERMINATE 的 burn 绝不因局部评估而合成永久环；INDETERMINATE burn 仅允许"缺失祖先"（有效但截断的 target→ancestor 链），不允许已知矛盾。(2) **写优先级冻结**：idempotency 定位（不裁决）→ 全量 supplied manifest 集对持久化注册表的 identity 冲突检查（硬 `OOSLedgerIdentityConflictError`，绝不被 self-parent/cycle/resolver 截断/幂等重放掩盖）→ 覆盖图结构校验 → 才裁决幂等重放/冲突 → lineage 审计 → claim 资格/暴露逻辑。(3) **幂等重放必须通过完整校验**——`IDEMPOTENT_REPLAY` 仅在入站命令通过 identity + 结构校验后且语义指纹精确匹配时返回；结构非法的变更重放按 identity/lineage 完整性错误失败，绝不返回 replay；指纹仍在校验后对合法 reachable 集合生成。(4) **迁移严格校验**——`_ensure_oos_consumption_ledger_schema()` 按精确冻结契约校验真实 SQLite 元数据：必填列 + 必填 NOT NULL、identity `id` INTEGER 主键、events `event_id INTEGER PRIMARY KEY AUTOINCREMENT`（查真实 DDL）、`experiment_id`/`operation_id` 必须各自有**专用单列且非 partial 的 UNIQUE**（复合 UNIQUE 或 `WHERE` 部分唯一索引不达标）、时间列 TEXT-affine；任一不达标 fail-closed 且**不**写入 `DatabaseSchemaMigration` 版本记录。(5) **确定性锁竞争回归测试**——独立连接持 `BEGIN IMMEDIATE`，两 worker 在进入 Ledger 写前置 started 事件，持锁期间断言两 done 均未置位（无竞争时毫秒级完成，未完成即证明阻塞于真实 SQLite 写锁），释放后恰一 CLAIMED、一 ALREADY_EXPOSED、一事件。新增图完整性回归套件：图可单调扩展且永不成环、持久化节点定义不可 mutation、晚注册不可引入环、无关节点不可毒化图、任何写不得把先前合法的持久化图变为已知非法。全程不改整体窗口重叠语义、半开相邻、BEGIN IMMEDIATE 架构、append-only 事件源、持久化图查询模型、canonical UTC TEXT、aware 边界、PRISTINE→BURNED 直跳、重复 claim 拒绝、被拒操作不预留 operation_id 与无 reset API。
- [修复] OOS Consumption Ledger 聚焦修复第一轮（9 项冻结语义修订）：(1) **仅 target-reachable 谱系节点**可被注册/指纹化/用于继承——从 target 沿 `parent_experiment_id` 向 root 追踪，同一路径外的 co-supplied 节点被完全忽略，绝不进入身份注册表、绝不参与 `lineage_binding_fingerprint`、绝不影响评估；reachable 链本身含 self-parent/cycle/冲突重复定义/根不变量破坏时判为谱系违规并拒绝写入。(2) **被拒 claim 零持久化副作用**——`LINEAGE_INDETERMINATE`/`LINEAGE_VIOLATION`/`ALREADY_EXPOSED` 不产生 event、不新增 identity 行、不保留 operation_id；PASS claim 的注册与事件仍原子，若注册后 overlap 判 ALREADY_EXPOSED，整个事务回滚（临时 identity 不残留）。(3) **claim 门禁优先级**冻结：identity 冲突=硬完整性错误；lineage VIOLATION→`LINEAGE_VIOLATION`、INDETERMINATE→`LINEAGE_INDETERMINATE` 均先于暴露评估；只有 PASS + 持久化图 RESOLVED 才进入 PRISTINE vs ALREADY_EXPOSED 判定——不完整谱系 + 自身已有 OUTCOME_USED 也只报 `INDETERMINATE + state=None`，绝不伪报 ALREADY_EXPOSED/PRISTINE。(4) **谱系规范化**：仅 target-reachable 集合、精确重复折叠、按 experiment_id 排序；fingerprint 对输入顺序/精确重复/unrelated 节点不变；reachable 冲突重复定义 → 拒绝（违规），绝不静默去重。(5) **真 AUTOINCREMENT**：事件表改用表级 `sqlite_autoincrement=True`，SQLite DDL 真正输出 `INTEGER PRIMARY KEY AUTOINCREMENT`，新增 sqlite_master DDL 断言测试（identity 表维持普通 INTEGER PRIMARY KEY 即可，其 id 不承担权威排序职责）。(6) **迁移 fail-closed**：`_ensure_oos_consumption_ledger_schema()` 现会检查实际存在的 Ledger 表（必填列、`experiment_id`/`operation_id` DB 级 UNIQUE、event_id 主键 + AUTOINCREMENT、时间列 TEXT-affine），畸形/残缺表直接 `RuntimeError` 且**不**写入 `DatabaseSchemaMigration` 版本记录（确保顺序调整为 Ledger 校验先于版本盖章）；新增"预置畸形表 → 初始化失败 → 版本未盖章"测试。(7) **被拒操作不预留 operation_id**：幂等语义只覆盖已持久化的状态变更事件；被拒 claim 重试时按当前 Ledger 状态重新评估（可能产生不同结果），不引入 operation-attempt 表。(8) **并发测试强化**：主线程持 `BEGIN IMMEDIATE` 写锁 + 两个 barrier 同步的 worker 必须阻塞在锁上（断言持锁期间 worker 仍存活），释放后恰好一个 CLAIMED、一个 ALREADY_EXPOSED、仅一条事件。(9) **崩溃持久化测试强化**：claim 提交后 `DatabaseManager.reset_instance()` + 重新打开同一 SQLite 文件，`get_assessment` 仍返回 CONSUMED。全程不改整体窗口重叠语义、半开相邻、BEGIN IMMEDIATE 架构、append-only 事件源、持久化图查询模型、canonical UTC TEXT、aware 边界、PRISTINE→BURNED 直跳、重复 claim 拒绝与无 reset API。
- [新功能] Strategy Lab V0.1 新增 OOS Consumption Ledger——Strategy Lab 第一个持久化模块，由纯计算 domain 层（`src/services/strategy_lab/oos_consumption.py`）与 SQLAlchemy/SQLite 持久层（`src/repositories/oos_consumption_ledger_repo.py`，两张新 ORM 表 `oos_experiment_identity_records`/`oos_consumption_event_records` 定义在 `src/storage.py`）组成。消费状态为冻结单调序 `PRISTINE < CONSUMED < BURNED`，PRISTINE 从不物化为 current-state 行——"无合格暴露事件"本身就是 PRISTINE；`CLAIMED_FOR_EVALUATION` 至少推为 CONSUMED、`OUTCOME_USED` 推为 BURNED，允许 PRISTINE 直跳 BURNED（已知污染不得因缺少 claim 日志而拒绝记录），禁止任何降级，公开 API 无 reset/delete/unconsume/unburn。消费状态与 `OOSConsumptionResolution`（`RESOLVED`/`INDETERMINATE`/`CONFLICT`）分离：谱系不完整只给 `INDETERMINATE + state=None`，绝不伪报 PRISTINE。官方 claim 资格以整个 requested OOS 区间为单位（半开区间相邻不重叠）：任一重叠 BURNED 暴露 → 整窗 BURNED；否则任一重叠 CONSUMED → 整窗 CONSUMED；否则 PRISTINE；无 per-segment claim eligibility（未来 per-segment 诊断只能是非权威视图），防 window-padding/subset/superset/sliding-window/resegmentation 洗白。重复 claim 已暴露区间返回 `ALREADY_EXPOSED` 而非自动 burn；claim-before-evaluate 强制，已提交的 claim 在评估崩溃后依然 CONSUMED。Ledger 自行调用 `audit_experiment_lineage` 并固定 `history_complete=False`，绝不接受 caller 自报 verdict：PASS+PRISTINE 才允许 claim；INDETERMINATE 拒绝 claim（abstain）；VIOLATION 拒绝 claim 与 burn；但 `mark_outcome_used` 在 INDETERMINATE 下若 target 身份本身无歧义仍允许记录真实污染——缺失祖先绝不伪造，晚注册的祖先可使已持久化图 INDETERMINATE→PASS，任何 mutation 都不得降级。不可变 first-seen 身份注册表（`experiment_id` DB 级 UNIQUE）将每个 experiment_id 永久绑定到唯一 `manifest_hash`/`parent`/`root`，矛盾即 `OOSLedgerIdentityConflictError`（绝非"新版本"）；查询只接受 `experiment_id` 并仅从持久化图推导 self+ancestors，caller 无法靠省略祖先让既有暴露消失。所有写操作经 `DatabaseManager._run_write_transaction`（SQLite `BEGIN IMMEDIATE` + 锁重试），operation 幂等裁决、identity register-or-verify、lineage 审计、overlap 检查与 event 插入同一原子临界区——两个并发重叠 claim 只会一个 `CLAIMED`、一个 `ALREADY_EXPOSED`，绝无 CLAIMED+CLAIMED。`operation_id` 全局 UNIQUE 且绑定语义指纹（schema tag、event kind、experiment 身份、区间、declared 时间、lineage-binding 摘要——刻意不含 operation_id 本身）：同 id 同指纹 → `IDEMPOTENT_REPLAY`，同 id 异指纹 → `OOSLedgerIdempotencyConflictError`。`event_id` INTEGER AUTOINCREMENT 为持久化权威排序，`recorded_at` 仅诊断，`declared_occurred_at` 为 caller claim 且不要求 `recorded_at >= declared_occurred_at`。Ledger 是仓库持久化约定的刻意例外：所有时间列存 canonical UTC TEXT（不复用仓库 UTC-naive DateTime 惯例），读取一律恢复 aware UTC datetime。schema 迁移沿用既有 `create_all` + `_ensure_oos_consumption_ledger_schema()` + `DatabaseSchemaMigration` 记录机制（`CURRENT_SCHEMA_VERSION` 升级为 `2026-09-07-oos-consumption-ledger-v0.1`），不引入 Alembic。永久对抗测试覆盖：单调序、无 reset 公共面、claim-before-evaluate、claim 提交后崩溃仍 CONSUMED、失败 claim 交易回滚后仍 PRISTINE、幂等重放与异载荷冲突、identity 三字段冲突、祖先 CONSUMED/BURNED 继承、查询不可省略祖先、INDETERMINATE/VIOLATION 禁 claim、部分重叠/子集/超集/padding 不可重置、相邻半开区间独立、PRISTINE 直跳 BURNED、重复 claim 拒绝不 burn、**真实临时 SQLite 文件**上的并发重叠 claim 单胜、identity 注册+claim 原子回滚、UTC TEXT 落库与 aware 往返、事件写序无关、INDETERMINATE burn 不伪造祖先、晚注册祖先解析不完备图、注册表不可 mutation 降级。
- [修复] Walk-Forward Core Foundation 聚焦修复第一轮：(1) warmup 的 grid 校验现区分两种可构造场景——feature set 为 `DECLARED` 时比对 `evaluation_bar_grid_id`，feature set 为 `NOT_APPLICABLE` 而正向 warmup 完全由 `DECLARED` `COLD_START` state 提供时改为比对 `state.payload.bar_grid_id`（该字段在 convergence_warmup_bars 为正时本就是闭合 `StateDependency` 契约的必填项，绝非新造）；此前只在 feature set 为 `DECLARED` 时才做 grid 比对，state-only warmup 场景会被静默放行。(2) 四类此前会直接 `raise ValueError` 中止校验的场景现改为可审计 finding 并继续返回完整报告、绝不中止——`manifest.experiment_id` 与 `lineage_audit.experiment_id` 不一致记为新增 `EXPERIMENT_IDENTITY_MISMATCH`，`FIXED` 模式缺少 `parameter_origin`/`fixed_parameter_evidence` 分别记为新增 `PARAMETER_ORIGIN_REQUIRED`/`FIXED_EVIDENCE_REQUIRED`，`FIXED` 模式携带非空 `fold_parameter_selection_evidence` 记为新增 `FORBIDDEN_FOLD_SELECTION_EVIDENCE_UNDER_FIXED`；四者均为 `INVALID` 且以 `fold_id=None` 写入 `report_findings` 的同时逐字复制到每个 fold 自身的 findings（与既有实验级 finding 广播机制一致），`ValueError` 现只保留给真正的类型错误、负数、bool 冒充 int、naive datetime 与不可能的 dataclass 不变量这类调用契约层面的编程错误。(3) `FIXED` 模式且 fold 集合为空时，parameter hash 一致性与 `PRIOR_EXPERIMENT` 自引用检查依然照常执行（二者不依赖任何 fold 数据），但依赖 `min(fold.train_interval.start)` 的 `information_horizon_end`/`declared_at` 边界检查会被跳过而不是编造一个不存在的边界；`total_fold_count` 恒为 `0`。(4) 修复无 validation 分裂的 fold 若其证据仍携带 `applied_train_to_validation_purge_bars`/`usable_validation_bars` 非 `None` 值会被静默忽略的缺陷——现两者均记为 `INVALID_FOLD_GEOMETRY`，因为该 fold 根本不存在 train-to-validation 边界可供这些字段描述。(5) 同一未知 fold_id 在同一证据集合中出现多次时，现只产生一条 `EVIDENCE_FOLD_ID_UNKNOWN`（按不同 id 去重）而非每条证据各一条。测试新增/更新覆盖以上全部行为，并将输入 fold 顺序与证据顺序不变性回归断言扩展到 `report_findings`/`performance_eligible_fold_ids`/四类计数属性，不再只比较 `fold_results`。
- [新功能] Strategy Lab V0.1 新增 Walk-Forward Core Foundation（`WalkForwardFold`/`FixedParameterEvidence`/`FoldParameterSelectionEvidence`/`FoldSeparationEvidence`/`FoldDataEvidence`/`UniverseIntegrityRequirement`/`FoldUniverseIntegrityEvidence`/`WalkForwardFinding`/`FoldValidationResult`/`WalkForwardValidationReport`，三个治理指纹函数 `compute_window_configuration_fingerprint`/`compute_contamination_policy_fingerprint`/`compute_evaluation_protocol_fingerprint`，以及入口 `validate_walk_forward`），校验调用方声明的 fold 几何、参数provenance、因果分离证据、information-dependency 义务、lineage 证据与 PIT universe 证据是否结构自洽到足以构成 OOS 证据；回答的是“这套 walk-forward 设置是否足够结构自洽以被信任”，而不是“这个策略是否盈利”——不计算 performance/Sharpe/alpha，不优化参数，不拥有持久化或 OOS Consumption Ledger，不生成 fold，不拥有 trading calendar 或 bar-grid 换算，不拥有 universe checkpoint/采样策略。它是消费层：真正 import 并使用 `experiment_governance`（`ExperimentManifest`/`ParameterOrigin`/`ExperimentLineageAudit`）、`information_dependency`（`InformationDependencyReport`）与 `universe_integrity`（三种 Resolution 类型）的既有产出，而非像下游三个已封闭模块那样彼此隔离。`ExperimentManifest` 在调用前必须已经冻结，但 `window_configuration`/`contamination_policy`/`evaluation_protocol` 三个治理指纹又依赖本次调用的 `mode`/`folds`/`parameter_selection_mode`——为解开这一先有鸡先有蛋的依赖，三个 `compute_*_fingerprint` 全部是公开函数，调用方必须能在构造 manifest **之前**独立算出完全相同的值再写入 `governed_components`，`"information_dependency"` 与 `"universe_policy"` 键分别复用 `InformationDependencyReport.contract_fingerprint` 与 `UniverseIntegrityRequirement.fingerprint`；五个治理键任一缺失或指纹不匹配都记为对应的 `*_UNBOUND` finding 并判定为 `INVALID`。`WalkForwardFindingCode` 到四态 `FoldValidationStatus`（`INVALID > LEAKAGE_RISK > INSUFFICIENT_DATA > VALID`）是固定映射表；实验级问题（manifest 绑定失败、lineage 裁决、information-dependency 完整度缺口、FIXED 模式 provenance 违规)会被同时记两份——一份 `fold_id=None` 写入 `report_findings` 作为唯一权威记录，另一份逐字复制并附上每个 fold 自己的 `fold_id` 写进该 fold 的 `FoldValidationResult.findings`，因为每个结果的状态只能由它自己携带的 findings 推导，而报告级 finding 绝不允许凭空生造出新的 fold 结果（"structural denominator"：恰有 N 个输入 fold 就恰有 N 个 `FoldValidationResult`)。逐 fold 证据集合（parameter-selection、separation、data、universe-integrity）先按 `fold_id` 分组而非按到达顺序处理：不属于任何输入 fold 的 id 记为 `EVIDENCE_FOLD_ID_UNKNOWN`（报告级，因为没有对应的 fold 结果可以挂载）；同一 fold 出现多条证据记为 `DUPLICATE_EVIDENCE_FOLD_ID` 并使该 fold 的这份证据在下游一律视为缺失（挑选其中一条会让结果依赖输入顺序）；完全没有对应条目记为 `FOLD_EVIDENCE_MISSING`。Fold 几何:未声明 validation 时要求 `train.end <= oos.start`，声明 validation 时要求 `train.end <= validation.start` 且 `validation.end <= oos.start`；`EXPANDING` 要求按 canonical 顺序 `train.start` 恒定、`train.end` 与 `oos.start` 严格递增，`ROLLING` 要求 `train.start`/`train.end`/`oos.start` 全部严格递增（允许变长窗口）；OOS 区间不得重叠，违规记在**较晚**的 canonical fold 上。Purge 恒由 `information_dependency.required_purge_bars` 驱动，为 `None` 记 `PURGE_REQUIREMENT_UNRESOLVED`；为整数时要求 `separation.purge_bar_grid_id` 与声明的 label bar grid 精确一致（不一致记 `BAR_GRID_MISMATCH`），再按是否存在 validation 分别核对 `applied_train_to_validation_purge_bars`/`applied_pre_oos_purge_bars` 是否 `>= required`（`None` 记 `PURGE_APPLICATION_UNRESOLVED`，不足记 `PURGE_INSUFFICIENT`）。Warmup 同理由 `required_warmup_bars` 驱动，大于零时额外核对 `data.bar_grid_id` 与声明的 evaluation grid 是否一致；`usable_train_bars` 为 `None` 记 `FOLD_EVIDENCE_MISSING`，不足 required 记 `TRAIN_WARMUP_INSUFFICIENT`。`None` 与 `0` 从不混淆：`usable_validation_bars`/`usable_oos_bars` 为 `None` 记证据缺失，恰好为 `0` 分别记 `VALIDATION_DATA_EMPTY`/`OOS_DATA_EMPTY`。参数 provenance 分三种模式：`FIXED` 要求 `parameter_origin`/`fixed_parameter_evidence` 均已提供且 `fold_parameter_selection_evidence` 必须为空（否则直接 `ValueError`，因为这是调用契约层面的先决条件而非可报告的证据问题），核对 parameter hash 是否一致、`information_horizon_end`/`declared_at` 是否严格早于 `min(fold.train_interval.start)`、`PRIOR_EXPERIMENT` 来源是否自我引用；`TRAIN_ONLY`/`TRAIN_VALIDATION` 则要求每个 fold 都有 `FoldParameterSelectionEvidence`，核对 `latest_selection_information_at` 是否严格早于 `train.end`/`validation.end` 与 `selection_completed_at`、`selection_completed_at` 是否严格早于 `oos.start`（`==` 一律拒绝，从不用 `<=`）。`CROSS_FOLD_OOS_FEEDBACK` 与 `EMBARGO_INSUFFICIENT` 均为 V0.1 保留但结构上不可达的 finding code——前者因为"原始行情事实" 与 "OOS 策略结果影响后续选参" 这两种情形无法仅凭时间戳区分，V0.1 不假装能侦测未声明的 feedback；后者因为当前严格顺序能力下 `required_embargo_bars` 恒为 0。`ExperimentLineageAudit` 不审计 `PRIOR_EXPERIMENT` 所指向的源实验本身，只核对是否自我引用当前 manifest。`FoldParameterSelectionEvidence` 属调用方声明 provenance：V0.1 检测其与冻结窗口/治理之间的矛盾，但不证明未声明的输入从未被读取过。Fold 顺序、finding 顺序与证据集合顺序均在构造期规范化（`(oos.start, train.start, fold_id)` 与 `(severity_rank, code.value, fold_id_or_empty, message)`），因此打乱任何输入序列的顺序不改变输出。模块 import `experiment_governance`/`information_dependency`/`universe_integrity` 但不修改它们，也不 import providers/repositories/trading_ca…12994 tokens truncated…命中零网络，调用方离线低延迟契约不变），跨市场候选能力由 `resolver_name_to_code_list()` 独立提供；解析全链路线程安全（`stockDB` 读写加锁、名称/拼音索引随库变更自动失效），新增 40 个单元测试覆盖精确/跨市场排序/子串/拼音/模糊/幂等扩展/失败退避/多候选场景。
- [改进] `StockDaily` 表新增可空 `canonical_id` 列并支持双写（Expand-Contract PR2，issue #2207）：自愈式迁移幂等加列 + 普通索引 `ix_stock_daily_canonical_id`，存量行与 `save_daily_data` 未显式传参时均经 index-aware 推导（裸指数码命中注册表时统一到指数 `canonical_id`，避免同一指数按输入形态分裂到不同桶——例如裸 `000300` 与显式 `sh000300` 现在都收敛到 `sh000300`，而非裸码被推导为 `sz000300`），推导失败写 NULL 降级；读路径仍用 `code` 列，`(code, date)` 唯一约束保留不变。显式登记契约漂移：PRD Glossary/FR-1/DD-3 与架构 AD-1/AD-7 中 canonical_id 的点分格式描述（`000016.SH`）已被 Phase 1 已合入代码的前缀格式（`sh000016`）取代，本变更遵循代码，PRD/架构文档的同步修正留待后续 PR 统一收敛。
- [新功能] 当前注册表已识别的 5 个沪深 A 股指数以显式市场输入按 canonical 身份路由：名称优先使用注册表并以 Tencent、AkShare、TickFlow 兜底，日线固定使用 Tencent、AkShare、TickFlow、yfinance 多源降级链，不读取普通 A 股日 K 的 `*_PRIORITY` 配置；裸代码仍按股票处理，并隔离同码股票名称缓存。
- [修复] Anspire 搜索默认切换为全球区域模式（`region_mode=2`），使海外股票新闻检索能够覆盖境外信息。
- [修复] 桌面端将 `builder-util-runtime` 升级至 9.7.0，修复 CVE-2026-54673 涉及的 HTTP 重定向凭据头信息泄露风险。
- [文档] 增加 xAI Grok 的 LiteLLM 配置示例、Grok Bot 集成指南和异步分析 Skill，明确分析模型与 AI teammate 两类接入边界。
- [测试] 固定 yfinance 股息 TTM 与单股报告文件名的时间夹具，消除跨日期和合并后时间基准冲突造成的 CI 波动。

## [3.30.0] - 2026-08-09

### 发布亮点

- feat: LLM 渠道新增显式 Chat Completions / Responses API Surface，统一连接测试、分析、选股、图片识别与状态诊断的协议路由。
- feat: Agent Chat 按会话持久化 Skill 选择，刷新和切换会话后可恢复，并完整保留省略、显式空列表与非空选择三态。
- feat: Electron 桌面端恢复历史报告、市场复盘和完整报告分享图；未配置自定义品牌时，统一使用随包二维码与默认“小红书@霸天土小豆”账号文案。
- feat: 新增单条分析目标解析契约，收紧交易所后缀、指数别名及美股代码的规范化边界。
- fix: 修复移动端侧栏滚动、自选股详情状态、长通知标题分片及 Lark 国际域名等用户可见稳定性问题。
- improve: 后端 CI 按测试文件分成三个 runner 并行执行，并收紧 Web 共享资产与跨层契约的门禁范围。

### 新功能

- LLM 渠道支持显式选择 Chat Completions 或 Responses API Surface，兼容 Responses-only 模型，并让连接测试、主分析、选股、图片识别和状态诊断复用统一路由契约。
- Agent Chat 将 Skill 选择按会话持久化，刷新或切换会话后恢复；历史会话继续保留运行时默认，非法 Skill 请求不会误清空已有选择。
- Electron 桌面端复用安装包自带 Chromium，为历史个股报告、市场复盘和完整报告生成 PNG 分享图；Web 与桌面端统一使用随包分发的小红书二维码。
- `STOCK_LIST` 新增 `parse_analysis_target()` 单条目解析契约，并对外暴露可注入的指数注册表及解析结果类型。

### 改进

- 优化首页侧栏任务面板和自选股工作区，支持折叠任务摘要、自选股直接打开最新详情，并压缩头部操作以释放列表空间。
- 后端 CI 按完整测试文件拆分为三个 runner 并行执行，由统一 `backend-gate` 汇总结果；继续保留稳定的离线测试语义并降低全局状态竞态风险。

### 修复

- 固定分享图小红书二维码下方的账号文案格式为“小红书@昵称”，未配置自定义昵称时默认显示“小红书@霸天土小豆”；不再渲染数字 ID，历史 ID 配置不会改变分享图模板。
- 修复首页移动端历史、自选和今日列表无法稳定纵向触摸滚动的问题，同时保持桌面端卡片裁剪行为。
- 长通知包含一级 Markdown 标题时按对应标题边界正确分片，避免错误递归耗尽长度预算并中断发送。
- 收敛自选股详情与今日状态语义：刷新和查询期间不再开放过期报告，失败时不会将旧历史误标为今日分析，并限制逐股票 fallback 并发及取消失效批次。
- 收敛 Responses 渠道的协议、provider、route alias 与 wire-model 契约，拒绝协议不匹配、同名 alias 混用 Surface 及非法历史配置。
- 飞书交互机器人在 `FEISHU_DOMAIN=lark` 时让 Stream 长连接和消息回复统一使用 Lark 国际版 API 域名，避免连接国内域名后返回 `Incorrect domain name`。
- 显式交易所后缀、畸形混合 alias、dotted-prefix 及外盘半显式后缀的非法输入不再静默改写或降级为错误市场。
- `us` 前缀保持大小写不敏感，但 ticker base 必须满足规范的大写美股代码形态；非法小写、标点或数字输入直接返回 `unsupported`。
- 带 `.US` 后缀的规范美股代码不再因前两字符碰撞 `sh`、`hk`、`bj` 或 `us` 前缀而被错误拆分。

### 测试

- 非 Web 改动默认执行完整后端门禁；纯 Web、共享 public 资产、渠道模板和设置帮助的过滤语义补充回归测试，Docker 构建继续按实际输入过滤。

### 文档

- FAQ 补充 macOS 桌面应用被 Gatekeeper quarantine 阻止启动时，对受信任安装包进行临时放行的步骤。

## [3.29.0] - 2026-08-02

### 发布亮点

- feat: 将参考 AlphaSift 实现的选股核心与策略正式纳入 DSA，新增选股运行历史、数据源历史和候选深度分析链路。
- feat: 新增 1080px 个股决策卡与高密度市场复盘分享图，支持 Web 原生分享和下载回退。
- feat: 新增 Skill Opinion Outcome 计算、表现统计与基于真实样本的有界运行时权重。
- improve: 优化选股快照复用、热点按需加载、多源并发和候选轮换，缩短长流程等待并提升结果多样性。
- fix: 加固关闭认证、短凭证诊断脱敏、CI 超时取证和桌面冻结包启动链路。
- fix: 修复 Longbridge 量比、股票代码窗口解析、选股后置重排及分享图交互等稳定性问题。

### 新功能

- SkillAggregator 基于独立满足 30 条 evaluated 门槛的真实 Skill Outcome bucket，使用 Beta 先验收缩、unable 惩罚和多周期证据加权生成有界运行时权重；缺失、低样本或异常统计保持中性。
- 选股结果按 `run_id` 持久化到 DSA 数据库，新增运行历史和数据源历史 API，接入公告事件上下文及其搜索缓存，并支持将候选连同筛选策略映射的 skill 交给单股深度分析。
- 新增按 skill、horizon 与 outcome engine version 独立聚合的只读 Skill Opinion 表现统计；少于 30 条 evaluated 样本时仅返回观察性计数，不输出表现指标或调整运行时权重。
- 新增按 individual SkillAgent 自身 signal、版本化 engine 与本地已存同源日线窗口计算并持久化 `skill_opinion_outcomes` 的核心服务。

### 改进

- 选中热点后先展示榜单已有摘要和核心股，后台再补充完整详情，并将单次热点源等待上限收紧为 8 秒。
- 热点成分股并行获取东方财富与同花顺数据，并按固定数据源优先级合并；真实供应商调用增加限流、可终止 timeout、并发槽和 worker 回收，题材详情可按需复用 DSA 原生搜索服务补充安全且带链接的近期消息。
- 精简选股页面的重复说明，将任务标识、快照统计和排序诊断折叠到运行详情。
- 将参考 AlphaSift 实现的选股核心与策略正式纳入 DSA，统一使用 `ScreeningService`、`SCREENING_ENABLED` 和 `/api/v1/screening`，并保留 Apache-2.0 归因与来源版本记录。
- Web 选股使用浏览器匿名种子与运行 ID 在最终评分后的有界近分池中生成每次运行的候选组合；本地评分覆盖完整短名单，远程分析继续遵守数量上限，硬过滤、风险否决和得分保持不变。
- 热点榜单刷新与选股长流程解除双向串行等待，热点详情改为选中后按需加载；选股默认复用 5 分钟内且数据源优先级一致的成功全市场快照，并展示快照、候选上下文、LLM 重排、最终评分和新闻事件增强阶段。
- 图片报告改用独立的 1080px 个股决策卡和高密度市场复盘卡，优先从结构化 payload 精确填充数据并保留 Markdown 回退；小红书账号与二维码支持关闭或替换，Web 支持原生分享与下载回退。

### 修复

- Web 分享图在按需生成完成后通过第二次用户点击同步打开系统分享，避免首次异步生成使原生分享退化为下载。
- Web 分享图改为用户点击“分享”后才按需生成，不再在报告加载时自动请求。
- 移除基础设置选股卡片中仍跳转到“数据源”的过期“查看配置项”按钮，并将 `SCREENING_ENABLED` 及 Web 选股功能开关归入“基础设置”。
- `scripts/ci_gate.sh` 的离线测试增加单测 timeout 与 faulthandler 取证，并同步 Docker 发布流程的 CI 依赖，避免无 traceback 卡住或发布门禁缺少 `pytest-timeout`。
- 选股策略栏稳定展示完整中文策略列表，并保留自定义策略 ID 入口。
- 选股热点详情统一使用中文业务文案，不再显示内部类名、字段名和原始数据源错误。
- 刷新热点榜单并保留当前题材时同步绕过详情缓存重拉该题材，避免新榜单继续搭配旧路线与成分股。
- 选股尾部轮换以分析器输入顺序为权威并保留并列分候选顺序；热点消息增强、共享缓存 owner、全局并发容量和新闻搜索 deadline 统一收敛。
- Outcome 候选按上次尝试时间公平调度，避免持续新增的缺失 key 使旧 `pending` outcome 永久得不到重试。
- 选股主模型返回空内容、非 JSON 或低覆盖结构时继续尝试备用模型；全部失败时明确展示确定性因子排序状态，且不把 `reasoning_content` 当作最终结果。
- 选股日线增强改用请求级 DSA-first fetcher 注入，多个后置分析器按最新分数逐级重排，远程分析状态跟随实际提交候选，避免重叠请求泄漏 wrapper 或改写未提交候选。
- 统一等价股票代码的本地日线候选与同源窗口解析；冲突沪深交易所代码不再降级匹配裸码，回测仅接受快照或交易日历确认的起点。
- 关闭认证时强制再次校验当前管理员密码，命中 rate limit 时返回 429，前端在当前密码缺失时阻止提交并显示内联提示（#1970）。
- 本地 CLI 的 `stdout_preview` / `stderr_preview` 按环境变量、JSON、YAML/日志标量与 URL 的独立契约脱敏短凭证，避免 API key、secret 或 token 进入诊断（refs #1784）。
- PyInstaller 冻结包在 NLTK 3.10 导入保护下误判内置 `_internal` 标准库时不再启动失败；Windows/macOS 打包脚本统一接入兼容 runtime hook。
- 分享图按字段合并历史结构化数据与 Markdown，多市场逐区域复用持久化 payload，隐藏不可用市场灯号维度并保留配色方案；中英韩模板跟随报告语言，原生分享失败时自动回退下载。
- 飞书文件报告在写入或上传前清理隐藏的市场 metadata；桌面运行时默认隐藏未随包提供 renderer 的 Web 分享按钮。
- `redact_diagnostic_text()` 的命令替换扫描不再吞掉尾随非敏感诊断字段，并统一 `export FOO=$(...)` 与 `FOO=$(...)` 的脱敏行为。
- Longbridge 量比改用 adaptive keyword args 调用 `history_candlesticks_by_offset`，兼容 0.2.74 与 4.x SDK 参数顺序（fixes #2100）。

## [3.28.0] - 2026-07-26

### 发布亮点

- feat: Multi-Agent 多策略综合支持分层 deliberation、mediator/self-review、revision projection 与 multi-round，并统一最终动作和解释契约。
- feat: AI 建议页新增按决策风格分组的历史表现，specialist opinion 样本可持久化并用于后验评估。
- feat: 新增 `--portfolio futu`，可只读导入 Futu OpenD 真实账户的沪深 A 股、港股和美股 LONG 正股持仓。
- feat: Web 首页与 API 支持按单个或多个市场临时触发大盘复盘，不修改全局配置。
- feat: Tushare 支持通过 `TUSHARE_HTTP_URL` 接入自建网关或兼容镜像。
- fix: 改进港股行情路由与缓存、外股英文新闻匹配、数据源兜底顺序及桌面端发包稳定性。

### 新功能

- Multi-Agent 多策略综合新增受控 deliberation v0、可注入 mediator/self-review v1-v2、只读 revision projection v3 与 multi-round v4；增强层相对上一层 baseline 只能保持或继续 softened，不覆盖权威最终信号。
- `specialist` 模式最多选择 4 个策略专家，并通过 `AGENT_SKILL_CONCURRENCY` 控制 1–4 个 worker 并发；worker 继承主管线冻结的 target date 等上下文，单个 skill 失败不阻断其它策略或最终决策。
- Multi-Agent 报告按八态用户 action 追踪 Pipeline 最终调整，排除非法 Agent 意见；仅在 canonical action 可唯一解析时生成 explanation 与 DecisionSignal，并以同一个 `final_action` 统一最终动作契约。
- specialist 在分析历史保存成功后持久化版本化、低敏且幂等的有效 opinion 样本，为后续后验评估提供真实数据；本阶段不计算 outcome、不统计表现、不调整权重。
- AI 建议页新增决策风格历史表现，按每个分组独立的 30 个已完成样本门槛展示命中、区间涨跌、无法评估和最大不利波动，并保持旧统计接口兼容。
- 新增 `--portfolio futu`，只读导入 Futu OpenD 真实账户的沪深 A 股、港股和美股 LONG 正股持仓作为分析列表。
- Web 首页与 `POST /api/v1/analysis/market-review` 支持用严格校验的 `region` 临时选择单个或多个复盘市场；一次性覆盖不读写全局配置，并贯穿任务提交、状态、SSE、结果与历史记录。
- Tushare 数据源支持通过 `TUSHARE_HTTP_URL` 自定义接入地址；留空时继续使用官方默认地址（fixes #1985）。

### 改进

- 暂停 PR Review 的自动触发，仅保留 `workflow_dispatch` 手动入口，避免辅助评审重复运行及评论权限失败产生误导性红灯；正式 CI 检查保持不变。
- `.env.example` 与每日分析 workflow 同步映射 `TUSHARE_HTTP_URL`，保持本地和云端配置入口一致。

### 修复

- 修复外股代码映射到中文显示名时英文新闻相关性漏判，统一外股代码、英文名和别名解析，并对展开后的检索词去重（fixes #2026）。
- 特权 `pull_request_target` 流程不再检出 fork PR head；敏感步骤仅执行主分支可信脚本，PR 元数据与 diff 通过 GitHub API 读取（fixes #2051）。
- PR Review 事件载荷缺失、不可读或 JSON 非法时输出可定位且不泄露载荷的警告，并保留原有降级行为（fixes #2070）。
- 修复 Windows 上 `mimetypes` 冷启动读取注册表导致进程卡死的问题。
- 统一 `DataFetcherManager`、AkShare 与 Longbridge 对 4–5 位裸港股码的识别，避免 4 位代码被错误路由或静默失败（fixes #2091）。
- AkShare 港股实时行情增加 20 分钟全市场缓存与并发冷启动 single-flight，热缓存命中不再等待网络限速，主接口异常时仍保留新浪备用接口降级（refs #1852）。
- 将 `TencentFetcher` 默认优先级调整为 A 股日 K 数据源的最终兜底，并新增 `TENCENT_PRIORITY` 显式覆盖项（refs #2032）。
- Web 设置页和通知测试入口补齐普通钉钉群机器人配置，支持安全遮罩保存 webhook 与 secret、查看帮助并发送测试通知（refs #1957）。
- Agent Chat 普通与流式接口在请求未指定 `report_language` 时继承全局 `REPORT_LANGUAGE`，显式请求值仍优先。
- WebUI 分开展示发布版本、代码版本与构建时间，并用构建输入摘要避免复用时间戳未变化的旧静态资源（fixes #2093）。
- macOS unsigned 打包显式禁用 Electron 签名与 Hardened Runtime，在冻结后端和 electron-builder 阶段清理残缺签名，并审计原始应用与 DMG 产物；该缓解不替代 Apple Developer 签名与公证（refs #2075）。

### 文档

- 修复文档中的失效相对链接。
- [修复] #2026 外股代码映射到中文显示名时英文新闻相关性判定漏判：新增同源 STOCK_ENGLISH_NAME_MAP 单一真源、canonicalize_foreign_stock_code 规范化入口与 _foreign_english_query_terms 别名解析，使 AAPL/00700/BABA 等 ticker 即使 stock_name 为中文也能在查询构建、相关性打分与多维度情报路径上复用 canonical 英文名，并补齐 .US/.HK suffix / HK 前缀全形式的归类与回归用例；同时在 _score_news_relevance 对 alias 展开 term 做去重，避免 legal alias 展开短名与显式 short alias 重复计分。
- [新功能] Tushare 数据源支持通过 `TUSHARE_HTTP_URL` 环境变量自定义接入地址，便于网络无法直达 `api.tushare.pro` 时切换自建网关或第三方兼容镜像；留空保持官方默认地址不变（fixes #1985）
- [文档] `.env.example` 与 `.github/workflows/00-daily-analysis.yml` 同步映射 `TUSHARE_HTTP_URL`，避免出现"配置项有但 workflow 漏映射"的半修状态
- [修复] #2051 PR Review 的特权 `pull_request_target` 流程不再检出 fork PR head：敏感文件、标签、报告与 AI 审查统一通过 GitHub API 将 PR 元数据和 diff 作为数据读取，只执行主分支可信脚本；Python 语法、Flake8、确定性检查和离线测试继续由无 secrets 的 `pull_request` CI / `backend-gate` 执行，兼容 `actions/checkout` 新增的 fork checkout 安全保护。
- [修复] 修复 Windows 上 mimetypes 冷启动时读取注册表导致的进程卡死

## [3.27.0] - 2026-07-19

### 发布亮点

- feat: 新增 Codex App Server single-agent 问股实验原型，并保持 LiteLLM、Multi Agent、普通报告和定时任务等默认链路不变。
- feat: Web AI 建议页支持保存基于历史报告快照重算的决策风格信号，补齐去重、续期、失效和可审计 guardrail 语义。
- feat: 引入多策略观点结构化输出第一阶段契约，覆盖观点标准化、基础冲突检测、聚合元数据和报告兼容边界。
- improve: 报告页明确展示输入数据状态、来源、异常影响、处理建议和诊断码，并区分页面资讯与本次分析输入。
- fix: 修复 MiniMax 推理内容污染最终 JSON、字符串 `<think>` 包装兼容及多 Agent 风险覆盖后结论未按最终信号收敛的问题。
- fix: 补齐美…32955 tokens truncated…。
- 📅 **持仓页默认日期本地化**：手工录入表单默认日期改用本地时间（`getFullYear/Month/Date`），修复 UTC-N 时区用户在当天晚间出现日期偏移的问题。
- 🔁 **CSV 导入去重逻辑加固**：dedup hash 纳入行序号作为区分因子，确保同字段合法分笔成交不被误折叠；同时在 `trade_uid` 存在时也持久化 hash，防止混合来源重复写入。

### 变更

- `POST /api/v1/portfolio/trades` 在同账户内 `trade_uid` 冲突时返回 `409`。
- 持仓风险响应新增 `sector_concentration` 字段（增量扩展），原有 `concentration` 字段保持不变。
- 分析 API `analyze` 接口异步行为契约文档化；前端报告类型联合更新。

### 测试

- 新增持仓核心服务测试（FIFO / AVG 部分卖出、同日事件顺序、重复 `trade_uid` 返回 409、快照 API 契约）。
- 新增 CSV 导入幂等性、合法分笔成交不误去重、去重边界、风险阈值边界、汇率降级行为测试。
- 新增 Agent `get_portfolio_snapshot` 工具调用测试。
- 新增分析 API 异步契约回归测试。

## [3.6.0] - 2026-03-14

### Added
- 📊 **Web UI Design System** — implemented dual-theme architecture and terminal-inspired atomic UI components
- 📊 **UI Components Refactoring** — integrated `clsx` and `tailwind-merge` for robust class composition across Web UI

- 🗑️ **History batch deletion** — Web UI now supports multi-selection and batch deletion of analysis history; added `POST /api/v1/history/batch-delete` endpoint and `ConfirmDialog` component.
- 🔐 **Auth settings API** — new `POST /api/v1/auth/settings` endpoint to enable or disable Web authentication at runtime and set the initial admin password when needed
- openclaw Skill 集成指南 — 新增 [docs/openclaw-skill-integration.md](openclaw-skill-integration.md)，说明如何通过 openclaw Skill 调用 DSA API
- ⚙️ **LLM channel protocol/test UX** — `.env` and Web settings now share the same channel shape (`LLM_CHANNELS` + `LLM_<NAME>_PROTOCOL/BASE_URL/API_KEY/MODELS/ENABLED`); settings page adds per-channel connection testing, primary/fallback/vision model selection, and protocol-aware model prefixing
- 🤖 **Agent architecture Phase 0+1** — shared protocols (`AgentContext`, `AgentOpinion`, `StageResult`), extracted `run_agent_loop()` runner, `AGENT_ARCH` switch (`single`/`multi`), config registry entries
- 🔍 **Bot NL routing** — two-layer natural-language routing: cheap regex pre-filter (stock codes + finance keywords) → lightweight LLM intent parsing; controlled by `AGENT_NL_ROUTING=true`; supports multi-stock and strategy extraction
- 💬 **`/ask` multi-stock analysis** — comma or `vs` separated codes (max 5), parallel thread execution with 150s timeout (preserves partial results), Markdown comparison summary table at top
- 📋 **`/history` command** — per-user session isolation via `{platform}_{user_id}:{scope}` format (colon delimiter prevents prefix collision); lists both `/chat` and `/ask` sessions; view detail or clear
- 📊 **`/strategies` command** — lists available strategy YAML files grouped by category (趋势/形态/反转/框架) with ✅/⬜ activation status
- 🔧 **Backtest summary tools** — `get_strategy_backtest_summary` and `get_stock_backtest_summary` registered as read-only Agent tools
- ⚙️ **Agent auto-detection** — `is_agent_available()` auto-detects from `LITELLM_MODEL`; explicit `AGENT_MODE=true/false` takes full precedence
- 🏗️ **Multi-Agent orchestrator (Phase 2)** — `AgentOrchestrator` with 4 modes (`quick`/`standard`/`full`/`strategy`); drop-in replacement for `AgentExecutor` via `AGENT_ARCH=multi`; `BaseAgent` ABC with tool subset filtering, cached data injection, and structured `AgentOpinion` output
- 🧩 **Specialised agents (Phase 2-4)** — `TechnicalAgent` (8 tools, trend/MA/MACD/volume/pattern analysis), `IntelAgent` (news & sentiment, risk flag propagation), `DecisionAgent` (synthesis into Decision Dashboard JSON), `RiskAgent` (7 risk categories, two-level severity with soft/hard override)
- 📈 **Strategy system (Phase 3)** — `StrategyAgent` (per-strategy evaluation from YAML skills), `StrategyRouter` (rule-based regime detection → strategy selection), `StrategyAggregator` (weighted consensus with backtest performance factor)
- 🔬 **Deep Research agent (Phase 5)** — `ResearchAgent` with 3-phase approach (decompose → research sub-questions → synthesise report); token budget tracking; new `/research` bot command with aliases (`/深研`, `/deepsearch`)
- 🧠 **Memory & calibration (Phase 6)** — `AgentMemory` with prediction accuracy tracking, confidence calibration (activates after minimum sample threshold), strategy auto-weighting based on historical win rate
- 📊 **Portfolio Agent (Phase 7)** — `PortfolioAgent` for multi-stock portfolio analysis (position sizing, sector concentration, correlation risk, cross-market linkage, rebalance suggestions)
- 🔔 **Event-driven alerts (Phase 7)** — `EventMonitor` with `PriceAlert`, `VolumeAlert`, `SentimentAlert` rules; async checking, callback notifications, serializable persistence
- ⚙️ **New config entries** — `AGENT_ORCHESTRATOR_MODE`, `AGENT_RISK_OVERRIDE`, `AGENT_DEEP_RESEARCH_BUDGET`, `AGENT_MEMORY_ENABLED`, `AGENT_STRATEGY_AUTOWEIGHT`, `AGENT_STRATEGY_ROUTING` — all registered in `config.py` + `config_registry.py` (WebUI-configurable)

### Changed
- 🔐 **Auth password state semantics** — stored password existence is now tracked independently from auth enablement; when auth is disabled, `/api/v1/auth/status` returns `passwordSet=false` while preserving the saved password for future re-enable
- 🔐 **Auth settings re-enable hardening** — re-enabling auth with a stored password now requires `currentPassword`, and failed session creation rolls back the auth toggle to avoid lockout
- ♻️ **AgentExecutor refactored** — `_run_loop` delegates to shared `runner.run_agent_loop()`; removed duplicated serialization/parsing/thinking-label code
- ♻️ **Unified agent switch** — Bot, API, and Pipeline all use `config.is_agent_available()` instead of divergent `config.agent_mode` checks
- 📖 **README.md** — expanded Bot commands section (ask/chat/strategies/history), added NL routing note, updated agent mode description
- 📖 **.env.example** — added `AGENT_ARCH` and `AGENT_NL_ROUTING` configuration documentation
- 🔌 **Analysis API async contract** — `POST /api/v1/analysis/analyze` now documents distinct async `202` payloads for single-stock vs batch requests, and `report_type=full` is treated consistently with the existing full-report behavior

### Fixed
- 🐛 **Analysis API blank-code guardrails** — `POST /api/v1/analysis/analyze` now drops whitespace-only entries before batch enqueue and returns `400` when no valid stock code remains
- 🐛 **Bare `/api` SPA fallback** — unknown API paths now return JSON `404` consistently for both `/api/...` and the exact `/api` path
- 🎮 **Discord channel env compatibility** — runtime now accepts legacy `DISCORD_CHANNEL_ID` as a fallback for `DISCORD_MAIN_CHANNEL_ID`, and the docs/examples now use the same variable name as the actual workflow/config implementation
- 🐛 **Session secret rotation on Windows** — use atomic replace so auth toggles invalidate existing sessions even when `.session_secret` already exists
- 🐛 **Auth toggle atomicity** — persist `ADMIN_AUTH_ENABLED` before rotating session secret; on rotation failure, roll back to the previous auth state
- 🔧 **LLM runtime selection guardrails** — YAML 模式下渠道编辑器不再覆盖 `LITELLM_MODEL` / fallback / Vision；系统配置校验补上全部渠道禁用后的运行时来源检查，并修复 `vertexai/...` 这类协议别名模型被重复加前缀的问题
- 🐛 **Multi-stock `/ask` follow-up regressions** — portfolio overlay now shares the same timeout budget as the per-stock phase and is skipped on timeout instead of blocking the bot reply; `/history` now stores the readable per-stock summary instead of raw dashboard JSON; condensed multi-stock output now renders numeric `sniper_points` values
- 🐛 **Decision dashboard enum compatibility** — multi-agent `DecisionAgent` now keeps `decision_type` within the legacy `buy|hold|sell` contract and normalizes stray `strong_*` outputs before risk override, pipeline conversion, and downstream统计/通知汇总
- 🛟 **Multi-Agent partial-result fallback** — `IntelAgent` now caches parsed intel for downstream reuse, shared JSON parsing tolerates lightly malformed model output, and the orchestrator preserves/synthesizes a minimal dashboard on timeout or mid-pipeline parse failure instead of always collapsing to `50/观望/未知`
- 🐛 **Shared LiteLLM routing restored** — bot NL intent parsing and `ResearchAgent` planning/synthesis now reuse the same LiteLLM adapter / Router / fallback / `api_base` injection path as the main Agent flow, so `LLM_CHANNELS` / `LITELLM_CONFIG` / OpenAI-compatible deployments behave consistently
- 🐛 **Bot chat session backward compatibility** — `/chat` now keeps using the legacy `{platform}_{user_id}` session id when old history already exists, and `/history` can still list / view / clear those pre-migration sessions alongside the new `{platform}_{user_id}:chat` format
- 🐛 **EventMonitor unsupported rule rejection** — config validation/runtime loading now reject or skip alert types the monitor cannot actually evaluate yet, so schedule mode no longer silently accepts permanent no-op rules
- 🐛 **P0 基本面聚合稳定性修复** (#614) — 修复 `get_stock_info` 板块语义回归（新增 `belong_boards` 并保留 `boards` 兼容别名）、引入基本面上下文精简返回以控制 token、为基本面缓存增加最大条目淘汰，并补齐 ETF 总体状态聚合与 NaN 板块字段过滤，保证 fail-open 与最小入侵。
- 🔧 **GitHub Actions 搜索引擎环境变量补充** — 工作流新增 `MINIMAX_API_KEYS`、`BRAVE_API_KEYS`、`SEARXNG_BASE_URLS` 环境变量映射，使 GitHub Actions 用户可配置 MiniMax、Brave、SearXNG 搜索服务（此前 v3.5.0 已添加 provider 实现但缺少工作流配置）
- 🤖 **Multi-Agent runtime consistency** — `AGENT_MAX_STEPS` now propagates to each orchestrated sub-agent; added cooperative `AGENT_ORCHESTRATOR_TIMEOUT_S` budget to stop overlong pipelines before they cascade further
- 🔌 **Multi-Agent feature wiring** — `AGENT_RISK_OVERRIDE` now actively downgrades final dashboards on hard risk findings; `AGENT_MEMORY_ENABLED` now injects recent analysis memory + confidence calibration into specialised agents; multi-stock `/ask` now runs `PortfolioAgent` to add portfolio-level allocation and concentration guidance
- 🔔 **EventMonitor runtime wiring** — schedule mode can now load alert rules from `AGENT_EVENT_ALERT_RULES_JSON`, poll them at `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`, and send triggered alerts through the existing notification service
- 🛠️ **Follow-up stability fixes** — multi-stock `/ask` now falls back to usable text output when dashboard JSON parsing fails; EventMonitor skips semantically invalid rules instead of aborting schedule startup; background alert polling now runs independently of the main scheduled analysis loop
- 🧪 **Multi-Agent regression coverage** — added orchestrator execution tests for `run()`, `chat()`, critical-stage failure, graceful degradation, and timeout handling
- 🧹 **PortfolioAgent cleanup** — `post_process()` now reuses shared JSON parsing and removed stale unused imports
- 🚦 **Bot async dispatch** — `CommandDispatcher` now exposes `dispatch_async()`; NL intent parsing and default command execution are offloaded from the event loop, DingTalk stream awaits async handlers directly, and Feishu stream processing is moved off the SDK callback thread
- 🌐 **Async webhook handler** — new `handle_webhook_async()` function in `bot/handler.py` for use from async contexts (e.g. FastAPI); calls `dispatch_async()` directly without thread bridging
- 🧵 **Feishu stream ThreadPoolExecutor** — replaced unbounded per-message `Thread` spawning with a capped `ThreadPoolExecutor(max_workers=8)` to prevent thread explosion under message bursts
- 🔒 **EventMonitor safety** — `_check_volume()` now safely handles `get_daily_data` returning `None` (no tuple-unpacking crash); `on_trigger` callbacks support both sync and async callables via `asyncio.to_thread`/`await`
- 🧹 **ResearchAgent dedup** — `_filtered_registry()` now delegates to `BaseAgent._filtered_registry()` instead of duplicating the filtering logic
- 🧹 **Bot trailing whitespace cleanup** — removed W291/W293 whitespace issues across `bot/handler.py`, `bot/dispatcher.py`, `bot/commands/base.py`, `bot/platforms/feishu_stream.py`, `bot/platforms/dingtalk_stream.py`
- 🐛 **Dispatcher `_parse_intent_via_llm` safety** — replaced fragile `'raw' in dir()` with `'raw' in locals()` for undefined-variable guard in `JSONDecodeError` handler
- 🐛 **筹码结构 LLM 未填写时兜底补全** (#589) — DeepSeek 等模型未正确填写 `chip_structure` 时，自动用数据源已获取的筹码数据补全，保证各模型展示一致；普通分析与 Agent 模式均生效
- 🐛 **历史报告狙击点位显示原始文本** (#452) — 历史详情页现优先展示 `raw_result.dashboard.battle_plan.sniper_points` 中的原始字符串，避免 `analysis_history` 数值列把区间、说明文字或复杂点位压缩成单个数字；保留原有数值列作为回退
- 🐛 **Session prefix collision** — user ID `123` could see sessions of user `1234` via `startswith`; fixed with colon delimiter in session_id format
- 🐛 **NL pre-filter false positives** — `re.IGNORECASE` caused `[A-Z]{2,5}` to match common English words like "hello"; removed global flag, use inline `(?i:...)` only for English finance keywords
- 🐛 **Dotted ticker in strategy args** — `_get_strategy_args()` didn't recognize `BRK.B` as a stock code, leaving it in strategy text; now accepts `TICKER.CLASS` format
- ⏱️ **efinance 长调用挂起修复** (#660) — 为所有 efinance API 调用引入 `_ef_call_with_timeout()` 包装（默认 30 秒，可通过 `EFINANCE_CALL_TIMEOUT` 配置）；使用 `executor.shutdown(wait=False)` 确保超时后不再阻塞主线程，彻底消除 81 分钟挂起问题
- 🛡️ **类型安全内容完整性检查** (#660) — `check_content_integrity()` 现在将非字符串类型的 `operation_advice` / `analysis_summary` 视为缺失字段，避免下游 `get_emoji()` 因 `dict.strip()` 崩溃
- 📄 **报告保存与通知解耦** (#660) — `_save_local_report()` 不再依赖 `send_notification` 标志触发，`--no-notify` 模式下本地报告照常保存
- 🔄 **operation_advice 字典归一化** (#660) — Pipeline 和 BacktestEngine 现在将 LLM 返回的 `dict` 格式 `operation_advice` 通过 `decision_type`（不区分大小写）映射为标准字符串，防止因模型输出格式变化导致崩溃
- 🛡️ **runner.py usage None 防护** (#660) — `response.usage` 为 `None` 时不再抛出 `AttributeError`，回退为 0 token 计数
- 📋 **orchestrator 静默失败改为日志警告** (#660) — `IntelAgent` / `RiskAgent` 阶段失败现在记录 `WARNING` 而非静默跳过，便于诊断

### Notes
- ⚠️ **Multi-worker auth toggles** — runtime auth updates are process-local; multi-worker deployments must restart/roll workers to keep auth state consistent

## [3.5.0] - 2026-03-12

### Added
- 📊 **Web UI full report drawer** (Fixes #214) — history page adds "Full Report" button to display the complete Markdown analysis report in a side drawer; new `GET /api/v1/history/{record_id}/markdown` endpoint
- 📊 **LLM cost tracking** — all LLM calls (analysis, agent, market review) recorded in `llm_usage` table; new `GET /api/v1/usage/summary?period=today|month|all` endpoint returns aggregated token usage by call type and model
- 🔍 **SearXNG search provider** (Fixes #550) — quota-free self-hosted search fallback; priority: Bocha > Tavily > Brave > SerpAPI > MiniMax > SearXNG
- 🔍 **MiniMax web search provider** — `MiniMaxSearchProvider` with circuit breaker (3 failures → 300s cooldown) and dual time-filtering; configured via `MINIMAX_API_KEYS`
- 🤖 **Agent models discovery API** — `GET /api/v1/agent/models` returns available model deployments (primary/fallback/source/api_base) for Web UI model selector
- 🤖 **Agent chat export & send** (#495) — export conversation to .md file; send to configured notification channels; new `POST /api/v1/agent/chat/send`
- 🤖 **Agent background execution** (#495) — analysis continues when switching pages; badge notification on completion; auto-cancel in-progress stream on session switch
- 📝 **Report Engine P0** — Pydantic schema validation for LLM JSON; Jinja2 templates (markdown/wechat/brief) with legacy fallback; content integrity checks with retry; brief mode (`REPORT_TYPE=brief`); history signal comparison
- 📦 **Smart import** — multi-source import from image/CSV/Excel/clipboard; Vision LLM extracts code+name+confidence; name→code resolver (local map + pinyin + AkShare); confidence-tiered confirmation
- ⚙️ **GitHub Actions LiteLLM config** — workflow supports `LITELLM_CONFIG`/`LITELLM_CONFIG_YAML` for flexible AI provider configuration
- ⚙️ **Config engine refactor & system API** (#602) — unified config registry, validation and API exposure
- 📖 **LLM configuration guide** — new `docs/LLM_CONFIG_GUIDE.md` covering 3-tier config, quick start, Vision/Agent/troubleshooting

### Fixed
- 🐛 **analyze_trend always reports No historical data** (#600) — now fetches from DB/DataFetcher instead of broken `get_analysis_context`
- 🐛 **Chip structure fallback when LLM omits it** (#589) — auto-fills from data source chip data for consistent display across models
- 🐛 **History sniper points show raw text** (#452) — prioritizes original strings over compressed numeric values
- 🐛 **GitHub Actions ENABLE_CHIP_DISTRIBUTION configurable** (#617) — no longer hardcoded, supports vars/secrets override
- 🐛 **`.env` save preserves comments and blank lines** — Web settings no longer destroys `.env` formatting
- 🐛 **Agent model discovery fixes** — legacy mode includes LiteLLM-native providers; source detection aligned with runtime; fallback deployments no longer expanded per-key
- 🐛 **Stooq US stock previous close semantics** — no longer misuses open price as previous close
- 🐛 **Stock name prefetch regression** — prioritizes local `STOCK_NAME_MAP` before remote queries
- 🐛 **AkShare limit-up/down calculation** (#555) — fixed market analysis statistics
- 🐛 **AkShare Tencent source field index & ETF quote mapping** (#579)
- 🐛 **Pytdx stock name cache pagination** (#573) — prevents cache overflow
- 🐛 **PushPlus oversized report chunking** (#489) — auto-segments long content
- 🐛 **Agent chat cancel & switch** (#495) — cancel no longer misreports as failure; fast switch no longer overwrites stream state
- 🐛 **MiniMax search status in `/status` command** (#587)
- 🐛 **config_registry duplicate BOCHA_API_KEYS** — removed duplicate dict entry that silently overwrote config

### Changed
- 🔎 **Fetcher failure observability** — logs record start/success/failure with elapsed time, failover transitions; Efinance/Akshare include upstream endpoint and classified failure categories
- ♻️ **Data source resilience & cleanup** (#602) — fallback chain optimization
- ♻️ **Image extract API response extension** — new `items` field (code/name/confidence); `codes` preserved for backward compatibility
- ♻️ **Import parse error messages** — specific failure reasons for Excel/CSV; improved logging with file type and size

### Docs
- 📖 LLM config guide refactored for clarity (#583)
- 📖 `image-extract-prompt.md` with full prompt documentation
- 📖 AkShare fallback cache TTL documentation
## [3.4.10] - 2026-03-07

### Fixed
- 🐛 **EfinanceFetcher ETF OHLCV data** (#541, #527) — switch `_fetch_etf_data` from `ef.fund.get_quote_history` (NAV-only, no OHLCV, no `beg`/`end` params) to `ef.stock.get_quote_history`; ETFs now return proper open/high/low/close/volume/amount instead of zeros; remove obsolete NAV column mappings from `_normalize_data`
- 🐛 **tiktoken 0.12.0 `Unknown encoding cl100k_base`** (#537) — pin `tiktoken>=0.8.0,<0.12.0` in requirements.txt to avoid plugin-registration regression introduced in 0.12.0
- 🐛 **Web UI API error classification** (#540) — frontend no longer treats every HTTP 400 as the same "server/network" failure; now distinguishes Agent disabled / missing params / model-tool incompatibility / upstream LLM errors / local connection failures
- 🐛 **北交所代码识别失败** (#491, #533) — 8/4/92 开头的 6 位代码现正确识别为北交所；Tushare/Akshare/Yfinance 等数据源支持 .BJ 或 bj 前缀；Baostock/Pytdx 对北交所代码显式切换数据源；避免误判上海 B 股 900xxx
- 🐛 **狙击点位解析错误** (#488, #532) — 理想买入/二次买入等字段在无「元」字时误提取括号内技术指标数字；现先截去第一个括号后内容再提取

### Added
- **Markdown-to-image for dashboard report** (#455, #535) — 个股日报汇总支持 markdown 转图片推送（Telegram、WeChat、Custom、Email），与大盘复盘行为一致
- **markdown-to-file engine** (#455) — `MD2IMG_ENGINE=markdown-to-file` 可选，对 emoji 支持更好，需 `npm i -g markdown-to-file`
- **PREFETCH_REALTIME_QUOTES** (#455) — 设为 `false` 可禁用实时行情预取，避免 efinance/akshare_em 全市场拉取
- **Stock name prefetch** (#455) — 分析前预取股票名称，减少报告中「股票xxxxx」占位符
- 📊 **分析报告模型标记** (#528, #534) — 在分析报告 meta、报告末尾、推送内容中展示 `model_used`（完整 LLM 模型名）；Agent 多轮调用时记录并展示每轮实际使用的模型（支持 fallback 切换）

### Changed
- **Enhanced markdown-to-image failure warning** (#455) — 转图失败时提示具体依赖（wkhtmltopdf 或 m2f）
- **WeChat-only image routing optimization** (#455) — 仅配置企业微信图片时，不再对完整报告做冗余转图，避免误导性失败日志
- **Stock name prefetch lightweight mode** (#455) — 名称预取阶段跳过 realtime quote 查询，减少额外网络开销

## [3.4.9] - 2026-03-06

### Added
- 🧠 **Structured config validation** — `ConfigIssue` dataclass and `validate_structured()` with severity-aware logging; `CONFIG_VALIDATE_MODE=strict` aborts startup on errors
- 🖼️ **Vision model config** — `VISION_MODEL` and `VISION_PROVIDER_PRIORITY` for image stock extraction; provider fallback (Gemini → Anthropic → OpenAI → DeepSeek) when primary fails
- 🚀 **CLI init wizard** — `python -m dsa init` 3-step interactive bootstrap (model → data source → notification), 9 provider presets, incremental merge by default
- 🔧 **Multi-channel LLM support** with visual channel editor (#494)

### Changed
- ♻️ **Vision extraction** — migrated from gemini-3 hardcode to `litellm.completion()` with configurable model and provider fallback; `OPENAI_VISION_MODEL` deprecated in favor of `VISION_MODEL`
- ♻️ **Market analyzer** — uses `Analyzer.generate_text()` for LLM calls; fixes bypass and Anthropic `AttributeError` when using non-Router path
- ♻️ **Config validation refinements** — test_env output format syncs with `validate_structured` (severity-aware ✓/✗/⚠/·); Vision key warning when `VISION_MODEL` set but no provider API key; market_analyzer test covers `generate_market_review` fallback when `generate_text` returns None
- ⚙️ **Auto-tag workflow defaults to NO tag** — only tags when commit message explicitly contains `#patch`, `#minor`, or `#major`
- ♻️ **Formatter and notification refactor** (#516)

### Fixed
- 🐛 **STOCK_LIST not refreshed on scheduled runs** — `.env` or WebUI changes to `STOCK_LIST` now hot-reload before each scheduled analysis (#529)
- 🐛 **WebUI fails to load with MIME type error** — SPA fallback route now resolves correct `Content-Type` for JS/CSS files (#520)
- 🐛 **AstrBot sender docstring misplaced** — `import time` placed before docstring in `_send_astrbot`, causing it to become dead code
- 🐛 **Telegram Markdown link escaping** — `_convert_to_telegram_markdown` escaped `[]()` characters, breaking all Markdown links in reports
- 🐛 **Duplicate `discord_bot_status` field** in Config dataclass — second declaration silently shadowed the first
- 🧹 **Unused imports** — removed `shutil`/`subprocess` from `main.py`
- 🔧 **Config validation and Vision key check** (#525)

### Docs
- 📝 Clarified GitHub Actions non-trading-day manual run controls (`TRADING_DAY_CHECK_ENABLED` + `force_run`) for Issue #461 / PR #466

## [3.4.8] - 2026-03-02

### Fixed
- 🐛 **Desktop exe crashes on startup with `FileNotFoundError`** — PyInstaller build was missing litellm's JSON data files (e.g. `model_prices_and_context_window_backup.json`). Added `--collect-data litellm` to both Windows and macOS build scripts so the files are correctly bundled in the executable.

### CI
- 🔧 Cache Electron binaries on macOS CI runners to prevent intermittent EOF download failures when fetching `electron-vX.Y.Z-darwin-*.zip` from GitHub CDN
- 🔧 Fix macOS DMG `hdiutil Resource busy` error during desktop packaging

### Docs
- 📝 Clarify non-trading-day manual run controls for GitHub Actions (`TRADING_DAY_CHECK_ENABLED` + `force_run`) (#474)

## [3.4.7] - 2026-02-28

### Added
- 🧠 **CN/US Market Strategy Blueprint System** (#395) — market review prompt injects region-specific strategy blueprints with position sizing and risk trigger recommendations

### Fixed
- 🐛 **`TRADING_DAY_CHECK_ENABLED` env var and `--force-run` for GitHub Actions** (#466)
- 🐛 **Agent pipeline preserved resolved stock names** (#464) — placeholder names no longer leak into reports
- 🐛 **Code cleanup** (#462, Fixes #422)
- 🐛 **WebUI auto-build on startup** (#460)
- 🐛 **ARCH_ARGS unbound variable** (#458)
- 🐛 **Time zone inconsistency & right panel flash** (#439)

### Docs
- 📝 Clarify potential ambiguities in code (#343)
- 📝 ENABLE_EASTMONEY_PATCH guidance for Issue #453 (#456)

## [3.4.0] - 2026-02-27

### Added
- 📡 **LiteLLM Direct Integration + Multi API Key Support** (#454, Fixes #421 #428)
  - Removed native SDKs (google-generativeai, google-genai, anthropic); unified through `litellm>=1.80.10`
  - New config: `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`
  - Multi-key auto-builds LiteLLM Router (simple-shuffle) with 429 cooldown
  - **Breaking**: `.env` `GEMINI_MODEL` (no prefix) only for fallback; explicit config must include provider prefix

### Changed
- ♻️ **Notification Refactoring** (#435) — extracted 10 sender classes into `src/notification_sender/`

### Fixed
- 🐛 LLM NoneType crash, history API 422, sniper points extraction
- 🐛 Auto-build frontend on WebUI startup — `WEBUI_AUTO_BUILD` env var (default `true`)
- 🐛 Docker explicit project name (#448)
- 🐛 Bocha search SSL retry (#445, #446) — transient errors retry up to 3 times
- 🐛 Gemini google-genai SDK migration (Fixes #440, #444)
- 🐛 Mobile home page scrolling (Fixes #419, #433)
- 🐛 History list scroll reset (#431)
- 🐛 Settings save button false positive (fixes #417, #430)

## [3.3.22] - 2026-02-26

### Added
- 💬 **Chat History Persistence** (Fixes #400, #414) — `/chat` page survives refresh, sidebar session list
- 🎨 Project VI Assets — logo icon set, PSD, vector, banner (#425)
- 🚀 Desktop CI Auto-Release (#426) — Windows + macOS parallel builds

### Fixed
- 🐛 Agent Reasoning 400 & LiteLLM Proxy (fixes #409, #427)
- 🐛 Discord chunked sending (#413) — `DISCORD_MAX_WORDS` config
- 🐛 yfinance shared DataFrame (#412)
- 🐛 sniper_points parsing (#408)
- 🐛 Agent framework category missing (#406)
- 🐛 Date inconsistency & query id (fixes #322, #363)

## [3.3.12] - 2026-02-24

### Added
- 📈 **Intraday Realtime Technical Indicators** (Issue #234, #397) — MA calculated from realtime price, config: `ENABLE_REALTIME_TECHNICAL_INDICATORS`
- 🤖 **Agent Strategy Chat** (#367) — full ReAct pipeline, 11 YAML strategies, SSE streaming, multi-turn chat
- 📢 PushPlus Group Push — `PUSHPLUS_TOPIC` (#402)
- 📅 Trading Day Check (Issue #373, #375) — `TRADING_DAY_CHECK_ENABLED`, `--force-run`

### Fixed
- 🐛 DeepSeek reasoning mode (Issue #379, #386)
- 🐛 Agent news intel persistence (Fixes #396, #405)
- 🐛 Bare except clauses replaced with `except Exception` (#398)
- 🐛 UUID fallback for HTTP non-secure context (fixes #377, #381)
- 🐛 Docker DNS resolution (Fixes #372, #374)
- 🐛 Agent session/strategy bugs — multiple follow-up fixes for #367
- 🐛 yfinance parallel download data filtering

### Changed
- Market review strategy consistency — unified cn/us template
- Agent test assertions updated (`6 -> 11`)


## [3.2.11] - 2026-02-23

### 修复（#patch）
- 🐛 **StockTrendAnalyzer 从未执行** (Issue #357)
  - 根因：`get_analysis_context` 仅返回 2 天数据且无 `raw_data`，pipeline 中 `raw_data in context` 始终为 False
  - 修复：Step 3 直接调用 `get_data_range` 获取 90 日历天（约 60 交易日）历史数据用于趋势分析
  - 改善：趋势分析失败时用 `logger.warning(..., exc_info=True)` 记录完整 traceback

## [3.2.10] - 2026-02-22

### 新增
- ⚙️ 支持 `RUN_IMMEDIATELY` 配置项，设为 `true` 时定时任务触发后立即执行一次分析，无需等待首个定时点

### 修复
- 🐛 修复 Web UI 页面居中问题
- 🐛 修复 Settings 返回 500 错误

## [3.2.9] - 2026-02-22

### 修复
- 🐛 **ETF 分析仅关注指数走势**（Issue #274）
  - 美股/港股 ETF（如 VOO、QQQ）与 A 股 ETF 不再纳入基金公司层面风险（诉讼、声誉等）
  - 搜索维度：ETF/指数专用 risk_check、earnings、industry 查询，避免命中基金管理人新闻
  - AI 提示：指数型标的分析约束，`risk_alerts` 不得出现基金管理人公司经营风险

## [3.2.8] - 2026-02-21

### 修复
- 🐛 **BOT 与 WEB UI 股票代码大小写统一**（Issue #355）
  - BOT `/analyze` 与 WEB UI 触发分析的股票代码统一为大写（如 `aapl` → `AAPL`）
  - 新增 `canonical_stock_code()`，在 BOT、API、Config、CLI、task_queue 入口处规范化
  - 历史记录与任务去重逻辑可正确识别同一股票（大小写不再影响）

## [3.2.7] - 2026-02-20

### 新增
- 🔐 **Web 页面密码验证**（Issue #320, #349）
  - 支持 `ADMIN_AUTH_ENABLED=true` 启用 Web 登录保护
  - 首次访问在网页设置初始密码；支持「系统设置 > 修改密码」和 CLI `python -m src.auth reset_password` 重置

## [3.2.6] - 2026-02-20
### ⚠️ 破坏性变更（Breaking Changes）

- **历史记录 API 变更 (Issue #322)**
  - 路由变更：`GET /api/v1/history/{query_id}` → `GET /api/v1/history/{record_id}`
  - 参数变更：`query_id` (字符串) → `record_id` (整数)
  - 新闻接口变更：`GET /api/v1/history/{query_id}/news` → `GET /api/v1/history/{record_id}/news`
  - 原因：`query_id` 在批量分析时可能重复，无法唯一标识单条历史记录。改用数据库主键 `id` 确保唯一性
  - 影响范围：使用旧版历史详情 API 的所有客户端需同步更新

### 修复
- 修复美股（如 ADBE）技术指标矛盾：akshare 美股复权数据异常，统一美股历史数据源为 YFinance（Issue #311）
- 🐛 **历史记录查询和显示问题 (Issue #322)**
  - 修复历史记录列表查询中日期不一致问题：使用明天作为 endDate，确保包含今天全天的数据
  - 修复服务器 UI 报告选择问题：原因是多条记录共享同一 `query_id`，导致总是显示第一条。现改用 `analysis_history.id` 作为唯一标识
  - 历史详情、新闻接口及前端组件已全面适配 `record_id`
  - 新增后台轮询（每 30s）与页面可见性变更时静默刷新历史列表，确保 CLI 发起的分析完成后前端能及时同步，使用 `silent` 模式避免触发 loading 状态
- 🐛 **美股指数实时行情与日线数据** (Issue #273)
  - 修复 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指数无法获取实时行情的问题
  - 新增 `us_index_mapping` 模块，将用户输入（如 SPX）映射为 Yahoo Finance 符号（如 ^GSPC）
  - 美股指数与美股股票日线数据直接路由至 YfinanceFetcher，避免遍历不支持的数据源
  - 消除重复的美股识别逻辑，统一使用 `is_us_stock_code()` 函数

### 优化
- 🎨 **首页输入栏与 Market Sentiment 布局对齐优化**
  - 股票代码输入框左缘与历史记录 glass-card 框左对齐
  - 分析按钮右缘与 Market Sentiment 外框右对齐
  - Market Sentiment 卡片向下拉伸填满格子，消除与 STRATEGY POINTS 之间的空隙
  - 窄屏时输入栏填满宽度，响应式对齐保持一致

## [3.2.5] - 2026-02-19

### 新增
- 🌍 **大盘复盘可选区域**（Issue #299）
  - 支持 `MARKET_REVIEW_REGION` 环境变量：`cn`（A股）、`us`（美股）、`both`（两者）
  - us 模式使用 SPX/纳斯达克/道指/VIX 等指数；both 模式可同时复盘 A 股与美股
  - 默认 `cn`，保持向后兼容

## [3.2.4] - 2026-02-18

### 修复
- 🐛 **统一美股数据源为 YFinance**（Issue #311）
  - akshare 美股复权数据异常，统一美股历史数据源为 YFinance
  - 修复 ADBE 等美股股票技术指标矛盾问题

## [3.2.3] - 2026-02-18

### 修复
- 🐛 **标普500实时数据缺失**（Issue #273）
  - 修复 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指数无法获取实时行情的问题
  - 新增 `us_index_mapping` 模块，将用户输入（如 SPX）映射为 Yahoo Finance 符号（如 `^GSPC`）
  - 美股指数与美股股票日线数据直接路由至 YfinanceFetcher，避免遍历不支持的数据源

## [3.2.2] - 2026-02-16

### 新增
- 📊 **PE 指标支持**（Issue #296）
  - AI System Prompt 增加 PE 估值关注
- 📰 **新闻时效性筛查**（Issue #296）
  - `NEWS_MAX_AGE_DAYS`：新闻最大时效（天），默认 3，避免使用过时信息
- 📈 **强势趋势股乖离率放宽**（Issue #296）
  - `BIAS_THRESHOLD`：乖离率阈值（%），默认 5.0，可配置
  - 强势趋势股（多头排列且趋势强度 ≥70）自动放宽乖离率到 1.5 倍

## [3.2.1] - 2026-02-16

### 新增
- 🔧 **东财接口补丁可配置开关**
  - 支持 `EFINANCE_PATCH_ENABLED` 环境变量开关东财接口补丁（默认 `true`）
  - 补丁不可用时可降级关闭，避免影响主流程

## [3.2.0] - 2026-02-15

### 新增
- 🔒 **CI 门禁统一（P0）**
  - 新增 `scripts/ci_gate.sh` 作为后端门禁单一入口
  - 主 CI 改为 `backend-gate`、`docker-build`、`web-gate` 三段式
  - CI 触发改为所有 PR，避免 Required Checks 因路径过滤缺失而卡住合并
  - `web-gate` 支持前端路径变更按需触发
  - 新增 `network-smoke` 工作流承载非阻断网络场景回归
- 📦 **发布链路收敛（P0）**
  - `docker-publish` 调整为 tag 主触发，并增加发布前门禁校验
  - 手动发布增加 `release_tag` 输入与 semver/changelog 强校验
  - 发布前新增 Docker smoke（关键模块导入）
- 📝 **PR 模板升级（P0）**
  - 增加背景、范围、验证命令与结果、回滚方案、Issue 关联等必填项
- 🤖 **AI 审查覆盖增强（P0）**
  - `pr-review` 纳入 `.github/workflows/**` 范围
  - 新增 `AI_REVIEW_STRICT` 开关，可选将 AI 审查失败升级为阻断

## [3.1.13] - 2026-02-15

### 新增
- 📊 **仅分析结果摘要**（Issue #262）
  - 支持 `REPORT_SUMMARY_ONLY` 环境变量，设为 `true` 时只推送汇总，不含个股详情
  - 默认 `false`，多股时适合快速浏览

## [3.1.12] - 2026-02-15

### 新增
- 📧 **个股与大盘复盘合并推送**（Issue #190）
  - 支持 `MERGE_EMAIL_NOTIFICATION` 环境变量，设为 `true` 时将个股分析与大盘复盘合并为一次推送
  - 默认 `false`，减少邮件数量、降低被识别为垃圾邮件的风险

## [3.1.11] - 2026-02-15

### 新增
- 🤖 **Anthropic Claude API 支持**（Issue #257）
  - 支持 `ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`、`ANTHROPIC_TEMPERATURE`、`ANTHROPIC_MAX_TOKENS`
  - AI 分析优先级：Gemini > Anthropic > OpenAI
- 📷 **从图片识别股票代码**（Issue #257）
  - 上传自选股截图，通过 Vision LLM 自动提取股票代码
  - API: `POST /api/v1/stocks/extract-from-image`；支持 JPEG/PNG/WebP/GIF，最大 5MB
  - 支持 `OPENAI_VISION_MODEL` 单独配置图片识别模型
- ⚙️ **通达信数据源手动配置**（Issue #257）
  - 支持 `PYTDX_HOST`、`PYTDX_PORT` 或 `PYTDX_SERVERS` 配置自建通达信服务器

## [3.1.10] - 2026-02-15

### 新增
- ⚙️ **立即运行配置**（Issue #332）
  - 支持 `RUN_IMMEDIATELY` 环境变量，`true` 时定时任务启动后立即执行一次
- 🐛 修复 Docker 构建问题

## [3.1.9] - 2026-02-14

### 新增
- 🔌 **东财接口补丁机制**
  - 新增 `patch/eastmoney_patch.py` 修复 efinance 上游接口变更
  - 不影响其他数据源的正常运行

## [3.1.8] - 2026-02-14

### 新增
- 🔐 **Webhook 证书校验开关**（Issue #265）
  - 支持 `WEBHOOK_VERIFY_SSL` 环境变量，可关闭 HTTPS 证书校验以支持自签名证书
  - 默认保持校验，关闭存在 MITM 风险，仅建议在可信内网使用

## [3.1.7] - 2026-02-14

### 修复
- 🐛 修复包导入错误（package import error）

## [3.1.6] - 2026-02-13

### 修复
- 🐛 修复 `news_intel` 中 `query_id` 不一致问题

## [3.1.5] - 2026-02-13

### 新增
- 📷 **Markdown 转图片通知**（Issue #289）
  - 支持 `MARKDOWN_TO_IMAGE_CHANNELS` 配置，对 Telegram、企业微信、自定义 Webhook（Discord）、邮件发送图片格式报告
  - 邮件为内联附件，增强对不支持 HTML 客户端的兼容性
  - 需安装 `wkhtmltopdf` 和 `imgkit`

## [3.1.4] - 2026-02-12

### 新增
- 📧 **股票分组发往不同邮箱**（Issue #268）
  - 支持 `STOCK_GROUP_N` + `EMAIL_GROUP_N` 配置，不同股票组报告发送到对应邮箱
  - 大盘复盘发往所有配置的邮箱

## [3.1.3] - 2026-02-12

### 修复
- 🐛 修复 Docker 内运行时通过页面修改配置报错 `[Errno 16] Device or resource busy` 的问题

## [3.1.2] - 2026-02-11

### 修复
- 🐛 修复 Docker 一致性问题，解决关键批次处理与通知 Bug

## [3.1.1] - 2026-02-11

### 变更
- ♻️ `API_HOST` → `WEBUI_HOST`：Docker Compose 配置项统一

## [3.1.0] - 2026-02-11

### 新增
- 📊 **ETF 支持增强与代码规范化**
  - 统一各数据源 ETF 代码处理逻辑
  - 新增 `canonical_stock_code()` 统一代码格式，确保数据源路由正确

## [3.0.5] - 2026-02-08

### 修复
- 🐛 修复信号 emoji 与建议不一致的问题（复合建议如"卖出/观望"未正确映射）
- 🐛 修复 `*ST` 股票名在微信/Dashboard 中 markdown 转义问题
- 🐛 修复 `idx.amount` 为 None 时大盘复盘 TypeError
- 🐛 修复分析 API 返回 `report=None` 及 ReportStrategy 类型不一致问题
- 🐛 修复 Tushare 返回类型错误（dict → UnifiedRealtimeQuote）及 API 端点指向

### 新增
- 📊 大盘复盘报告注入结构化数据（涨跌统计、指数表格、板块排名）
- 🔍 搜索结果 TTL 缓存（500 条上限，FIFO 淘汰）
- 🔧 Tushare Token 存在时自动注入实时行情优先级
- 📰 新闻摘要截断长度 50→200 字

### 优化
- ⚡ 补充行情字段请求限制为最多 1 次，减少无效请求

## [3.0.4] - 2026-02-07

### 新增
- 📈 **回测引擎** (PR #269)
  - 新增基于历史分析记录的回测系统，支持收益率、胜率、最大回撤等指标评估
  - WebUI 集成回测结果展示

## [3.0.3] - 2026-02-07

### 修复
- 🐛 修复狙击点位数据解析错误问题 (PR #271)

## [3.0.2] - 2026-02-06

### 新增
- ✉️ 可配置邮件发送者名称 (PR #272)
- 🌐 外国股票支持英文关键词搜索

## [3.0.1] - 2026-02-06

### 修复
- 🐛 修复 ETF 实时行情获取、市场数据回退、企业微信消息分块问题
- 🔧 CI 流程简化

## [3.0.0] - 2026-02-06

### 移除
- 🗑️ **移除旧版 WebUI**
  - 删除基于 `http.server.ThreadingHTTPServer` 的旧版 WebUI（`web/` 包）
  - 旧版 WebUI 的功能已完全被 FastAPI（`api/`）+ React 前端替代
  - `--webui` / `--webui-only` 命令行参数标记为弃用，自动重定向到 `--serve` / `--serve-only`
  - `WEBUI_ENABLED` / `WEBUI_HOST` / `WEBUI_PORT` 环境变量保持兼容，自动转发到 FastAPI 服务
  - `webui.py` 保留为兼容入口，启动时直接调用 FastAPI 后端
  - Docker Compose 中移除 `webui` 服务定义，统一使用 `server` 服务

### 变更
- ♻️ **服务层重构**
  - 将 `web/services.py` 中的异步任务服务迁移至 `src/services/task_service.py`
  - Bot 分析命令（`bot/commands/analyze.py`）改为使用 `src.services.task_service`
  - Docker 环境变量 `WEBUI_HOST`/`WEBUI_PORT` 更名为 `API_HOST`/`API_PORT`（旧名仍兼容）

## [2.3.0] - 2026-02-01

### 新增
- 🇺🇸 **增强美股支持** (Issue #153)
  - 实现基于 Akshare 的美股历史数据获取 (`ak.stock_us_daily()`)
  - 实现基于 Yfinance 的美股实时行情获取（优先策略）
  - 增加对不支持数据源（Tushare/Baostock/Pytdx/Efinance）的美股代码过滤和快速降级

### 修复
- 🐛 修复 AMD 等美股代码被误识别为 A 股的问题 (Issue #153)

## [2.2.5] - 2026-02-01

### 新增
- 🤖 **AstrBot 消息推送** (PR #217)
  - 新增 AstrBot 通知渠道，支持推送到 QQ 和微信
  - 支持 HMAC SHA256 签名验证，确保通信安全
  - 通过 `ASTRBOT_URL` 和 `ASTRBOT_TOKEN` 配置

## [2.2.4] - 2026-02-01

### 新增
- ⚙️ **可配置数据源优先级** (PR #215)
  - 支持通过环境变量（如 `YFINANCE_PRIORITY=0`）动态调整数据源优先级
  - 无需修改代码即可优先使用特定数据源（如 Yahoo Finance）

## [2.2.3] - 2026-01-31

### 修复
- 📦 更新 requirements.txt，增加 `lxml_html_clean` 依赖以解决兼容性问题

## [2.2.2] - 2026-01-31

### 修复
- 🐛 修复代理配置区分大小写问题 (fixes #211)

## [2.2.1] - 2026-01-31

### 修复
- 🐛 **YFinance 兼容性修复** (PR #210, fixes #209)
  - 修复新版 yfinance 返回 MultiIndex 列名导致的数据解析错误

## [2.2.0] - 2026-01-31

### 新增
- 🔄 **多源回退策略增强**
  - 实现了更健壮的数据获取回退机制 (feat: multi-source fallback strategy)
  - 优化了数据源故障时的自动切换逻辑

### 修复
- 🐛 修复 analyzer 运行后无法通过改 .env 文件的 stock_list 内容调整跟踪的股票

## [2.1.14] - 2026-01-31

### 文档
- 📝 更新 README 和优化 auto-tag 规则

## [2.1.13] - 2026-01-31

### 修复
- 🐛 **Tushare 优先级与实时行情** (Fixed #185)
  - 修复 Tushare 数据源优先级设置问题
  - 修复 Tushare 实时行情获取功能

## [2.1.12] - 2026-01-30

### 修复
- 🌐 修复代理配置在某些情况下的区分大小写问题
- 🌐 修复本地环境禁用代理的逻辑

## [2.1.11] - 2026-01-30

### 优化
- 🚀 **飞书消息流优化** (PR #192)
  - 优化飞书 Stream 模式的消息类型处理
  - 修改 Stream 消息模式默认为关闭，防止配置错误运行时报错

## [2.1.10] - 2026-01-30

### 合并
- 📦 合并 PR #154 贡献

## [2.1.9] - 2026-01-30

### 新增
- 💬 **微信文本消息支持** (PR #137)
  - 新增微信推送的纯文本消息类型支持
  - 添加 `WECHAT_MSG_TYPE` 配置项

## [2.1.8] - 2026-01-30

### 修复
- 🐛 修正日志中 API 提供商显示错误 (PR #197)

## [2.1.7] - 2026-01-30

### 修复
- 🌐 禁用本地环境的代理设置，避免网络连接问题

## [2.1.6] - 2026-01-29

### 新增
- 📡 **Pytdx 数据源 (Priority 2)**
  - 新增通达信数据源，免费无需注册
  - 多服务器自动切换
  - 支持实时行情和历史数据
- 🏷️ **多源股票名称解析**
  - DataFetcherManager 新增 `get_stock_name()` 方法
  - 新增 `batch_get_stock_names()` 批量查询
  - 自动在多数据源间回退
  - Tushare 和 Baostock 新增股票名称/列表方法
- 🔍 **增强搜索回退**
  - 新增 `search_stock_price_fallback()` 用于数据源全部失败时
  - 新增搜索维度：市场分析、行业分析
  - 最大搜索次数从 3 增加到 5
  - 改进搜索结果格式（每维度 4 条结果）

### 改进
- 更新搜索查询模板以提高相关性
- 增强 `format_intel_report()` 输出结构

## [2.1.5] - 2026-01-29

### 新增
- 📡 新增 Pytdx 数据源和多源股票名称解析功能

## [2.1.4] - 2026-01-29

### 文档
- 📝 更新赞助商信息

## [2.1.3] - 2026-01-28

### 文档
- 📝 重构 README 布局
- 🌐 新增繁体中文翻译 (README_CHT.md)

### 修复
- 🐛 修复 WebUI 无法输入美股代码问题
  - 输入框逻辑改成所有字母都转换成大写
  - 支持 `.` 的输入（如 `BRK.B`）

## [2.1.2] - 2026-01-27

### 修复
- 🐛 修复个股分析推送失败和报告路径问题 (fixes #166)
- 🐛 修改 CR 错误，确保微信消息最大字节配置生效

## [2.1.1] - 2026-01-26

### 新增
- 🔧 添加 GitHub Actions auto-tag 工作流
- 📡 添加 yfinance 兜底数据源及数据缺失警告

### 修复
- 🐳 修复 docker-compose 路径和文档命令
- 🐳 Dockerfile 补充 copy src 文件夹 (fixes #145)

## [2.1.0] - 2026-01-25

### 新增
- 🇺🇸 **美股分析支持**
  - 支持美股代码直接输入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作为美股数据源
- 📈 **MACD 和 RSI 技术指标**
  - MACD：趋势确认、金叉死叉信号（零轴上金叉⭐、金叉✅、死叉❌）
  - RSI：超买超卖判断（超卖⭐、强势✅、超买⚠️）
  - 指标信号纳入综合评分系统
- 🎮 **Discord 推送支持** (PR #124, #125, #144)
  - 支持 Discord Webhook 和 Bot API 两种方式
  - 通过 `DISCORD_WEBHOOK_URL` 或 `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` 配置
- 🤖 **机器人命令交互**
  - 钉钉机器人支持 `/分析 股票代码` 命令触发分析
  - 支持 Stream 长连接模式
- 🌡️ **AI 温度参数可配置** (PR #142)
  - 支持自定义 AI 模型温度参数
- 🐳 **Zeabur 部署支持**
  - 添加 Zeabur 镜像部署工作流
  - 支持 commit hash 和 latest 双标签

### 重构
- 🏗️ **项目结构优化**
  - 核心代码移至 `src/` 目录，根目录更清爽
  - 文档移至 `docs/` 目录
  - Docker 配置移至 `docker/` 目录
  - 修复所有 import 路径，保持向后兼容
- 🔄 **数据源架构升级**
  - 新增数据源熔断机制，单数据源连续失败自动切换
  - 实时行情缓存优化，批量预取减少 API 调用
  - 网络代理智能分流，国内接口自动直连
- 🤖 Discord 机器人重构为平台适配器架构

### 修复
- 🌐 **网络稳定性增强**
  - 自动检测代理配置，对国内行情接口强制直连
  - 修复 EfinanceFetcher 偶发的 `ProtocolError`
  - 增加对底层网络错误的捕获和重试机制
- 📧 **邮件渲染优化**
  - 修复邮件中表格不渲染问题 (#134)
  - 优化邮件排版，更紧凑美观
- 📢 **企业微信推送修复**
  - 修复大盘复盘推送不完整问题
  - 增强消息分割逻辑，支持更多标题格式
  - 增加分批发送间隔，避免限流丢失
- 👷 **CI/CD 修复**
  - 修复 GitHub Actions 中路径引用的错误

## [2.0.0] - 2026-01-24

### 新增
- 🇺🇸 **美股分析支持**
  - 支持美股代码直接输入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作为美股数据源
- 🤖 **机器人命令交互** (PR #113)
  - 钉钉机器人支持 `/分析 股票代码` 命令触发分析
  - 支持 Stream 长连接模式
  - 支持选择精简报告或完整报告
- 🎮 **Discord 推送支持** (PR #124)
  - 支持 Discord Webhook 推送
  - 添加 Discord 环境变量到工作流

### 修复
- 🐳 修复 WebUI 在 Docker 中绑定 0.0.0.0 (fixed #118)
- 🔔 修复飞书长连接通知问题
- 🐛 修复 `analysis_delay` 未定义错误
- 🔧 启动时 config.py 检测通知渠道，修复已配置自定义渠道情况下仍然提示未配置问题

### 改进
- 🔧 优化 Tushare 优先级判断逻辑，提升封装性
- 🔧 修复 Tushare 优先级提升后仍排在 Efinance 之后的问题
- ⚙️ 配置 TUSHARE_TOKEN 时自动提升 Tushare 数据源优先级
- ⚙️ 实现 4 个用户反馈 issue (#112, #128, #38, #119)

## [1.6.0] - 2026-01-19

### 新增
- 🖥️ WebUI 管理界面及 API 支持（PR #72）
  - 全新 Web 架构：分层设计（Server/Router/Handler/Service）
  - 核心 API：支持 `/analysis` (触发分析), `/tasks` (查询进度), `/health` (健康检查)
  - 交互界面：支持页面直接输入代码并触发分析，实时展示进度
  - 运行模式：新增 `--webui-only` 模式，仅启动 Web 服务
  - 解决了 [#70](https://github.com/ZhuLinsen/daily_stock_analysis/issues/70) 的核心需求（提供触发分析的接口）
- ⚙️ GitHub Actions 配置灵活性增强（[#79](https://github.com/ZhuLinsen/daily_stock_analysis/issues/79)）
  - 支持从 Repository Variables 读取非敏感配置（如 STOCK_LIST, GEMINI_MODEL）
  - 保持对 Secrets 的向下兼容

### 修复
- 🐛 修复企业微信/飞书报告截断问题（[#73](https://github.com/ZhuLinsen/daily_stock_analysis/issues/73)）
  - 移除 notification.py 中不必要的长度硬截断逻辑
  - 依赖底层自动分片机制处理长消息
- 🐛 修复 GitHub Workflow 环境变量缺失（[#80](https://github.com/ZhuLinsen/daily_stock_analysis/issues/80)）
  - 修复 `CUSTOM_WEBHOOK_BEARER_TOKEN` 未正确传递到 Runner 的问题

## [1.5.0] - 2026-01-17

### 新增
- 📲 单股推送模式（[#55](https://github.com/ZhuLinsen/daily_stock_analysis/issues/55)）
  - 每分析完一只股票立即推送，不用等全部分析完
  - 命令行参数：`--single-notify`
  - 环境变量：`SINGLE_STOCK_NOTIFY=true`
- 🔐 自定义 Webhook Bearer Token 认证（[#51](https://github.com/ZhuLinsen/daily_stock_analysis/issues/51)）
  - 支持需要 Token 认证的 Webhook 端点
  - 环境变量：`CUSTOM_WEBHOOK_BEARER_TOKEN`

## [1.4.0] - 2026-01-17

### 新增
- 📱 Pushover 推送支持（PR #26）
  - 支持 iOS/Android 跨平台推送
  - 通过 `PUSHOVER_USER_KEY` 和 `PUSHOVER_API_TOKEN` 配置
- 🔍 博查搜索 API 集成（PR #27）
  - 中文搜索优化，支持 AI 摘要
  - 通过 `BOCHA_API_KEYS` 配置
- 📊 Efinance 数据源支持（PR #59）
  - 新增 efinance 作为数据源选项
- 🇭🇰 港股支持（PR #17）
  - 支持 5 位代码或 HK 前缀（如 `hk00700`、`hk1810`）

### 修复
- 🔧 飞书 Markdown 渲染优化（PR #34）
  - 使用交互卡片和格式化器修复渲染问题
- ♻️ 股票列表热重载（PR #42 修复）
  - 分析前自动重载 `STOCK_LIST` 配置
- 🐛 钉钉 Webhook 20KB 限制处理
  - 长消息自动分块发送，避免被截断
- 🔄 AkShare API 重试机制增强
  - 添加失败缓存，避免重复请求失败接口

### 改进
- 📝 README 精简优化
  - 高级配置移至 `docs/full-guide.md`


## [1.3.0] - 2026-01-12

### 新增
- 🔗 自定义 Webhook 支持
  - 支持任意 POST JSON 的 Webhook 端点
  - 自动识别钉钉、Discord、Slack、Bark 等常见服务格式
  - 支持配置多个 Webhook（逗号分隔）
  - 通过 `CUSTOM_WEBHOOK_URLS` 环境变量配置

### 修复
- 📝 企业微信长消息分批发送
  - 解决自选股过多时内容超过 4096 字符限制导致推送失败的问题
  - 智能按股票分析块分割，每批添加分页标记（如 1/3, 2/3）
  - 批次间隔 1 秒，避免触发频率限制

## [1.2.0] - 2026-01-11

### 新增
- 📢 多渠道推送支持
  - 企业微信 Webhook
  - 飞书 Webhook（新增）
  - 邮件 SMTP（新增）
  - 自动识别渠道类型，配置更简单

### 改进
- 统一使用 `NOTIFICATION_URL` 配置，兼容旧的 `WECHAT_WEBHOOK_URL`
- 邮件支持 Markdown 转 HTML 渲染

## [1.1.0] - 2026-01-11

### 新增
- 🤖 OpenAI 兼容 API 支持
  - 支持 DeepSeek、通义千问、Moonshot、智谱 GLM 等
  - Gemini 和 OpenAI 格式二选一
  - 自动降级重试机制

## [1.0.0] - 2026-01-10

### 新增
- 🎯 AI 决策仪表盘分析
  - 一句话核心结论
  - 精确买入/止损/目标点位
  - 检查清单（✅⚠️❌）
  - 分持仓建议（空仓者 vs 持仓者）
- 📊 大盘复盘功能
  - 主要指数行情
  - 涨跌统计
  - 板块涨跌榜
  - AI 生成复盘报告
- 🔍 多数据源支持
  - AkShare（主数据源，免费）
  - Tushare Pro
  - Baostock
  - YFinance
- 📰 新闻搜索服务
  - Tavily API
  - SerpAPI
- 💬 企业微信机器人推送
- ⏰ 定时任务调度
- 🐳 Docker 部署支持
- 🚀 GitHub Actions 零成本部署

### 技术特性
- Gemini AI 模型（gemini-3-flash-preview）
- 429 限流自动重试 + 模型切换
- 请求间延时防封禁
- 多 API Key 负载均衡
- SQLite 本地数据存储

---

[Unreleased]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.31.0...HEAD
[3.31.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.30.0...v3.31.0
[3.30.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.29.0...v3.30.0
[3.29.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.28.0...v3.29.0
[3.28.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.27.0...v3.28.0
[3.27.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.26.1...v3.27.0
[3.26.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.25.0...v3.26.1
[3.25.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.1...v3.25.0
[3.24.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.0...v3.24.1
[3.24.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.23.0...v3.24.0
[3.23.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.22.0...v3.23.0
[3.22.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.1...v3.22.0
[3.21.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.0...v3.21.1
[3.21.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.20.0...v3.21.0
[3.20.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.19.0...v3.20.0
[3.19.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.18.0...v3.19.0
[3.18.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.1...v3.18.0
[3.17.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.0...v3.17.1
[3.17.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.16.0...v3.17.0
[3.16.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.15.0...v3.16.0
[3.15.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.2...v3.15.0
[3.14.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.1...v3.14.2
[3.14.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.0...v3.14.1
[3.14.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.13.0...v3.14.0
[3.13.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.12.0...v3.13.0
[3.12.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.11.0...v3.12.0
[3.11.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.1...v3.11.0
[3.10.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.0...v3.10.1
[3.10.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.9.0...v3.10.0
[3.9.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.8.0...v3.9.0
[3.8.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.7.0...v3.8.0
[3.7.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.10...v3.5.0
[3.4.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.9...v3.4.10
[3.4.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.8...v3.4.9
[3.4.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.7...v3.4.8
[3.4.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.0...v3.4.7
[3.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.22...v3.4.0
[3.3.22]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.12...v3.3.22
[3.3.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.11...v3.3.12
[3.2.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.10...v3.2.11
[2.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.5...v2.3.0
[2.2.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.4...v2.2.5
[2.2.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.3...v2.2.4
[2.2.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.14...v2.2.0
[2.1.14]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.13...v2.1.14
[2.1.13]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.12...v2.1.13
[2.1.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.11...v2.1.12
[2.1.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.10...v2.1.11
[2.1.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.9...v2.1.10
[2.1.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.8...v2.1.9
[2.1.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.7...v2.1.8
[2.1.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.6...v2.1.7
[2.1.6]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.5...v2.1.6
[2.1.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.4...v2.1.5
[2.1.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.3...v2.1.4
[2.1.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.2...v2.1.3
[2.1.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.6.0...v2.0.0
[1.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v1.0.0
