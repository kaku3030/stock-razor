Warning: truncated output (original token count: 73874)
Total output lines: 2410

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
- [新功能] Strategy Lab V0.1 新增 Walk-Forward Core Foundation（`WalkForwardFold`/`FixedParameterEvidence`/`FoldParameterSelectionEvidence`/`FoldSeparationEvidence`/`FoldDataEvidence`/`UniverseIntegrityRequirement`/`FoldUniverseIntegrityEvidence`/`WalkForwardFinding`/`FoldValidationResult`/`WalkForwardValidationReport`，三个治理指纹函数 `compute_window_configuration_fingerprint`/`compute_contamination_policy_fingerprint`/`compute_evaluation_protocol_fingerprint`，以及入口 `validate_walk_forward`），校验调用方声明的 fold 几何、参数provenance、因果分离证据、information-dependency 义务、lineage 证据与 PIT universe 证据是否结构自洽到足以构成 OOS 证据；回答的是“这套 walk-forward 设置是否足够结构自洽以被信任”，而不是“这个策略是否盈利”——不计算 performance/Sharpe/alpha，不优化参数，不拥有持久化或 OOS Consumption Ledger，不生成 fold，不拥有 trading calendar 或 bar-grid 换算，不拥有 universe checkpoint/采样策略。它是消费层：真正 import 并使用 `experiment_governance`（`ExperimentManifest`/`ParameterOrigin`/`ExperimentLineageAudit`）、`information_dependency`（`InformationDependencyReport`）与 `universe_integrity`（三种 Resolution 类型）的既有产出，而非像下游三个已封闭模块那样彼此隔离。`ExperimentManifest` 在调用前必须已经冻结，但 `window_configuration`/`contamination_policy`/`evaluation_protocol` 三个治理指纹又依赖本次调用的 `mode`/`folds`/`parameter_selection_mode`——为解开这一先有鸡先有蛋的依赖，三个 `compute_*_fingerprint` 全部是公开函数，调用方必须能在构造 manifest **之前**独立算出完全相同的值再写入 `governed_components`，`"information_dependency"` 与 `"universe_policy"` 键分别复用 `InformationDependencyReport.contract_fingerprint` 与 `UniverseIntegrityRequirement.fingerprint`；五个治理键任一缺失或指纹不匹配都记为对应的 `*_UNBOUND` finding 并判定为 `INVALID`。`WalkForwardFindingCode` 到四态 `FoldValidationStatus`（`INVALID > LEAKAGE_RISK > INSUFFICIENT_DATA > VALID`）是固定映射表；实验级问题（manifest 绑定失败、lineage 裁决、information-dependency 完整度缺口、FIXED 模式 provenance 违规)会被同时记两份——一份 `fold_id=None` 写入 `report_findings` 作为唯一权威记录，另一份逐字复制并附上每个 fold 自己的 `fold_id` 写进该 fold 的 `FoldValidationResult.findings`，因为每个结果的状态只能由它自己携带的 findings 推导，而报告级 finding 绝不允许凭空生造出新的 fold 结果（"structural denominator"：恰有 N 个输入 fold 就恰有 N 个 `FoldValidationResult`)。逐 fold 证据集合（parameter-selection、separation、data、universe-integrity）先按 `fold_id` 分组而非按到达顺序处理：不属于任何输入 fold 的 id 记为 `EVIDENCE_FOLD_ID_UNKNOWN`（报告级，因为没有对应的 fold 结果可以挂载）；同一 fold 出现多条证据记为 `DUPLICATE_EVIDENCE_FOLD_ID` 并使该 fold 的这份证据在下游一律视为缺失（挑选其中一条会让结果依赖输入顺序）；完全没有对应条目记为 `FOLD_EVIDENCE_MISSING`。Fold 几何:未声明 validation 时要求 `train.end <= oos.start`，声明 validation 时要求 `train.end <= validation.start` 且 `validation.end <= oos.start`；`EXPANDING` 要求按 canonical 顺序 `train.start` 恒定、`train.end` 与 `oos.start` 严格递增，`ROLLING` 要求 `train.start`/`train.end`/`oos.start` 全部严格递增（允许变长窗口）；OOS 区间不得重叠，违规记在**较晚**的 canonical fold 上。Purge 恒由 `information_dependency.required_purge_bars` 驱动，为 `None` 记 `PURGE_REQUIREMENT_UNRESOLVED`；为整数时要求 `separation.purge_bar_grid_id` 与声明的 label bar grid 精确一致（不一致记 `BAR_GRID_MISMATCH`），再按是否存在 validation 分别核对 `applied_train_to_validation_purge_bars`/`applied_pre_oos_purge_bars` 是否 `>= required`（`None` 记 `PURGE_APPLICATION_UNRESOLVED`，不足记 `PURGE_INSUFFICIENT`）。Warmup 同理由 `required_warmup_bars` 驱动，大于零时额外核对 `data.bar_grid_id` 与声明的 evaluation grid 是否一致；`usable_train_bars` 为 `None` 记 `FOLD_EVIDENCE_MISSING`，不足 required 记 `TRAIN_WARMUP_INSUFFICIENT`。`None` 与 `0` 从不混淆：`usable_validation_bars`/`usable_oos_bars` 为 `None` 记证据缺失，恰好为 `0` 分别记 `VALIDATION_DATA_EMPTY`/`OOS_DATA_EMPTY`。参数 provenance 分三种模式：`FIXED` 要求 `parameter_origin`/`fixed_parameter_evidence` 均已提供且 `fold_parameter_selection_evidence` 必须为空（否则直接 `ValueError`，因为这是调用契约层面的先决条件而非可报告的证据问题），核对 parameter hash 是否一致、`information_horizon_end`/`declared_at` 是否严格早于 `min(fold.train_interval.start)`、`PRIOR_EXPERIMENT` 来源是否自我引用；`TRAIN_ONLY`/`TRAIN_VALIDATION` 则要求每个 fold 都有 `FoldParameterSelectionEvidence`，核对 `latest_selection_information_at` 是否严格早于 `train.end`/`validation.end` 与 `selection_completed_at`、`selection_completed_at` 是否严格早于 `oos.start`（`==` 一律拒绝，从不用 `<=`）。`CROSS_FOLD_OOS_FEEDBACK` 与 `EMBARGO_INSUFFICIENT` 均为 V0.1 保留但结构上不可达的 finding code——前者因为"原始行情事实" 与 "OOS 策略结果影响后续选参" 这两种情形无法仅凭时间戳区分，V0.1 不假装能侦测未声明的 feedback；后者因为当前严格顺序能力下 `required_embargo_bars` 恒为 0。`ExperimentLineageAudit` 不审计 `PRIOR_EXPERIMENT` 所指向的源实验本身，只核对是否自我引用当前 manifest。`FoldParameterSelectionEvidence` 属调用方声明 provenance：V0.1 检测其与冻结窗口/治理之间的矛盾，但不证明未声明的输入从未被读取过。Fold 顺序、finding 顺序与证据集合顺序均在构造期规范化（`(oos.start, train.start, fold_id)` 与 `(severity_rank, code.value, fold_id_or_empty, message)`），因此打乱任何输入序列的顺序不改变输出。模块 import `experiment_governance`/`information_dependency`/`universe_integrity` 但不修改它们，也不 import providers/repositories/trading_calendar/pandas/numpy 等无关依赖，由永久结构性测试强制验证。
- [新功能] Strategy Lab V0.1 新增 Universe Integrity Foundation（`UniverseMembershipAnchor`/`UniverseMembershipEvent`/`UniverseMembershipFacts`/`InstrumentLifecycleAnchor`/`InstrumentLifecycleEvent`/`InstrumentLifecycleFacts`/`ClassificationAnchor`/`ClassificationEvent`/`ClassificationFacts`/`ClassificationValue`、三套 Coverage Certificate、`CoverageDiagnostics`、`IntegrityFinding`、三个事件切片指纹函数与三个 `resolve_*` 决策入口），基于 Temporal Contract 的 `effective_at`/`available_at` 从因果时间戳化的 anchor 与 event 中重建 PIT universe membership、instrument lifecycle 与 classification 历史；不依赖 repositories、providers、trading calendar、security-master identity、`information_dependency` 或 `experiment_governance`。Anchor 是某一瞬间的完整绝对状态断言（membership 场景下是完整成员集合，绝非增量），Event 同样是绝对断言（`MEMBER`/`NON_MEMBER`、`LISTED`/`NOT_LISTED`、或完整 `ClassificationValue`），绝非 add/remove 指令，因此重建从不需要按顺序回放历史——只有某个 subject 最新 effective、最新可见 revision 才有意义。Anchor 选取：按 `effective_at <= as_of` 筛选出 eligible anchors 并按 effective_at 分组，每组解析其最新可见 revision 子组（先折叠完全重复项，子组内部矛盾记为 `ANCHOR_CONFLICT`），随后**无论该组是否 resolve 或 conflict**，一律选取 effective_at 最高的组——更早的已 resolve 组永远不能绕过更晚一次的 conflict，但更晚一次的 resolve 组可以覆盖更早的 conflict。effective_at 恰好等于选中 anchor 的 boundary event 既不会被静默忽略，也不会被当作状态变更应用：该 boundary subject 解析出的值会与 anchor 自身隐含值比较，一致则无害，不一致记为 `ANCHOR_EVENT_CONFLICT`，boundary 子组内部自相矛盾则记为 `EVENT_CONFLICT`（先于与 anchor 的比较判定）；对 anchor 自身取值的修正必须通过新的 anchor revision（同一 `effective_at`、更晚的 `available_at`）表达，绝不允许由同刻 event 篡改。Coverage 只做正向验证：每个 `*CoverageCertificate` 都会用实际持有的 facts 重新计算指纹并与 `certified_event_slice_fingerprint` 比对，scope 错误或指纹不匹配会让该证书本身失效（计入诊断计数器）但不会污染其余有效证书。当 `as_of > selected_anchor.effective_at` 时才要求 coverage；此时必须存在一个**包含 anchor 瞬间本身**（而非全局最靠后）的已合并有效区间，且其终点必须严格晚于 `as_of`——`coverage_end == as_of` 天然不足，这与 event 资格判定 `effective_at <= as_of` 保持一致。三个 `compute_*_event_slice_fingerprint` 是窄范围 SHA-256 摘要，只覆盖 schema tag、domain、scope、coverage 窗口，以及 `effective_at` 落在 `[coverage_start, coverage_end)` 内的每个 event（从不包含 anchor）——完全重复项在哈希前折叠，输入顺序不影响结果，窗口外的任何变化都不改变指纹。`instrument_id`/`universe_id`/`taxonomy_id`/`classification_id` 均为不透明精确匹配字符串，不做归一化、别名解析或强制转换，且在需要 enum 实例的位置绝不接受原始字符串。`UniverseIntegrityResolutionStatus` 与 `information_dependency.ResolutionStatus` 是完全独立的两个枚举——本模块完全不 import `information_dependency`。模块为仅依赖 stdlib 与 Temporal Contract 的纯计算叶子节点，由永久结构性测试强制验证。
- [新功能] Strategy Lab V0.1 新增 Temporal Contract Foundation（`TemporalInterval`/`TemporalEvidence`/`canonical_utc_datetime`/`canonical_utc_text`/`is_available_by`），负责 aware-datetime 校验、UTC 规范化、确定性 UTC 文本、半开时间区间、effective/available 时间证据与纯粹的可用性判定；不拥有 trading calendar、market session、bar-grid 或时间戳解析/持久化。所有公开 datetime 入参必须是真实 `datetime` 且 `tzinfo is not None`、`utcoffset() is not None`——字符串、int/float epoch、naive datetime、以及 `utcoffset()` 返回 `None` 的退化 `tzinfo` 一律 `ValueError` 拒绝而非强制转换，naive 值从不被假定为 UTC 或任何其他时区。规范化统一使用 `value.astimezone(timezone.utc)`，绝不使用 `value.replace(tzinfo=timezone.utc)`——`replace` 会在不改变时刻的前提下覆盖偏移量，而 `astimezone` 是把同一时刻换算成 UTC 表达；调用方提供的、正确 aware 的 `ZoneInfo` datetime 是合法输入，模块自身不 import `zoneinfo`、也不对任何时区名称分支。`canonical_utc_text` 为 UTC 下的 `isoformat(timespec="microseconds")`——恒定六位小数与字面量 `+00:00` 后缀，从不输出 `Z`，刻意区别于仓库内 `src/llm/usage.py` 秒精度、`Z` 后缀的另一套时间文本约定，两者不做统一。`TemporalInterval` 为半开区间 `[start, end)` 且严格要求 `start < end`，因此 `contains(start)` 为 `True`、`contains(end)` 为 `False`，相邻区间永不重叠；`contains` 对其 `moment` 参数应用与模块内其他 datetime 入参完全相同的校验规则。`TemporalEvidence` 携带 `effective_at` 与 `available_at`，二者之间刻意**不**设排序约束——谁先谁后或相等均合法——且不携带 `published_at`/`received_at`/`recorded_at`，因为生产者时间戳的真实性/来源判断被显式排除在本契约之外。`is_available_by` 是纯粹的因果性查询：`available_at <= decision_time` 为 `True`（相等被刻意视为可用），`available_at > decision_time` 为 `False`，非法 `decision_time` 恒抛异常而不会退化为 `False`。本模块不 import 也不重构 `experiment_governance`——后者已私有实现完全相同的 validate-canonicalize 规则（`_require_utc_datetime`），二者刻意保持独立实现，已封闭模块保持封闭。模块为 stdlib-only 纯计算叶子节点，由永久结构性测试断言其不 import trading calendar、Data Layer、repositories 或任何同级 Strategy Lab 引擎。

- [新功能] Strategy Lab V0.1 新增 Information Dependency Contract Foundation（泛型声明状态包装器 `DependencyDeclaration[T]`、聚合契约 `InformationDependencyDeclaration`、`FeatureSetDependency`/`FeatureDependencyDeclaration`/`FeatureDependency`/`LabelDependency`/`StateDependency`/`SampleOverlapDependency`/`AvailabilityLag`/`SampleInformationInterval` 与推导入口 `evaluate_information_dependency`），声明策略的 feature/label/state 究竟依赖哪些信息，并据此推导 warmup/purge/embargo/overlap 义务；回答的是"这份证据要在因果上干净需要满足什么"，而不是"这个策略是否盈利"。`bar_grid_id` 是**不透明的精确匹配标识符**：严格非空字符串，不做归一化、不做别名解析、不做任何解释，模块不赋予 `"1m"`/`"15m"`/`"1d"`/`"daily"`/`"D"` 等任何 provider 拼写以含义，也不拥有未来的 bar-grid 词表，更不依赖仓库中既有的若干套互不一致的 timeframe 词表；`FeatureSetDependency.evaluation_bar_grid_id` 声明策略真正被评估的 grid，跨 grid 判定是把每个已声明 feature 自身的 `bar_grid_id` 与该声明的 evaluation grid 逐一比较，**不会**因为所有 feature 彼此一致就推断为“同一 grid”——单个 feature 在 grid A 而评估在 grid B 同样属于跨 grid。不同 bar grid 上的 lookback 属于不同 index space，因此**永不做数值比较**（不取 max、不相加、不排序）；grid 之间的换算需要本模块刻意不拥有的日历，因此跨 grid warmup 归类为 `EXTERNAL_RESOLUTION_REQUIRED`：`feature_warmup_bars` 与 `required_warmup_bars` 均为 `None`，`warmup_source=UNRESOLVED`，`calendar_resolution_required=True`，且其本身**不**降低完整度。`LIMITED_EXPRESSION` 专门保留给真正的 schema 能力缺口（即 `AvailabilityLagKind.UNSUPPORTED`——词表根本无法表达），而非“表达精确但需要外部解析”的情况。`None` 永远不等于 `0`：未声明表示未知并污染一切派生量，声明为 NOT_APPLICABLE 表示恰好为零且完全已解析；`UNDECLARED` 不得携带占位 payload，`NOT_APPLICABLE` 必须给出非空 reason，二者无法被误认。声明状态是包装器而非 payload 字段：`DependencyDeclaration[T]` 是泛型声明状态包装器（`status` + 可选 `payload` + 可选 `reason`），`InformationDependencyDeclaration` 才是聚合契约（每个 slot 一个包装器）；payload dataclass 只描述依赖本身、绝不重复声明状态，因此"是否已声明"与"声明了什么"不会漂移。`FeatureDependencyDeclaration` 刻意特殊处理而非泛型包装：feature 的身份必须在未声明时依然存在，它沿用包装器的 `status`/`payload`/`reason` 形状并额外携带 `feature_id`，`reason` 在两种 status 下均可选（解释一个已声明依赖与解释一个空缺同样正当），`DECLARED` 必须提供 `FeatureDependency` payload，`UNDECLARED` 必须不携带 payload——"未声明"是被明确陈述的具名事实，而非从缺失值反推出来的。冻结的 NOT_APPLICABLE 矩阵：Label 非法、FeatureSet 合法（必须非空 reason）、State 非法、Overlap 合法（必须非空 reason）、单个 feature 非法（只有 FeatureSet 整体可以）。FeatureSet `UNDECLARED` → feature warmup 未知，`NOT_APPLICABLE` → 恰好 0，任一 `UNDECLARED` feature 即污染聚合 feature warmup 但保留该 feature 自身身份；每个达到该 grid 绑定最大值的 feature 全部保留（不塌缩为第一个）。State `UNDECLARED` → state warmup 未知，`STATELESS`/`WARM_START` → 0，`COLD_START` → 声明的 convergence warmup；任一侧未解析即污染 total required warmup。`warmup_source` 是单一标量枚举（feature 严格更大 → `FEATURE`；state 严格更大 → `STATE`；相等且为正 → `BOTH`；同为 0 → `NONE`；任一侧未知 → `UNRESOLVED`），绝不用 tuple/list/set 编码；feature 级别的并列由 `binding_feature_ids` 单独保留。刻意不产生聚合式 "warmup unresolved" finding：warmup 可能因某一侧未声明而未解析，也可能因跨 grid 不可比而未解析，两者 category 不同，用一个聚合 category 覆盖必然误报其中一种；未解析的 warmup 改为结构化表达（`required_warmup_bars=None` 且 `warmup_source=UNRESOLVED`），只上报各自具体的底层 findings。Purge 由 label information horizon 加其 availability lag 驱动，永不由 feature lookback 驱动（feature 从决策点向后看，label 越过决策点向前伸），horizon 与 lag 皆为 0 时推导出恰好为 0 的 purge——这是一个已解析的答案而非缺失值。`PurgeDerivation` 是结构化诊断记录（`label_horizon_bars`/`label_lag_kind`/`label_lag_bars`/`resolvable_in_bars`），而非 verdict/driver 枚举；label 未声明时其各字段显式表达“该声明事实不可得”，而不是省略。Label 与 State 均不允许声明为 `NOT_APPLICABLE`。lookback 与 availability 正交：feature 的 `lookback_bars` 与 label 的 `information_horizon_bars` 恒为非负整数 bar 数（依赖在 bar grid 上伸展多远永远可表达），而"何时才能真正知道该值"由独立的 `availability_lag` 描述，**只有该 lag** 可以是 `BAR_COUNT`/`DURATION`/`UNSUPPORTED`；lookback 本身永远不是 duration 或 unsupported，availability lag 也永不污染 warmup。`feature_availability_requirements` 是义务清单而非全量名册：只有 `DECLARED` feature 出现在其中，且各自带有具体 `bar_grid_id` 与完整 `AvailabilityLag`（kind、bars、duration、note，而不只是 kind）；`UNDECLARED` feature 只以结构化 unresolved finding 呈现，义务清单中永不出现"义务未知"的条目。每条 unresolved finding 携带 `UnresolvedCategory`，且**由 category 独占决定完整度**，不存在第二条 presentation severity 轴：任一 `UNDECLARED` → `INCOMPLETE`；否则任一 `LIMITED_EXPRESSION` → `LIMITED_EXPRESSION`；否则 `COMPLETE`。`EXTERNAL_RESOLUTION_REQUIRED` 保留在 unresolved findings 中但永不降低完整度——`DURATION` availability lag 正是这一类：置 `calendar_resolution_required=True` 并始终产生 unresolved finding，但完整度仍可为 `COMPLETE`（依赖被精确声明了，只是本模块按设计不拥有日历因而无法换算）；`UNSUPPORTED` 属 `LIMITED_EXPRESSION` 并确实降低完整度。无论哪一类胜出，所有 findings 都完整保留在报告中。Overlap 同样遵循三态：`NOT_APPLICABLE` → 不产生 overlap 对象；`UNDECLARED` → 不产生对象并附 `INCOMPLETE` finding；`DECLARED` 始终产生真实 `OverlapDiagnostics` 对象——未提供区间时为 `UNRESOLVED` 状态且各精确指标为 `None`，使未了义务不会静默消失；`DECLARED` 必须声明正整数 `sampling_step_bars`，它参与声明与 fingerprint（即便当前区间算法尚未消费它）。已解析的 `SampleInformationInterval` 采用半开区间 `[start_bar_index, end_bar_index)`，限定在调用方提供的单一 bar-index 域内——该类型自身不携带任何 grid 标识，跨域区间身份校验刻意排除在 V0.1 范围之外，而不是靠为每个区间附加 grid 元数据来模拟——暴露精确的最大并发数与最大互不重叠数。严格顺序评估是 V0.1 的**能力边界**而非调用方声明项：declaration 上没有 topology 字段，canonical payload 与两个 fingerprint 中也都没有；在该唯一受支持能力下推导恒为 `required_embargo_bars=0` 与显式 `NO_APPLICABLE_DEPENDENCY` 理由，该推导仅对 V0.1 严格顺序能力有效，不实现非顺序/CPCV 行为，未来引入时必须重新审视而非直接复用该常量。模块自带狭窄 canonicalizer（UTF-8、canonical JSON、`sort_keys=True`、固定分隔符、完整 SHA-256、Enum 按 `.value` 序列化、`timedelta` 按精确整数微秒序列化、显式 `None`、feature 按 `feature_id` 规范排序），对任何其他类型直接拒绝而非强制转换（全模块无 `default=str`）；不 import、不泛化 Experiment Governance 的 canonicalizer，已封闭的 `experiment_governance.py` 未被修改。`declaration_fingerprint` 只覆盖规范化后的 declarations，`contract_fingerprint` 覆盖 contract_version 加同一批 declarations——用于未来 `governed_components["information_dependency"]` 的是 `contract_fingerprint` 而非 `declaration_fingerprint`；产出该字符串即是全部集成接缝，本模块不 import 也不实例化任何 Experiment Governance 对象。报告上的两个 fingerprint 均为从其所依据的 declaration 派生的只读 property，不存在可供调用方传入或赋值的 fingerprint 字段——它们是溯源事实而非构造入参。模块为 stdlib-only 纯计算叶子节点，不引入 Data Layer、trading calendar、repositories/持久化或任何同级 Strategy Lab 引擎依赖，并由永久结构性测试强制保证。
- [新功能] Strategy Lab V0.1 新增 Experiment Governance Foundation（`ExperimentManifest`/`ParameterOrigin`/`LineageAuditContext`/`LineageViolation`/`ExperimentLineageAudit` 与审计入口 `audit_experiment_lineage`），为后续 OOS/Walk-Forward、benchmark、regime、component attribution 提供"这份证据出自哪个实验、其参数从哪里来"的身份与溯源契约。`ExperimentManifest` 的 `manifest_hash` 为 `SHA256(canonical(schema_version + governed_components))`；`experiment_id`/`parent_experiment_id`/`root_experiment_id`/`created_at` 以**结构方式**排除——canonicalizer 只接收受治理子集，而不是"接收整个 manifest 再删掉几个具名字段"，因此未来新增的任何身份字段都不会被静默扫进 hash（denylist 做法则会）。`governed_components` 是开放映射：未知 key 一律接受并照常参与 hash，`RECOGNIZED_GOVERNED_COMPONENTS` 仅为拼写可见性提供 `unrecognized_component_keys` 诊断，且刻意**不**为该 key 集合建立 anti-shrink 测试（治理覆盖面预期会增长，冻结白名单正是本设计要避免的脆弱机制）；但永久对抗测试 ID 清单仍沿用既有 anti-shrink 模式。Canonicalization 刻意保持狭窄，V0.1 只覆盖 `schema_version` 与 `governed_components`，不泛化成通用 JSON canonicalization 框架，非字符串的 component key/fingerprint 直接拒绝而非强制转换（不使用 `default=str`，避免把不支持的类型静默字符串化成"看起来稳定但无意义"的摘要）。`ParameterOrigin` 严格约束 `PRIOR_EXPERIMENT` 必须提供 `origin_experiment_id`、`LITERATURE`/`MANUAL_PRIOR` 禁止提供，且 `information_horizon_end <= declared_at`，其 fingerprint 覆盖全部六个溯源字段。`audit_experiment_lineage` 返回 `PASS`/`VIOLATION`/`INDETERMINATE` 三态裁决，由结构化 `LineageViolation`（`code`/`severity`/`message`/`evidence`，而非纯自由文本）派生并在 `__post_init__` 中交叉校验，覆盖 root invariant、child/root mismatch、self-parent、lineage cycle、missing parent，以及"同一 `experiment_id` 出现互相冲突的 manifest 定义"；审计结果确定且与输入顺序无关（violations 按规范序排序，`prior_manifests` 按事实集合消费）。完备性永不从 `prior_manifests` 反推，而由调用方通过 `LineageAuditContext.history_complete` 显式声明：这正是"父实验确实不存在"（VIOLATION）与"父实验只是没被传进本次审计"（INDETERMINATE）的分界。`experiment_id` 与 manifest 定义永久一一对应，同一 id 出现不同定义即为 lineage violation，与任何 OOS 消费状态无关——本 Foundation 完全不接受 OOS 输入，OOS burn 后果仍属未来持久化 ledger 的职责。治理类 datetime 必须 timezone-aware 并规范化到 UTC，naive 一律 `ValueError`；该约定刻意严于现有引擎（`TradeObservation`/`ExecutionObservation` 目前接受 naive），且**不**回溯改造现有引擎。信任边界显式声明：component fingerprint 在 V0.1 属调用方提供的可信输入，`manifest_hash` 只证明 manifest 是其所收到 fingerprint 的一致函数，不证明这些 fingerprint 忠实反映外部组件的真实内容。模块为纯计算叶子节点，不引入持久化、repository、OOS ledger、Walk-Forward fold、PIT universe 或 `PerformanceReport` 依赖，也未修改 Hard/Soft validation 管线或 SoftValidation source 集合。

- [新功能] Strategy Lab V0.1 新增 Validation Gate 的 Soft Validation 层（`SoftValidationStatus`/`SoftValidationSource`/`SoftValidationResult`/`SoftValidationReport` 及三个 Foundation 适配器 `soft_validation_from_parameter_stability`/`soft_validation_from_edge_concentration`/`soft_validation_from_execution_stress` 与聚合函数 `aggregate_soft_validation`）。这是与既有 Hard Validation（`ValidationReport`/`HardGatePipeline`，本次未修改）并列、独立的第二套证据体系：Hard PASS 只表示实验有资格继续验证，不代表策略已被验证，Soft 证据永远不能把 Hard PASS 改写成 Hard FAIL；本次不引入任何"validated/promotable"级别的最终晋升判断，也不实现 `logic_integrity`/`execution_causality`/`execution_reality` 中任何一个生产 Hard Gate（含 `execution_reality`——execution_stress 衡量对 fee/slippage/delay 的鲁棒性，是 causal/physical 执行有效性之外的另一件事，cost fragility 是 Soft Validation 证据，不是 Hard execution-reality failure，本次不做这条连接）。Status 分四级 `ACCEPTABLE`/`CAUTION`/`FRAGILE`/`INCONCLUSIVE`；三个适配器分别只读取对应 Foundation 引擎自身的冻结 label 字段（`stability_label`/`fragility_label`/`fragility_label`），从不读取任何数值分数、retention 或 PnL 派生值——`stability_score`/`fragility_score`/`worst_retention` 等字段即便被人为构造成与 label 矛盾的数值，也不会改变映射结果。三引擎的冻结映射表：Parameter Stability 的 `STABLE_PLATEAU`→ACCEPTABLE，`FRAGILE`/`NARROW_PEAK`→CAUTION，`UNSTABLE_CLIFF`→FRAGILE，`INSUFFICIENT_DATA`→INCONCLUSIVE；Edge Concentration 的 `DIVERSIFIED`→ACCEPTABLE，`MODERATE`→CAUTION，`CONCENTRATED`/`EXTREME`→FRAGILE，`INSUFFICIENT_DATA`/`NO_POSITIVE_EDGE`→INCONCLUSIVE；Execution Stress 的 `ROBUST`→ACCEPTABLE，`MODERATE`→CAUTION，`FRAGILE`/`EXTREME`→FRAGILE，`INSUFFICIENT_DATA`/`NO_POSITIVE_BASELINE_EDGE`→INCONCLUSIVE（"无法计算出可信 edge"与"edge 确认很差"是两个不同的判断，与两个 Foundation 引擎自身对这两者的区分保持一致）。聚合规则是对"当前出现过的 status 集合"做优先级选取（不做平均/加权/投票/复合打分，与 Hard Validation"不跨 Gate 取平均"的哲学一致）：`FRAGILE > INCONCLUSIVE > CAUTION > ACCEPTABLE`；由于是对集合做优先级选取而非按输入顺序做顺序折叠，聚合结果天然与输入顺序无关。要求`SoftValidationReport`必须恰好包含三个冻结 source（`parameter_stability`/`edge_concentration`/`execution_stress`）各一份结果，缺失、重复或未知 source 在构造时即 fail closed（`ValueError`）；`overall_status` 作为派生不变量在 `__post_init__` 中与 `results` 重新核对，即使绕过 `aggregate_soft_validation` 直接手工构造出与 results 不一致的 `overall_status` 也会 fail closed。`evidence` 仅作诊断用途（当前为各引擎自身的 `warnings` 元组），不被任何函数读回用于影响 status 判定。不依赖 PerformanceReport：不 import `performance_models`，不接受 `PerformanceReport` 参数，不读取 CAGR/Sharpe/MaxDD/绝对收益类指标——新增 AST 级别永久结构测试验证该边界，而非仅做字符串扫描（避免模块自身文档字符串里解释"不依赖"这件事本身触发误报）。不修改 `validation_models.py`、`hard_gates.py`、`adversarial_checks.py`、Parameter Stability Engine、Edge Concentration Engine、Execution Stress Engine、`performance_models.py`、`config.py` 或 `strategy_lab_validation.yaml`（无需新增配置，因为适配器只消费已冻结的 Foundation label，不重复定义任何阈值）。
- [新功能] Strategy Lab V0.1 新增 Cost / Execution Stress Test Foundation 基础实现，评估策略在更差手续费/点差假设和 +1/+2 bar 延迟成交下能保留多少已实现的执行层edge（Signal Edge 与 Execution Edge 分离，不对信号本身打分）。每笔交易的最小输入是 side + quantity + 信号时间戳 + delay-0 基准 `ExecutionPricePoint.reference_price`（一个 causal、可执行、pre-slippage 的参考价——slippage 由 Engine 自己叠加，caller 不得预先把 slippage 算进价格里），Engine 自行计算 gross_pnl = side_sign * (exit - entry) * quantity 与 net_pnl = gross_pnl - cost，不接受 caller 预先算好的 baseline_pnl，也不从价格变化反推 exposure——`quantity` 是显式必填的正数输入，只用于把价格变化换算成 PnL 单位，不属于 Position Sizing Engine。fee（`baseline_fee_cost`，仅显式 monetary commission/fees，不包含 slippage/spread）与 price slippage（`baseline_entry_slippage_bps` / `baseline_exit_slippage_bps` 两个独立可表示的 bps 值——entry 和 exit 成交不保证承受相同摩擦，因此冻结执行模型要求两者可独立表示；若价差/spread 造成的价格degradation 未反映在 reference_price 中也应归入此项，按 LONG/SHORT 方向正确作用于对应 delay 的各自 reference price：LONG entry×(1+k·entry_slip)/exit×(1-k·exit_slip)，SHORT entry×(1-k·entry_slip)/exit×(1+k·exit_slip)）分开建模、不得 double count，因此 fee 维度的加减法运算天然不会出现多空方向符号错误，符号风险完全收敛在 slippage 的价格调整方向上（Round 3 code review 修复：此前仅有单一 `baseline_slippage_bps` 字段同时作用于 entry 和 exit，已拆分为两个独立字段并新增 `test_asymmetric_entry_exit_slippage_is_applied_independently` 永久 regression test，使用真实不同的 entry/exit bps 验证各自方向的 PnL 数学，并覆盖 LONG/SHORT 镜像场景；A/F break-even、cohort-baseline、coverage、reference-path、weakest-link 逻辑均未改动，因为 slippage loss 的推导本就是 entry/exit 两项之和，对独立速率天然成立）。Scenario matrix 为 {1.0, 1.5, 2.0} cost multiplier × {0, 1, 2} bar delay 共 9 格，(1.0, 0 bar) 是唯一 realistic reference execution（delay-0 reference price + 1× slippage + 1× fee），不是 zero-friction fantasy baseline，且模块内所有 baseline/reference aggregate net PnL（顶层 eligibility gate、各 delay level 自己的 retention denominator、break-even 解析式）均来自同一条 (1.0×, 0 bar) 计算路径，不存在第二套 baseline 定义。Retention 在 (k, delay=d) 处使用同一个 eligible cohort `C_d`（有 delay=d 价格点的交易集合，`C_0` 为全部交易）同时计算 numerator 与 denominator——denominator 是该 cohort 自身在 (1.0×, 0 bar) reference execution 下的 aggregate net PnL；若该 cohort denominator ≤ 0，该 delay level 全部 retention 返回 `None` 并显式告警 `delay_{d}_cohort_baseline_not_positive`，逻辑与顶层 `NO_POSITIVE_BASELINE_EDGE` 一致，只是范围收窄到单个 delay level（Round 2 code review 修复：此前 stressed numerator 用 delay-eligible subset 但 denominator 用 full-cohort baseline，导致 coverage gap 被错误当作 execution degradation，已修复并新增永久 regression fixture）。缺失的 delay 价格点会把该交易整体排除出该 delay level 的 cohort（numerator 和 denominator 都排除），不得 fallback 到 baseline 价格：每个非零 delay level 的覆盖率（更早一层、独立的 gate）按 absolute-baseline-gross-PnL（基于全体交易）加权计算，低于 0.80 时该 delay level 全部 scenario 返回 unavailable（None）并显式告警。Execution Fragility Score = `1 - clamp(worst_retention, 0, 1)`（worst_retention 取所有 eligible scenario 中的最小值，matrix 维度的 weakest-link，而非把 cost/delay 两个独立轴的最坏值分别取值后再合并——只有真正联合评估过 (2x cost, +2 bar delay) 这类组合格才能捕捉到联合应力），原始 worst_retention 保留、可为负数，标签按 worst_retention 分级（=0.75 ROBUST / =0.50 MODERATE / =0.25 FRAGILE / <0.25 EXTREME，全部配置化，Initial V0.1 heuristic）。Break-even 沿 delay-0 参考行求解 `A - k·F = 0`（`A` 为零摩擦 raw gross PnL，`F` 为 1× 总摩擦即 slippage loss 加 fee），`break_even_cost_multiplier = A / F`（`F>0` 时可用，非 optimizer），`A`/`F` 由同一 per-scenario 计算函数在 cost_multiplier=0.0 与 1.0 两点求值推导而来，不是另一套独立公式（Round 2 code review 修复：此前 `gross_at_k1 / fee_cost` 隐含"slippage 固定在 k=1 不随 k 缩放"的假设，与实际 scenario matrix 中 cost multiplier 同时放大 fee 和 slippage 的真实公理不一致，导致 break-even 被系统性高估；已修复并新增 nonzero-slippage 永久 regression test，验证把解出的 k 代回 reference-delay stress 方程后 aggregate net ≈ 0）。Engine 自身在 `ExecutionObservation` 构造时做结构性 causality 校验（executable 时间戳不得早于对应信号时间戳、delay 0/1/2 时间戳必须非递减）——这只是 input integrity 检查，不替代未来独立的 `execution_reality` Hard Gate。不读取 PerformanceReport，不接入 Hard/Soft Gate pipeline，不修改 Parameter Stability Engine、Edge Concentration Engine、`adversarial_checks.py`、`hard_gates.py`、Signal Engine 或 Data Layer。
- [新功能] Strategy Lab V0.1 新增 Edge Concentration Engine 基础实现，评估交易在 trade/month/symbol/sector/regime 维度的集中度；冻结最小输入契约仅为 timestamp + pnl，symbol/sector/regime 均为可选维度元数据，而非必填字段。集中度分母统一使用 Gross Positive PnL（仅盈利交易之和，不用 Net PnL），Top N% 的分位人数基于盈利交易数计算，零/亏损交易填充不会稀释集中度；Fragility Score 取始终计算的 trade/month 维度，及元数据覆盖率达标的 symbol/sector/regime 各维度 normalized HHI 的最大值（weakest-link，不取平均），Top 1%/5%/Top Month/Top 3 Months/Top Symbol/Top 5 Symbols/Top Sector/Top Regime 贡献比例仅作为解释性 evidence，不直接参与打分。symbol/sector/regime 三者均采用相同的 positive-PnL-weighted metadata coverage gate：缺失该维度元数据的 positive PnL 占比单独报告（`symbol_missing_positive_pnl_share` / `sector_missing_positive_pnl_share` / `regime_missing_positive_pnl_share`），既不建立 synthetic missing bucket 也不按零风险处理；覆盖率不足时只使该维度的正式 contribution/HHI 指标返回 unavailable（None）并显式告警，不阻断 trade/month（及其余已达标维度）的正常计算。不读取 PerformanceReport，不接入 Hard/Soft Gate pipeline，现有 `assess_edge_concentration` 永久对抗回归检查（Net PnL 口径）保持不变。
- [新功能] Strategy Lab V0.1 新增 Parameter Stability Engine 基础实现，评估参数邻域的 Plateau 宽度与相邻参数悬崖比例并给出 stability_label；阈值全部来自新增 `strategy_lab_validation.yaml`（沿用 stock_radar_v2 的 value/reason/evidence 配置约定），不读取 PerformanceReport，不对"是否盈利"做判断，也未接入 Hard Gate pipeline，现有 `assess_parameter_stability` 永久对抗回归检查保持不变。
- [测试] Strategy Lab V0.1 新增永久对抗回归套件，固定拦截未来数据、参数过拟合、收益集中、成本脆弱和 Beta 伪装 Alpha 五类坏策略，并将套件显式接入 Research Radar CI；任一坏样本漏检都会使检查失败。
- [新功能] Strategy Lab V0.1 新增彼此隔离的 Validation/Performance 报告契约与固定顺序、首错即停的 Hard Gate 基础管线；业绩指标不能覆盖验证失败，尚不包含具体策略检查或回测能力。
- [文档] 冻结 Strategy Lab V0.1 规格，明确 Validation/Performance 隔离、Hard Gate、永久对抗回归测试、实现顺序、现有 Stock Radar 前置能力映射及研究专用边界。
- [新功能] Stock Radar V2 新增 QMT/Alpaca 一次运行编排入口，将真实只读 1m 数据、现有 Daily 历史、技术状态快照和雷达报告串联；配置跨日历史窗口并优先读取最新数据，显式校验市场、隔离并脱敏单标的失败，缺失数据不伪造，且不自动通知或生成交易指令。
- [新功能] Stock Radar V2 新增多周期技术状态变化雷达发布器，为已计算状态生成幂等 JSON/Markdown 研究报告；不抓取或推断行情，不通知、不入 Validation Queue、不调权、不生成 Confirmed signal 或交易指令。
- [新功能] Stock Radar V2 新增多周期技术状态点时快照、稳定分类指纹与相邻 run 变化检测；忽略指标数值小幅漂移，并保持不通知、不调权、不生成 Confirmed signal。
- [改进] Stock Radar V2 新增实时行情快照到现有 Daily/1H/15m 技术状态分析器的只读桥接；保留 forming/missing/blocked 数据质量限制，不生成 Confirmed signal 或交易指令。
- [改进] Stock Radar V2 接入现有 NotificationService/Telegram 与 stateful SQLite；每日生成 QA 报告、周一生成 Calibration 人工复核报告，真实告警…43874 tokens truncated…。
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
