Warning: truncated output (original token count: 72997)
Total output lines: 2377

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
- [改进] Stock Radar V2 接入现有 NotificationService/Telegram 与 stateful SQLite；每日生成 QA 报告、周一生成 Calibration 人工复核报告，真实告警仍需显式开启，研究候选不会被自动标记为 Confirmed signal。
- [新功能] 新增 Stock Radar V2 MVP：配置化 provider fallback 防抖与 Critical 健康状态机、独立 signal/portfolio confidence、L3 `BLOCK_NEW_POSITION` 风险门禁、统一雷达通知出口，以及持久化 Validation Queue、Daily QA、Weekly Calibration 人工复核基础结构；不修改单标的 Signal 状态，不自动修改生产权重，不包含交易执行。
- [新功能] 新增研究雷达 MarketDataAdapter V1 契约与确定性 Data Health Gate，统一行情事实模型并按数据质量限制信号权限，不包含交易执行。
- [改进] MarketDataAdapter V1 增加现有 DataFetcherManager 的只读桥接，仅规范化实时快照和日线事实，明确拒绝伪造分钟线与流式订阅能力。
- [新功能] 新增会话感知的 1m 到 15m/1h Bar Builder，支持 A 股午休边界、forming/closed 状态、缺 K 降级与迟到分钟修正替换。
- [新功能] 新增 PyTDX 只读 1m MarketDataAdapter，保留分钟时间戳并交由统一 Bar Builder 生成高周期；无 Provider 时间戳的快照仅允许 Watch，且不宣称原生流式订阅。
- [新功能] 新增 QMT/xtquant 只读 1m MarketDataAdapter，支持官方 subscribe_quote 回调、历史 K 线与快照时间戳标准化，并在部分订阅失败时撤销已创建订阅。
- [新功能] 新增健康门控 Provider Router 与只读 QMT smoke test：快照/分钟 K 在 QMT 异常或被阻断时显式降级 PyTDX，流式订阅失败不会静默变成轮询。
- [新功能] 新增美股 Alpaca 只读 1m Adapter，保留 IEX/SIP feed，统一历史、最新 bar/quote，并同时处理 bars 与 updatedBars 以修正迟到成交。
- [新功能] 新增只读 Realtime Market Data Service，按标的维护有界 1m 缓存、确定性替换修正 K 线、生成 15m/1h 快照并在活跃时段暴露 stale 健康降级。
- [改进] 美股研究报告增加估值数据健康度与可信度标记，区分实时数据和历史缓存覆盖。
- [修复] 美股研究扫描为 PE/PB 增加带时间戳的最近有效值缓存，并分别记录实时、缓存和缺失覆盖，降低 yfinance 临时缺失导致的候选排序波动。
- [修复] 美股研究扫描不再把缺失 PE/PB 误判为估值不合格并清空候选；报告新增估值字段覆盖率诊断，筛选服务在未配置 LiteLLM 备用列表时继承 Gemini 备用模型。
- [修复] 美股研究扫描为 `S&P 500 + Nasdaq 100` 股票池增加带来源和时效校验的持久缓存、覆盖率诊断与发布门控；来源降级、股票池少于 400 只或有效快照低于 80% 时不再发布候选、更新历史或发送 Telegram 提醒。
- [新功能] 美股研究扫描结果持久化为长期候选池，记录 A/B/C/D 研究等级、入选历史、研究上下文与 active/watching/retired 生命周期。
- [新功能] 美股研究扫描新增行业研究雷达，聚合候选质量、持续入选与可用 industry/board heat 数据，并在市场层数据缺失时退化为 candidate_only。
- [新功能] 美股候选池新增财报与估值快照及按 run_id 保存的历史证据，缺失数据不会覆盖上一轮有效财务状态。
- [新功能] 新增相邻有效财务快照变化检测，分离盈利趋势、估值趋势与管理层指引变化，并输出财务变化雷达。
- [新功能] 新增研究优先级事件流，将候选等级、行业强度、财务变化与催化/风险线索融合为研究注意力排序，不生成交易指令。
- [改进] 研究优先级新增事件升级、反转、指引变化与恢复 transition gate，抑制重复提醒并输出 research_priority_alerts。
- [新功能] 研究事件提醒可显式接入现有 NotificationService，复用 alert 路由、severity、dedup、cooldown 与多渠道发送诊断，默认不自动发送。
- [改进] 新增 `US Research Stateful Scan` GitHub Actions 工作流，通过 SQLite quick_check、WAL checkpoint 与 GitHub Cache 在独立 runner 间保存候选池、财务快照和研究事件历史，并提供无 API 调用的缓存往返测试。
- [新功能] 美股研究新增新闻 / 催化剂变化雷达，按 run_id 持久化事件证据并用确定性归一与近似去重识别新增催化、新风险和重复旧闻；缺失线索不会自动解释为风险解除，并接入研究优先级与提醒 transition gate。
- [新功能] 支持通过 `main.py --stocks` 一次性分析已登记板块指数，自动使用指数适用的数据与分析能力，并保持报告、历史和决策信号兼容。
- [修复] `main.py --stocks` 在解析股票列表前先 best-effort 刷新股票索引注册表，保证首次运行能吃到刷新后的指数 alias/身份；刷新失败、超时或禁用不阻断分析。
- [修复] 交易日过滤对市场未知的指数 code（如 `sh000016`/`csi930955`/`930955.CSI`）按 `market=cn` 参与 A 股休市过滤，避免休市日指数被 fail-open 保留；市场仍未知的非指数 code 继续保留。
- [修复] 指数分析将实际命中的日线数据源归因保存到历史记录，并由 Dashboard/Brief aggregate 报告展示；来源无效时保持原有输出。
- [文档] 在中英繁 README 顶部关联 DSA arXiv 论文，并新增 `CITATION.cff` 统一项目引用信息。
- [新功能] 新增数据源能力与数据集质量只读契约，提供 `/api/v1/data/overview` 和 `/api/v1/data/capabilities`，为大盘看板、数据中心、个股详情和自选 2.0 统一暴露 provider capability、dataset quality 和 source priority。
- [修复] 统一美股指数实时行情与数据能力概览为 YFinance-only 路由，避免 YFinance 失败后误用 Longbridge fallback。
- [改进] PR CI 增加文档路径检测：仅修改普通文档、非治理 Markdown 或 LICENSE 时跳过后端测试分片、Docker、Web 与桌面打包，保留轻量治理和门禁汇总；契约文档、静态 API 规格与测试 fixture 仍执行后端回归。
- [新功能] 新增 ResearchArtifact 结构化研究产物契约，在 `AnalysisReport.structured_report` 中承载 Thesis、Evidence、Invalidation Conditions、Next Actions 和 Data Quality，并提供从现有报告生成结构化产物的后端 helper 与 Web 类型。
- [修复] 同步 ResearchArtifact 与 `AnalysisReport.structured_report` 到静态 OpenAPI，避免公开 API 规格与运行时契约漂移。
- [修复] Linux/Docker 分享图补齐 Noto CJK 字体与中韩文字体栈，避免 PNG 只显示数字和英文、中文或韩文内容消失。
- [新功能] Web Chat 意图识别层新增分词模块：`web_intent_tokenizer` 六步管道（多股票全名实体扫描 → 标点/空白切分 → 代码形提取 → 市场关键词 → 无歧义关键词 → 残存 gap 多策略 DFS 匹配）把用户消息切分为携带语义标签的 Token 序列；配套 `web_intent_types` 数据字典（Token 结构、Market 枚举、21 个语义 tag、clean/extend 双词池与正则机器）。核心原则"宁可不做，不可做错"：Step 1~5 只做精确匹配，Step 6 要求整段 TAG 全覆盖（交叉验证）才产出，未覆盖片段保持空 tag 交下游 LLM 兜底；代码形 token 辨认为 `stock_code`（附 code/name/market 三元组）/ `wrong_{market}_code` / `unknown_{market}_code` 三态，token 层代码拼写统一 canonical 归一（a=6 位裸数字、hk=HK+5 位、us=大写 ticker）。意图枚举与意图识别结果随后续 `web_intent_resolver` PR 引入。新增 183 个分词单元测试。
<!-- 新条目格式：- [类型] 描述（类型取值：新功能/改进/修复/文档/测试/chore）-->
<!-- 每条独立一行追加到本段末尾，无需分类标题，合并时冲突最小 -->
- [新功能] 完善 Futu OpenD 港股数据源接入：系统设置支持 OpenD 地址、端口和港股实时数据源优先级，保留 Longbridge、AkShare、YFinance fallback。
- [测试] 增加 Futu 配置 schema、港股实时路由和 fallback 契约覆盖。

- [新功能] 建立唯一、可生成、可校验、可降级的指数身份注册表：由 `scripts/stock_index_seeds/index_registry.csv` 的 31 项 manifest 确定性合并进 `apps/dsa-web/public/stocks.index.json`，运行时唯一真源为 JSON 中通过校验的 `active=true`/`assetType=index` 行，移除 `stock_list_parser` 的 5 项硬编码白名单；支持 `--index-only` 生成与字节稳定输出。
- [新功能] 补齐显式 SH/SZ/CSI 指数 alias 收敛与 CSI 身份：`sh000300`/`000300.SH`/`sz399300`/`399300.SZ`/`000300.CSI` 均解析到 `sh000300`，`csi930955`/`930955.CSI` 解析到 `csi930955`；未登记 `.CSI` 输入返回 `unsupported`；裸数字恒为 stock 并仅通过 `matched_index` 暴露歧义。
- [新功能] 数据管理器按 SH/SZ/CSI 支持矩阵映射 provider symbol：CSI 仅 AkShare 支持（`csi{code}`），Tencent/TickFlow/Yahoo 返回空 symbol 并记录 `unsupported` provider-run，不触发指数健康熔断。
- [改进] 存储层 `_derive_canonical_id` 统一为 parser 推导（裸码=stock、显式指数=index），并新增幂等分批修复历史裸码错误 canonical 串桶（`000001`/`000016`/`000688`/`930955` 等），显式指数行与正确 stock 行不受影响，registry 为空时修复 no-op。
- [改进] Web loader 完整解压含 index 的共享 payload，但在返回给 autocomplete/popular/group 消费面前过滤 `assetType=index`，股票与 ETF 行为保持不变。
- [测试] 为生成器、loader、parser、provider 路由、存储修复与 Web 门槛补充 TDD 回归锚点。
- [修复] PR #2267 review 收敛 CSI 显式身份：将 `csi` prefix（canonical）与 `.CSI` suffix（显式 alias）在 parser/build/runtime 规范化器中分离，未登记显式 `csiNNNNNN`/`NNNNNN.CSI` 一律返回 `unsupported`（不再落入美股或猜测 SH/SZ），并防止未登记 `csi000300` 被等价成已登记 `000300.CSI` alias；存储 `_derive_canonical_id` 对 unsupported 输入返回 NULL，避免进入持久化 canonical 桶。
- [修复] 在 seed、build entry 与 runtime candidate 三层严格校验 alias 唯一性与整数 popularity：NFKC/casefold 等价 alias 跨条目冲突被拒绝（无静默覆盖），非负整数之外（小数/布尔/负值/字符串）popularity 一律拒绝，整数 `100` 保持有效。
- [修复] 收敛已登记 CSI 显式身份在 resolver、任务去重键与历史候选中的分裂：`csi930955`/`930955.CSI`/`CSI930955` 统一解析为 parser canonical `csi930955`，未登记 `csi930956`/`930956.CSI` 保持既有降级语义；`is_code_like()`、REST/watchlist 输入边界与完整 Pipeline 透传不变。
- [修复] 阻止任意更新的非 bundled 指数候选（含 legacy `static` 子集）在 remote 缺失/损坏时以 active-index 子集覆盖 bundled baseline：所有非 bundled 候选必须为 bundled active-index canonical 集合的合法超集，否则回退 bundled 并记录 WARNING。
- [新功能] 桌面端全局右上角增加更新入口，与设置页共用更新状态；普通浏览器 WebUI 不展示，且不会在挂载时重复触发后台检查。
- [修复] 桌面端右上角更新入口与设置页共用检查中状态，避免一侧检查时另一侧仍可重复触发 GitHub Releases 检查；主进程手动检查路径同步增加 in-flight 防重。

## [3.31.0] - 2026-08-23

### 发布亮点

- feat: Agent 工具调用新增按类别和单工具配置的超时契约，并补齐防重试、协作取消、并发预算与热重载一致性。
- feat: 股票名称解析、`canonical_id` 双写和 A 股指数多数据源路由共同完善股票身份与行情降级链路。
- improve: 新闻检索为空时在报告中如实披露证据边界，Anspire 默认覆盖全球区域，公共 SearXNG 实例改为显式启用。
- fix: 定时任务恢复、无报告失败反馈、通知发送和大盘复盘历史/诊断信息进一步收敛，减少静默失败与误导展示。
- security: 桌面端升级 `builder-util-runtime`，修复 CVE-2026-54673 涉及的重定向凭据头信息泄露风险。
- docs: 增加 xAI Grok 的 LiteLLM 配置示例、Grok Bot 集成说明与可复用 Skill。

### 变更明细

- [修复] 大盘复盘历史列表与详情统一展示持久化短摘要；旧记录缺少摘要时从完整 Markdown 生成无内部标记的纯文本节选。
- [修复] 大盘复盘按实际执行的生成后端和模型记录诊断，避免 Codex CLI 或 fallback 被误显示为配置模型。
- [修复] 已配置钉钉 Webhook 时不再误报“未配置通知渠道”；钉钉 Stream 仍仅用于交互，不作为定时静态推送渠道。
- [修复] WebUI/API/Desktop 以 `--serve-only` 重启后会恢复已启用的定时任务，同时保持启动时不立即执行分析；通知路由示例补充钉钉 Webhook 渠道。
- [改进] AIHubMix 注册与引流链接统一使用 inferera.com，改善中国大陆网络直连体验。
- [修复] 单股推送模式在未配置通知渠道时仍会落盘本地个股报告；CLI 启动分析若因空股票列表、个股结果全失败或本地报告保存失败而未生成报告，会显式返回失败并记录原因。
- [修复] 合并推送模式下即使个股汇总报告落盘失败，仍会先发送已有的合并通知；仅启用大盘复盘但最终未生成任何复盘内容时，分析任务会显式返回失败。
- [修复] Web/API runtime scheduler 使用跨平台独立进程执行分析，并在默认 45 分钟硬超时或服务停止后清理进程树；停止返回后不再派发新的自动任务，避免一次卡死阻断后续调度。
- [修复] SearXNG 公共实例发现的默认值由启用改为关闭：公共实例普遍存在限流、下线或不返回 JSON 的情况，默认开启会让未配置搜索 key 的用户每次分析多耗 30~60 秒且新闻面最终为空。运行时默认值、配置模板、中英文档与工作流诊断同步调整；显式设为 true 的用户行为不变。
- [改进] 新闻检索未执行或零命中时，报告中如实标注结论未纳入新闻面证据：零命中与「未配置搜索渠道」使用各自独立的文案，覆盖日报 / dashboard / brief / 个股 / 企业微信与模板渲染的详细与摘要分支、历史报告与分享导出、报告详情 API 与 Web 报告详情页，并按 `zh` / `en` / `ko` 分别本地化。此前该情况下消息面章节直接消失，读者无从区分「确实没有新闻」与「检索静默失败」。披露以本次分析实际收到的消息面证据为准，涵盖实时检索、社交情绪与本地已落库的资讯池三路来源；搜索命中数仅用于在确无证据时说明原因（未配置渠道 / 检索零命中），避免把已用到本地或社交证据的分析误报成「未纳入新闻面证据」。Agent 模式的命中数取自 Agent 实际消费的搜索工具结果，而非分析结束后为持久化情报而补打的查询。

- [新功能] Agent 工具调用支持按类别（data/search/analysis/action/market）配置默认超时，并允许单工具声明 `timeout_seconds`；有效超时按 first-wins 优先级解析（显式 per-run `tool_call_timeout_seconds` > 单工具显式 `timeout_seconds` > 类别默认 > 无限制），剩余 wall-clock 预算仅作不可突破的外层 cap，超时后返回结构化 `{"timeout": true}` 错误（标记 `retriable: false` 并写入 `non_retriable_tool_results` 防重试重复执行）供 Agent 继续执行而非中断循环（fixes #1890）。
- [修复] Agent 工具注册表（`src/agent/factory.get_tool_registry`）由模块级缓存改为按「类别超时映射的值」比对失效，规避 CPython 回收对象后地址复用（`id(config)` 相同）导致配置 reload 后的 `Config` 被误判为未变、沿用过期超时的真 bug；新增 `_coerce_config_timeout` 类型白名单，使调用方传入 `MagicMock` / 缺属性 stub / 脏字符串（如 `float(MagicMock())` 静默得到 1.0）时降级为「无类别限制」而非崩溃或强加 1 秒超时；`build_agent_executor(config)` / `build_agent_chat_executor(config)` 现已把调用方 `config` 透传给 `get_tool_registry(config)`（不再无参调用冻结首构 registry）；`main._reload_runtime_config` 与 `SystemConfigService._reload_runtime_singletons`（及 `update()`→`reload_now` 路径）在配置热重载时调用 `reset_tool_registry()` 强制重建；回归测试补充「传入新 config 后 registry 重建」「reload 后新超时应生效」及「builder 透传 config」三类场景（#1890 的 review follow-up，闭环 OR-COM-dd1e8fa7 / OR-COM-bff42110）
- [修复] Agent 工具超时 review 闭环（fixes #1890 的 4 个 blocker）：超时解析由 min 契约改为 first-wins（显式 per-run `tool_call_timeout_seconds` > 单工具 `ToolDefinition.timeout_seconds` > 类别默认 > 无限制，剩余 wall-clock 预算只作不可突破的外层 cap；research 路径不再传 `tool_call_timeout_seconds` 以免覆盖类别限制）；超时结果标记 `retriable: false` 并写入 `non_retriable_tool_results` 阻断 LLM 同调用重试重入，且超时触发时为仍在后台运行的 handler 武装协作取消信号（`is_tool_cancellation_requested()` 与既有 `check_tool_execution()` 检查点均响应，handler 从不轮询则行为不变），作为 review 要求的「handler 内协作取消」缓解，规避 Python 线程无法 force-stop 导致的重复执行与副作用；`_coerce_config_timeout` 对 `inf`/`nan`/负数降级为「无限制」，根绝 `future.result(timeout=inf)` 触发 `OverflowError`；`get_tool_registry` / `reset_tool_registry` 加 `threading.Lock` 双检锁，且重建后返回本次构建的局部 registry（而非全局缓存），消除并发重建竞态与跨调用超时串扰；`@tool` 装饰器将 `ToolPolicy.timeout_seconds` 折叠进 `ToolDefinition` 单一来源；统一单/并行工具超时包装（单一 executor + deadline 驱动的 wait loop，消除并行路径嵌套 executor 与线程翻倍，duration 精确到各工具自身超时值），并新增快慢工具混合并行回归；同步 `docs/full-guide_EN.md` 的超时环境变量文档；测试覆盖 first-wins、non-retriable、协作取消接线、finite 校验、缓存线程安全与快慢混合并行。
- [修复] 按最新 review 复核收敛 3 处正确性问题（OR-COM-7f3d3f5b / 3d6b61f8 / a1e8b0c2）：`BaseAgent._filtered_registry()` 携带源 registry 的类别超时映射（工具子集仍生效类别上限，不再绕过 #1890 类别超时）；并行批次 >5 时排队调用的 per-tool 超时自 worker 实际开始起算（不再提交即烧预算导致对未启动调用的假超时）；`get_tool_registry()` 缓存命中快路径在锁内读取一致对（消除与 `reset_tool_registry()` 竞态返回 `None` 或错配 registry）。新增对应回归测试。
- [新功能] 股票名称解析引擎重构增强：新增 `resolver_name_to_code_list()` 公开 API，返回按市场排序（A 股→港股→美股）的 `Stock` 候选列表（最多 5 个），新增 `US_stock_code_match()` 匹配美股 ticker（1~5 位字母且仅限本地库已存在代码，避免 hello/open 等英文词误判为股票）；AkShare 全量 A 股数据经幂等 `extend_AkShare()` 合并进全局 `stockDB`（30 分钟缓存 + 失败 5 分钟退避 + Future 单飞：TTL 过期 stale-while-revalidate 零等待、冷启动等待上界由拉取超时推导（拉取经子进程封顶 25s）、worker 先清账唤醒等待者再做日志/落盘（finally 兜底 BaseException）、成功拉取落盘 `data/cache` 跨重启复用，非中文输入跳过网络扩展），匹配策略升级为「精确→子串（≥2 汉字）→拼音子串（≥5 字母）→difflib 模糊（0.8，单字误写 0.7 兜底）」；`resolve_name_to_code()` 保持既有本地优先语义（本地精确命中零网络，调用方离线低延迟契约不变），跨市场候选能力由 `resolver_name_to_code_list()` 独立提供；解析全链路线程安全（`stockDB` 读写加锁、名称/拼音索引随库变更自动失效），新增 40 个单元测试覆盖精确/跨市场排序/子串/拼音/模糊/幂等扩展/失败退避/多候选场景。
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
- fix: 补齐美股实时行情 PE/PB 估值字段、多市场工具描述和 macOS Gatekeeper 安装排障说明。

### 新功能

- 新增 #1743 Phase 6 Codex App Server single-agent 问股实验原型，仅开放三个既有只读 Tool Surface 工具；默认 LiteLLM、Multi Agent、Deep Research、普通报告、定时任务与 Phase 1/2 `codex_cli` 路径保持不变。
- Web AI 建议页支持确认保存基于历史报告快照重算的决策风格信号，以 created/existing/refreshed 区分新建、原样复用和既有记录续期或维度补齐，并复用 profile-aware 去重与失效语义。
- 多策略观点结构化输出第一版新增策略观点标准化、基础冲突检测与聚合 metadata，作为 #1964 的阶段性基础契约；本版本不声明完成并发执行、完整策略调度 MVP 或前端完整多语言展示。

### 改进

- Codex 设置页仅检查配置、命令和所需协议是否允许尝试，用户保存后可直接提问；Chat 以服务端 `accepted` 事件提交问题并按实际 backend 停止。
- Web 报告页输入数据块沿用状态、来源、告警和说明字段，在说明中补充异常影响、处理建议与诊断码，并区分报告页资讯和本次分析输入。
- 更新 Anspire 数据源的项目展示信息，并将 `get_stock_info` 工具说明从 A 股限定修正为覆盖 A 股、港股和美股。

### 修复

- 修复 MiniMax 分析与渠道 JSON 测试把推理内容和最终文本拼接后导致结果无法解析、无法持久化的问题；字符串响应仅剥离开头完整的 `<think>` 包装，并保留 JSON 内容中的同名字面标签。
- 修正多 Agent 内部 runtime facts 的 timeout 归因，并让 risk application 覆盖后的 dashboard 决策字段及一句话核心结论基于 post-risk signal 完成 finalization。
- 收敛多策略综合器语义：正确处理 Signal 枚举、缺失 signal、有效 opinion_count 和 deterministic synthesis，并兼容历史与外部 dashboard 的宽松字段形状。
- Codex 问股只接受 App Server 明确完成的终态回答，并统一整体时限、累计输出、事件、工具预算和进程回收边界。
- `codex_cli` 普通分析显式固定无人值守批准策略与只读沙箱，避免新版 Codex 在非交互任务中因请求人工批准而中断。
- yfinance 美股实时行情补齐 `pe_ratio` 和 `pb_ratio`，供估值分析和下游报告使用。

### 文档

- 补充 macOS 未签名、未公证 DMG 被 Gatekeeper 拦截时的架构选择、安全排查与官方安装包临时放行步骤。

## [3.26.1] - 2026-07-12

### 发布亮点

- feat: Web 首页新增历史、自选与今日工作区，支持批量分析、今日覆盖判断和评分排行。
- feat: 新增 A 股市场结构与题材主线上下文，并贯通报告、Agent、DecisionSignal 与 Web 展示。
- feat: 飞书支持文件形式推送报告，多 Agent 支持子 Agent 独立超时钳位。
- feat: 补齐内部 DSA Tool Surface、DecisionAgent 分歧摘要和 DecisionSignal profile 契约。
- fix: 统一报告动作口径，修复按股票代码批量删除历史记录和通知理由静默截断问题。
- fix: 改进 Web、桌面端、数据源缓存及发行包资源的稳定性。

### 新功能

- 新增 A 股市场结构与题材主线上下文，并在报告、Agent、DecisionSignal 和 Web 市场位置卡中复用。
- 飞书推送新增文件上传能力：`FeishuSender.send_feishu_file(file_path)` 通过 App Bot SDK (`im.v1.file.create`) 上传文件并发送文件消息；Webhook 模式回退为发送文件内容文本；新增 `FEISHU_SEND_AS_FILE=true` 配置开关，开启后飞书以文件形式发送报告而非文字消息。
- 多 Agent 编排 Pipeline 新增子 Agent 独立超时钳位：支持 6 个环境变量为 TechnicalAgent、IntelAgent、RiskAgent、DecisionAgent、PortfolioAgent、SkillAgent 各自配置独立硬上限，互不挤占配额；默认 0 表示关闭钳位。

### 改进

- 为 multi-agent DecisionAgent 增加内部低敏分歧摘要输入管线，作为 #1904 P1 解释输出的…22997 tokens truncated…升到 `8192`，降低长复盘输出因 `MAX_TOKENS` 提前截断导致内容未完成的概率。
- ⏰ **内置定时调度器感知 SCHEDULE_TIME 运行时变更** — 调度器现在会在运行中感知 WebUI 保存后的 `SCHEDULE_TIME` 变化，并在下一轮检查时重绑 daily job。
- 🪟 **Windows Release 渠道编辑器保留 MiniMax 模型前缀** — 渠道模式下填写 `minimax/<模型名>` 时，后端归一化与 Web 设置页运行时模型列表都会保留该值原样，不再误改写成 `openai/minimax/<模型名>`。
- 🤖 **Discord 入站 Webhook 补齐 Ed25519 验签** — `DiscordPlatform` 现在会基于 `X-Signature-Ed25519`、`X-Signature-Timestamp` 和原始请求体校验 Discord Interaction 签名；缺失签名头、公钥格式非法或签名不匹配时直接拒绝请求，同时对 timestamp 做 ±5 分钟时效窗口校验以防御重放攻击。
- ⚙️ **STOCK_GROUP_N / EMAIL_GROUP_N 配置关系明确化** — 明确与 `STOCK_LIST` 的关系，并在配置校验中对超出 `STOCK_LIST` 的邮件分组给出 warning。
- 🗓️ **断点续传改按市场时区和交易日历判断**（fixes #880）— 股票数据存在性检查不再直接使用服务器自然日，而是按 A 股 / 港股 / 美股各自市场时区解析"最新可复用交易日"。
- 📨 **单股推送模式不再并发复用共享通知实例** — `StockAnalysisPipeline.run()` 现在会保留个股分析并发，但把 `SINGLE_STOCK_NOTIFY=true` 下的即时通知挪到结果收集侧串行发送。
- 🔇 **实时行情降级提示收口为单次告警** — 分析主流程获取股票名称时不再提前触发一次实时行情查询，只有在全部数据源都不可用时才提示已降级为历史收盘价继续分析。
- 🔍 **A 股中文资讯搜索恢复中文优先** — `search_stock_news()` 现在会在首个 provider 主要返回英文资讯时继续尝试后续引擎，并将同批结果中的中文资讯排到前面。
- 🔒 **并发执行时共享状态补齐统一加锁** — 修复并发执行时共享状态缺少统一加锁的问题，避免多线程场景下的数据竞争。

### 测试

- 🧪 **补充设置页版本信息回归测试** — 新增 Web 设置页版本信息渲染断言，并覆盖占位版本 `0.0.0` 自动回退为构建标识的逻辑。
- 🧪 **UI 治理与关键路径回归补强** — 补充 `SidebarNav`、`ChatPage`、`BacktestPage` 等组件测试，并新增 UI governance 守卫，持续防止交互元素重新引入原生 `title` 属性或旧 `input-terminal` 样式回流。同步更新 smoke / markdown drawer 相关验证，覆盖主题升级后的关键主链路。

## [3.11.0] - 2026-03-27

### 发布亮点

- 🎨 **Web 工作台完成一轮 UI 统一与双主题升级** — 首页、问股、回测、持仓和设置页进一步收口到统一设计 token、输入表面和状态表达；新增完整浅色主题，并支持浅色 / 深色一键切换与持久化保存。
- 🤖 **Bot / Agent 能力重新补回主分支** — 恢复 `/history`、`/strategies`、`/research` 等命令，`/ask` 继续支持多股对比与组合视角；Deep Research、事件监控与 schedule 轮询链路重新接回主线能力。
- 🔒 **安全性与运行稳态同步补强** — 修复 `X-Forwarded-For` 限流绕过风险，恢复 LiteLLM 官方 PyPI 安装路径，Tushare 初始化不再依赖本地 SDK，降低 Docker、桌面打包和环境重建时的脆弱点。
- 🖥️ **日常使用细节继续打磨** — 修复首页港股自动补全提交、登录页首屏主题闪烁、历史长股票名重叠，以及 Telegram Markdown 解析失败时整条通知发送中断等问题。

### 新功能

- 🎨 **全新浅色主题与双主题切换上线** — Web 工作台新增完整浅色主题，并支持在侧边栏中一键切换浅色 / 深色模式；主题选择会持久化保存，刷新页面后仍保持当前偏好。此次升级不是局部配色微调，而是对卡片层级、边界对比、输入表面、状态提示和页面背景做了一整套 light theme 重绘。
- 🤖 **补回主分支缺失的 Agent / Bot 能力** — `#648` / `#649` 已重新补回 `main`：Bot 恢复 `/history`、`/strategies`、`/research`，`/ask` 保留多股对比与组合视角；Deep Research 与 Event Monitor 的配置重新在 Web 设置页可见并可编辑，schedule 模式也重新接入事件告警轮询。

### 改进

- 🖥️ **核心页面统一到同一套工作台视觉语言** — `Home / Chat / Backtest / Portfolio / Settings` 进一步收口到共享设计 token、`input-surface` 输入体系、空态/错误态表达和抽屉遮罩语义，减少页面之间的视觉割裂与局部私有样式漂移。
- 💬 **问股交互可达性与反馈增强** — 问股页补强了会话导出、通知发送、消息复制、历史删除与追问上下文提示；AI 回复操作不再过度依赖 hover，触屏设备和小屏场景下也能直接触达关键按钮。
- 📊 **回测与持仓页表面和状态表达继续标准化** — 回测页筛选控件、布尔状态、结果表格与汇总卡片统一到共享输入/状态原语；持仓页的导入反馈、汇率刷新提示、空态与警示信息进一步归口到共享组件，减少页面级重复实现。
- 🧭 **导航与页面壳层协同优化** — 侧边栏主题切换、问股完成角标、移动端抽屉遮罩和主内容滚动契约进一步统一，首页、问股和回测在桌面端与移动端的切页体验更稳定。

### 测试

- 🧪 **UI 治理与关键路径回归补强** — 补充 `SidebarNav`、`ChatPage`、`BacktestPage` 等组件测试，并新增 UI governance 守卫，持续防止交互元素重新引入原生 `title` 属性或旧 `input-terminal` 样式回流。同步更新 smoke / markdown drawer 相关验证，覆盖主题升级后的关键主链路。

### 修复

- 🌗 **Web 首屏默认主题预设为深色** — `apps/dsa-web/index.html` 现在会在 React 挂载前读取本地保存的主题偏好；若没有已保存值，则立即给 `<html>` 预设 `dark` 并同步 `color-scheme`，避免首页和登录页首屏先闪出浅色主题。
- 🔐 **登录页独立主题层收口** — 登录页输入框、标签、切换按钮和按钮文案现在使用独立的 `--login-*` 视觉 token，不再继承全局浅/深主题文字色；即使浏览器缓存了浅色主题，登录页仍保持稳定的深色视觉与青色密码输入表现，避免密码圆点和文案落成黑色。
- 🖥️ **首页港股代码输入修复** — Web 首页分析输入框现在可正确接受港股代码与自动完成选中的港股项，补齐 `00700.HK` / `HK00700` 等格式识别，避免提交时误报“请输入有效的股票代码或股票名称”。

- 🔒 **认证限流 X-Forwarded-For 取值修复（CWE-345）**（#841 / #842）— `get_client_ip()` 从取 `X-Forwarded-For` 最左值改为最右值，防止攻击者通过伪造首部旋转限流桶绕过暴力破解保护；仅影响 `TRUST_X_FORWARDED_FOR=true` 且单层可信反向代理的部署场景，多级代理环境需按部署文档评估配置。
- 📦 **恢复 LiteLLM 官方 PyPI 安装并锁定安全上限** — `requirements.txt` 重新使用 `pip install litellm` 的官方 PyPI 安装路径，并在保留历史最低要求 `>=1.80.10` 的同时增加 `<1.82.7` 的安全上限，避免误装已被移除的 `1.82.7` / `1.82.8` 风险版本；Windows 桌面打包脚本也同步回退到标准 `pip install -r requirements.txt` 链路，减少特殊下载分支带来的维护成本。
- 📨 **Telegram Markdown 解析失败回退纯文本**（fixes #850）— `src/notification_sender/telegram_sender.py` 现在会在 Telegram 返回 `HTTP 400` 且包含 `can't parse entities` / Markdown 解析错误时，自动去掉 `parse_mode` 后重试纯文本发送，避免 `*ST` 等正文内容直接导致整条通知失败。
- 🔢 **A 股同码实时行情保留交易所提示**（fixes #852）— `DataFetcherManager` 与 `TushareFetcher` 现在会保留 `SZ000001` / `000001.SZ` 这类显式沪深提示，旧版 Tushare 实时行情降级分支不再把深市 `000001` 误判成 `sh000001` 上证指数。
- 🎯 **多 Agent 次优买点不再盲目复制理想买点**（fixes #851）— 当多智能体结果缺少独立 `secondary_buy` 时，仪表盘现在优先展示 `N/A` 而不是把 fallback 值硬拷贝成与 `ideal_buy` 完全相同，减少误导性的双买点展示。
- 🧩 **Tushare 初始化不再强依赖本地 SDK 包** — `TushareFetcher` 现在直接使用内置 HTTP client 访问 Tushare Pro，不再在启动阶段先 `import tushare` 才能初始化；修复了 Docker、桌面打包或环境重建后因缺少 `tushare` 包而提前报 `No module named 'tushare'` 的问题，并补充对应回归测试。
- ⚙️ **`daily_analysis` 工作流补齐 `DEEPSEEK_API_KEY` 映射** — GitHub Actions 每日分析工作流现在会正确透传 `DEEPSEEK_API_KEY`，避免云端任务配置了密钥却在运行时拿不到对应环境变量。
- 🖥️ **历史列表过长股票名称截断与悬停展示**（fixes #815）— 历史列表中过长的股票名称, 现在会按字符类型自动截断（英文15/中文8/混合10字符），默认显示截断结果，悬停时展示完整名称；解决 1920x1080 分辨率下股票名称与右侧状态标签文字重叠的问题。新增 `stockName.ts` 工具函数并补充对应测试。

### 文档

- 🧾 **README 捐赠入口更新为小红书二维码** — README 及中英文说明中的赞助入口更新为小红书二维码素材，保持展示口径一致。

## [3.10.1] - 2026-03-24

### 新功能

- 🔔 **Web 端分析推送通知开关**（#808）— 首页分析按钮旁新增「推送通知」复选框，默认勾选；取消勾选时本次分析不发送 Telegram/企业微信等推送。API `POST /api/v1/analysis/analyze` 新增 `notify` 字段（`bool`，默认 `true`），不传时行为与修改前一致，Bot 和定时任务不受影响。

### 改进

- 🖥️ **问股 / 回测页面布局与壳层协同优化** — 统一 Chat / Backtest 页面容器、共享 UI 状态和跟随问答交互路径，移除部分硬编码高度限制，让导航框架内的填充与滚动行为更连贯。
- 🎨 **全局视觉与共享组件继续收敛** — Light theme 引入动态 HSL 阴影体系，统一侧边栏激活态、告警组件对比度和聊天气泡样式，并把部分零散内联样式收口为语义化 CSS 变量，提升一致性与可维护性。

### 修复

- 🖼️ **系统设置智能导入文件选择恢复** — 修复了“系统设置 > 基础设置 > 智能导入”模块中 “选择图片 / 选择文件” 两个按钮点击无响应的问题。
- 🖥️ **移动端滚动与交互层级修复** — 解决主题切换菜单在移动端被主内容遮挡的 z-index 冲突，并恢复首页长报告场景下的正常纵向滚动，不影响其他页面现有滚动行为。
- 🧾 **Markdown 纯文本复制清洗增强** — 改进纯文本导出算法，复制分析报告时会更稳定地清除表格分隔符等 Markdown 痕迹，提升分享和归档内容的纯净度。
- 🧠 **Trading philosophy injection 覆盖 legacy + Agent 全链路**（#810）— `GeminiAnalyzer`、单 Agent 模式和 skill-aware Prompt 现在共享同一套策略注入状态；只有隐式回落到内置默认 `bull_trend` 时才保留旧的趋势型提示，显式策略选择或自定义默认 skill 不再被偷偷叠加 `MA5>MA10>MA20` 多头基线。
- 🛠️ **后端 CI 依赖安装链路稳态化**（#835）— 拆分 backend gate 阶段、为依赖安装增加重试，并把 CI 用的 `litellm` 安装来源调整为更稳定的 GitHub 源，降低依赖解析抖动导致的 backend gate 偶发失败。
- 🪟 **Windows 桌面发版构建恢复 LiteLLM 安装兼容性** — `scripts/build-backend.ps1` 现在会先过滤 `requirements.txt` 中的 LiteLLM GitHub 源包，再下载对应 tag 的 zipball 到本地移除上游可选 `enterprise/` 目录后安装，绕过 Windows runner 上 Poetry 构建 wheel 时把目录误当文件打包导致的失败；同时补上 `pip install` 退出码检查，避免依赖安装失败后只在后续 `python-multipart` 校验阶段才暴露成次生报错。

### 测试

- 🧪 **问股 / 回测 / 智能导入回归覆盖补齐** — 同步更新 E2E 冒烟期望，补充 `DashboardStateBlock`、Chat 页、智能导入文件选择与相关交互回归断言，确保近期 UI 调整后的关键路径仍可稳定通过。

## [3.10.0] - 2026-03-24

### 发布亮点

- 🔎 **自动补全与索引工具扩展到三市场** — 补全索引生成链路现在同时覆盖 A 股、港股、美股，配套新增 Tushare 股票列表抓取工具与更完整的静态索引数据，让首页搜索入口从“能用”走向“更全、更稳”。
- 🖥️ **Dashboard 与报告查看体验继续收口** — 首页 Dashboard 面板、状态边界、字体层级和完整报告表格密度完成一轮统一；报告详情也补齐了 Markdown/纯文本复制与更可靠的按钮交互，减少历史报告查看与分享时的摩擦。
- 🤖 **Agent skill 与市场语义边界更清晰** — skill bundle、默认策略、回测汇总语义和兼容接口进一步收敛；同时分析 Prompt 不再默认写死 A 股上下文，美股和港股分析也能按各自市场规则生成更贴切的内容。
- ⏰ **定时与桌面配置能力更贴近真实使用场景** — 桌面端支持 `.env` 导入导出；`python main.py --schedule --stocks ...` 也不再把启动时股票快照错误带入后续计划执行，定时任务会跟随最新保存的 `STOCK_LIST`。
### 新功能

- 💾 **桌面端 `.env` 备份/恢复入口**（#754）— 桌面模式下的系统设置页新增 `导出 .env` / `导入 .env` 按钮，可直接备份当前已保存配置，或把备份文件中的键值合并恢复到当前桌面端 `.env`；导入沿用现有 `config_version` 冲突保护与运行时重载链路，不改变现有桌面端便携模式路径。
- 📊 **Tushare 股票列表获取工具** — 新增 `scripts/fetch_tushare_stock_list.py`，支持从 Tushare Pro 获取 A股、港股、美股列表信息并保存为 CSV，配有分页读取、智能限流、错误处理和进度提示；新增对应使用文档 `docs/TUSHARE_STOCK_LIST_GUIDE.md`。
- 🔎 **索引生成脚本多市场支持** — `generate_index_from_csv.py` 重构为支持 Tushare 和 AkShare 双数据源，同时覆盖 A股、港股、美股三个市场；新增按市场分类的别名映射（A股、港股常见别名，美股常用股票英文缩写）；添加 `--source` 参数切换数据源、`--test` 参数验证模式；严格过滤美股 DUMMY 记录。
- 🔎 **索引生成脚本增强** — `generate_stock_index.py` 新增 `--test`/`-t` 测试模式和 `--verbose`/`-v` 详细输出模式，添加市场分布统计，优化 JSON 输出格式。
- 📋 **首页完整报告支持双模式复制** — 历史报告详情头部新增“复制 Markdown 源码”和“复制纯文本”工具按钮；前者保留原始 Markdown 结构，后者去除常见 Markdown 格式符号，方便分享、归档和跨报告比对。复制按钮文案会跟随 `REPORT_LANGUAGE` 保持中英文一致，避免英文报告页出现中文固定文案。
- 🧩 **个股分析页补齐关联板块展示**（#669）— A 股分析写路径现在会把 `belong_boards` 一次性写入 `fundamental_context` / `fundamental_snapshot`，结构化报告详情同步新增 `belong_boards` 与 `sector_rankings` 字段，Web 个股分析页首屏可直接展示所属板块及其是否命中当日板块涨跌榜；无数据时保持 fail-open 隐藏，不影响现有分析主流程。

### 改进

- 🖥️ **Dashboard 面板统一化（PR7-2）** — 新增 `DashboardPanelHeader` 和 `DashboardStateBlock` 作为历史、报告、资讯、任务和透明度等面板的通用组件；统一了各面板标题层级、加载/空态/错误态和 CSS 变量 token。
- 🖥️ **HomePage 状态边界收口（PR7-2）** — 引入 `useHomeDashboardState` hook，集中 `stockPoolStore` 状态选取逻辑，移除 `HomePage` 中重复的本地状态派生和回调定义。
- 🧭 **Agent skill 统一到单一配置语义** — Multi-Agent runtime、API、Web chat 和配置元数据统一围绕 `skill` 概念收敛；`/api/v1/agent/skills` 成为主发现入口，`AGENT_SKILL_*` 成为主配置面，内置 skill 元数据也开始声明默认启用、排序优先级、market regime tag 等信息，减少默认策略散落在代码里的隐式耦合。
- 🔎 **自动补全索引数据更新** — 重新生成 `stocks.index.json`，涵盖 A股、港股、美股三个市场，提升自动补全覆盖率。
- 🧾 **Dashboard 字体与完整报告表格密度微调** — 收敛首页侧栏、空状态、历史操作区的字体层级，并将完整 Markdown 报告表格 `th/td` 的内边距调整到更紧凑的 4-6px 区间，让信息密度与现有 Dashboard 视觉节奏更一致。

### 修复

- ⏰ **定时模式不再锁定启动时 CLI 股票快照** — `python main.py --schedule --stocks ...` 现在不会让后续计划执行沿用启动时的旧股票列表；定时任务每次触发前都会重新读取最新保存的 `STOCK_LIST`，确保 WebUI 或 `.env` 更新后的自选股配置能参与后续推送。
- 🌍 **LLM Prompt 按股票市场动态注入上下文** — 分析链路不再把市场规则写死成 A 股；系统 Prompt 会根据股票代码识别 A 股、港股或美股，并注入对应的角色描述与交易规则提示，减少跨市场分析出现口径错位或结论失真的问题。
- 🔎 **美股自动补全复用 ticker 去重** — `generate_index_from_csv.py` 在导入 Tushare `us_basic` CSV 时会先按 `ts_code` 折叠复用的美股 ticker，优先保留更可能仍在使用的记录，避免 `stocks.index.json` 出现重复 `canonicalCode` 后让 Web 自动补全展示历史名称或提交歧义代码。
- 🧾 **Web 报告详情复制交互稳定性修复**（#749）— `ReportDetails` 中“原始分析结果 / 分析快照”的复制按钮补齐可点击层级，避免被下方 JSON 内容覆盖；两个面板的复制提示也改为各自独立，不再出现复制一个后两个按钮同时显示“已复制”的误导反馈。
- 📊 **Agent skill 回测与兼容接口语义收敛** — `get_skill_backtest_summary` 现在要求显式传入 `skill_id`，缺失时返回明确校验提示；仓库尚未持久化真实 skill 级汇总时会返回明确的 unsupported/info 响应，并保留 `normalized` 与 `*_pct` 兼容字段，避免沿用 overall 指标误导 Agent 或用户。
- 🔧 **Skill 默认选择与兼容层行为加固** — `allowed-tools` 会继续仅作为 `SKILL.md` bundle 元数据保留，不再泄露到运行时工具选择；`/api/v1/agent/strategies` 恢复旧 payload 形状；显式传入 `skills: []` 时会清空陈旧上下文；当用户明确选择策略 skill 时不再偷偷叠加默认 bull-trend，而在 `AGENT_SKILLS` 为空时则统一只回落到单一主默认 skill。

### 测试

- 🧪 **Dashboard 组件测试覆盖率扩展（PR7-2）** — 新增 `ReportNews` 和 `TaskPanel` 测试；对 `HistoryList`、`ReportDetails`、`HomePage`、`useDashboardLifecycle` 和 `stockPoolStore` 增强了断言覆盖，包括删除回退、移动端抽屉和任务生命周期等场景。
- 🧪 **多市场索引生成测试补齐** — 新增 `tests/test_generate_index_from_csv.py`，覆盖 Tushare/AkShare 双数据源解析、多市场判断、美股 DUMMY 过滤与重复 ticker 去重等核心路径。
- 🧪 **关联板块写入与 API 契约回归** — 新增 `tests/test_pipeline_related_boards.py`，并补充分析历史与分析接口契约测试，确保 `belong_boards` / `sector_rankings` 只做增量扩展且保持 fail-open。
- 🧪 **定时模式股票列表语义回归测试** — 新增 `tests/test_main_schedule_mode.py`，覆盖定时模式忽略启动时 `--stocks` 快照、单次运行仍保留 CLI 股票覆盖的边界场景。

### 文档

- 📘 **新增 Tushare 股票列表工具文档** — 新增 `docs/TUSHARE_STOCK_LIST_GUIDE.md`，说明股票列表抓取工具的使用方法、数据格式和常见问题。
- 🌍 **补齐定时模式与关联板块的双语说明** — `docs/full-guide.md` / `docs/full-guide_EN.md` 现在明确说明 scheduled mode 会在每次执行前重新读取 `STOCK_LIST`，并同步补充个股关联板块展示能力说明，减少配置预期偏差。
- 🧭 **调整 Agent 术语兼容文案** — README、双语文档、设置页与问股界面继续以“策略”作为用户入口主称呼，同时补充 `skill` 作为内部统一命名，降低迁移期理解成本。

## [3.9.0] - 2026-03-20

### 发布亮点

- 🤖 **模型链路与报告语言更灵活** — Agent 现在可以通过 `AGENT_LITELLM_MODEL` 独立选择模型链路，普通分析与 Agent 报告也可通过 `REPORT_LANGUAGE=zh|en` 输出统一语言，减少“英文内容 + 中文壳子”这类混排问题，并允许团队分别权衡主分析与 Agent 的成本、速度和能力。
- 🔎 **首页分析体验完成一轮闭环优化** — 首页新增 A 股自动补全，支持代码、中文名、拼音和别名检索；同时 Dashboard 状态收口到统一 store，历史、报告、新闻与 Markdown 抽屉的交互更稳定，“Ask AI” 追问也会优先携带当前报告上下文。
- 💬 **通知与检索能力继续外扩** — 新增 Slack 一等通知渠道；SearXNG 在未配置自建实例时可以自动发现公共实例并按受控轮询降级；Tavily 时效新闻链路修复后，严格时效过滤不再错误丢光有效结果。
- 💼 **持仓与市场复盘链路更稳** — A 股 market review 可选接入 TickFlow 强化指数与涨跌统计；持仓账本写入改为串行化以缩小并发超卖窗口；汇率刷新入口和禁用态提示也更加清晰，减少用户误判。

### 新功能

- 🔎 **Web 股票自动补全 MVP** — 首页分析输入框新增本地索引驱动的自动补全，支持股票代码、中文名、拼音和别名匹配；选中候选后会提交 canonical code，并透传 `stock_name`、`original_query`、`selection_source` 到分析请求、任务状态和 SSE 事件；索引加载失败时自动退回旧输入模式，不阻断原有提交流程。同步补充了静态索引加载器、索引生成脚本和前后端契约测试。分阶段进行开发，第一阶段仅支持 A 股。
- 💬 **Slack 一等通知渠道** — 新增 Slack 原生通知支持，同时支持 Bot Token 和 Incoming Webhook 两种接入方式；同时配置时优先使用 Bot API，确保文本与图片发送到同一频道；Bot Token 模式支持图片上传（raw body POST，不使用 multipart）；新增 `SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID`、`SLACK_WEBHOOK_URL` 配置项，GitHub Actions 工作流同步补齐对应 Secrets 传递。
- 🌍 **报告输出语言可配置**（Issue #758）— 新增 `REPORT_LANGUAGE=zh|en`，默认 `zh`；语言设置会同步注入普通分析与 Agent Prompt，并覆盖 Markdown/Jinja 模板、通知 fallback、历史/API `report_language` 元数据及 Web 报告页固定文案，避免“英文内容 + 中文壳子”的混合输出。
- 🚀 **Agent 与普通分析模型解耦**（Issue #692）— 新增 `AGENT_LITELLM_MODEL`（留空继承 `LITELLM_MODEL`，无前缀按 `openai/<model>` 归一）；Agent 执行链路与 `/api/v1/agent/models` 的 `is_primary/is_fallback` 标记改为基于 Agent 实际模型链路；系统配置与启动期校验补齐 `AGENT_LITELLM_MODEL` 的 `unknown_model/missing_runtime_source` 检查；Web 设置页新增 Agent 主模型选择并与渠道模式运行时配置同步。
- 🔎 **SearXNG 公共实例自动发现与受控轮询**（#752）— 新增 `SEARXNG_PUBLIC_INSTANCES_ENABLED`，在未配置 `SEARXNG_BASE_URLS` 时默认从 `searx.space` 拉取公共实例列表，并按受控轮询顺序选择实例；同次请求内遇到超时、连接错误、HTTP 非 200 或无效 JSON 会自动切换到下一个实例。已配置自建实例的用户保持原有优先级与语义不变；`daily_analysis` GitHub Actions 工作流也已支持显式透传该开关并在启动日志中展示当前状态。
- 📈 **TickFlow market review enhancement** (#632) — 新增可选 `TICKFLOW_API_KEY`；配置后，A 股大盘复盘的主要指数行情优先尝试 TickFlow；若当前 TickFlow 套餐支持标的池查询，市场涨跌统计也会优先尝试 TickFlow。失败或权限不足时立即回退到现有 `AkShare / Tushare / efinance` 链路；板块涨跌榜回退顺序保持不变。接入层同时适配了真实 SDK 契约：主指数查询按单次请求上限分批拉取，并将 TickFlow 返回的比例型 `change_pct` / `amplitude` 统一转换为项目内部的百分比口径。

### 改进

- **Dashboard state slice and workspace closure** — moved Home / Dashboard state into `stockPoolStore`, consolidated history selection, report loading, task syncing, polling refresh, and markdown drawer handling under a single state slice.
- **Dashboard panel standardization** — kept the current dashboard layout contract stable while unifying history, report, news, and markdown presentation with shared tokens, standardized states, and bounded in-panel scrolling for the history list.
- **Dashboard-to-chat follow-up bridge** — routed “Ask AI” follow-ups through report-context hydration instead of direct cross-page state coupling, while keeping chat sends usable when enriched history context is still loading.
- 💼 **持仓账本并发写入串行化**（#742）— 持仓源事件写入/删除现在会在 SQLite 下先获取串行化写锁，减少并发卖出把超售流水写入账本的窗口；直接持仓写接口在锁竞争时返回 `409 portfolio_busy`，CSV 导入保持逐条提交并把 busy 计入 `failed_count`。
- 💱 **持仓页汇率手动刷新入口补齐**（#748）— Web `/portfolio` 页面现在会在“汇率状态”卡片中展示“刷新汇率”按钮，直接调用现有 `POST /api/v1/portfolio/fx/refresh` 接口；刷新后会仅重载快照与风险数据，并以内联摘要反馈“已更新 / 仍 stale / 刷新失败”的结果，减少用户对 `fxStale` 长时间停留的误解。

### 修复

- 🔎 **Web 自动补全 Enter 提交语义修正** — 股票自动补全在搜索命中候选时不再默认高亮第一项；候选列表展开但用户尚未用方向键或鼠标明确选中时，按 Enter 会继续提交原始输入，避免手动输入被第一条候选静默覆盖。
- 🌍 **补齐 `REPORT_LANGUAGE` 启动解析与历史展示本地化边界** — `Config` 在启动时继续遵循“真实环境变量优先、`.env` 兜底”的既有语义，并在两者冲突时输出显式告警，减少 `REPORT_LANGUAGE` 来源不清带来的误判；同时 `/api/v1/history/{id}` 英文详情响应会同步本地化 `sentiment_label`，历史 Markdown 也会正确识别英文 `bias_status` 的风险等级 emoji，避免出现 `乐观` 或 `🚨Safe` 这类中英混排/误报展示。
- 📰 **Tavily 时效新闻检索发布时间映射修复**（#782）— Tavily 在股票新闻和严格时效的情报维度中现在会显式使用 `topic="news"`，并兼容 `published_date` / `publishedDate` 两种发布时间字段；修复了 Tavily 明明返回结果却在后续硬过滤阶段被全部记为 `drop_unknown` 丢弃的问题，同时将机构分析、业绩预期、行业分析等分析型维度恢复为宽源搜索，不再被统一压缩成新闻模式。
- 💱 **持仓页汇率刷新禁用语义修正**（#772）— 当 `PORTFOLIO_FX_UPDATE_ENABLED=false` 时，`POST /api/v1/portfolio/fx/refresh` 现在会返回显式 `refresh_enabled=false` 与 `disabled_reason`，Web `/portfolio` 页面会明确提示“汇率在线刷新已被禁用”，不再误报“当前范围无可刷新的汇率对”。
- 🤖 **Agent timeout and config hardening** — `AGENT_ORCHESTRATOR_TIMEOUT_S` now also protects the legacy single-agent ReAct loop, parallel tool batches stop waiting once the remaining budget is exhausted, and invalid numeric `.env` values fall back to safe defaults with warnings instead of crashing startup.
- 🌐 **CORS wildcard + credentials compatibility** — `CORS_ALLOW_ALL=true` no longer combines `allow_origins=["*"]` with credentialed requests, avoiding browser-side cross-origin failures in demo/development setups.
- 🧭 **Unavailable Agent settings hidden from Web UI** — Deep Research / Event Monitor controls are now treated as compatibility-only metadata in the current branch and are removed from the Settings page to avoid exposing non-functional toggles.

### 文档

- 新增 Ollama 本地模型配置说明，同步更新 `README.md` 与 `docs/README_EN.md`（Fixes #690）
- 完善 Ollama 配置说明：`docs/full-guide.md` / `docs/full-guide_EN.md` 环境变量表与 Note 补充 `OLLAMA_API_BASE`，避免英文用户误以为 Ollama 不能作为独立配置入口；合并重复的 `OLLAMA_API_BASE` 条目为单一条目
- 明确文档同步治理边界：补充 `README.md`、专题文档、双语文档与交付说明之间的默认同步规则，减少后续文档漂移

## [3.8.0] - 2026-03-17

### 发布亮点

- 🎨 **Web 界面完成一轮骨架升级** — 新的 App Shell、侧边导航、主题能力、登录与系统设置流程已经串成统一体验，桌面端加载背景也完成对齐。
- 📈 **分析上下文继续补强** — 美股新增社交舆情情报，A 股补齐财报与分红结构化上下文，Tushare 新接入筹码分布和行业板块涨跌数据。
- 🔒 **运行稳定性与配置兼容性提升** — 退出登录会立即让旧会话失效，定时启动兼容旧配置，运行中的 `MAX_WORKERS` 调整和新闻时效窗口反馈更清晰。
- 💼 **持仓纠错链路更完整** — 超售会被前置拦截，错误交易/资金流水/公司行为可以直接删除回滚，便于修复脏数据。

### 新功能

- 📱 **美股社交舆情情报** — 新增 Reddit / X / Polymarket 社交媒体情绪数据源，为美股分析提供实时社交热度、情绪评分和提及量等补充指标；完全可选，仅在配置 `SOCIAL_SENTIMENT_API_KEY` 后对美股生效。
- 📊 **A 股财报与分红结构化增强**（Issue #710）— `fundamental_context.earnings.data` 新增 `financial_report` 与 `dividend` 字段；分红统一按“仅现金分红、税前口径”计算，并补充 `ttm_cash_dividend_per_share` 与 `ttm_dividend_yield_pct`；分析/历史 API 的 `details` 追加 `financial_report`、`dividend_metrics` 可选字段，保持 fail-open 与向后兼容。
- 🔍 **接入 Tushare 筹码与行业板块接口** — 新增筹码分布、行业板块涨跌数据获取能力，并统一纳入配置化数据源优先级；默认按上海时间区分盘中/盘后交易日取数，优先使用 Tushare 同花顺接口，必要时降级到东财。
- 🧱 **Web UI 基础骨架升级** — 重建共享设计令牌与通用组件，新增 App Shell、Theme Provider、侧边导航，并同步调整 Electron 加载背景，为 Web / Desktop 的统一体验打底。
- 🔐 **登录与系统设置流程重做** — 重构 Login、Settings 与 Auth 管理流程，补上显式的认证 setup-state 处理，并让 Web 端与运行时认证配置 API 行为对齐。
- 🧪 **前端回归与冒烟覆盖补强** — 新增并扩展登录、首页、聊天、移动端 Shell、设置页、回测入口等关键路径的组件测试与 Playwright smoke coverage。

### 变更

- 🧭 **页面接入新 Shell 布局契约** — Home、Chat、Settings、Backtest 已统一接入新的页面容器、抽屉和滚动约定，降低 UI 迁移期间的页面行为不一致。
- 💾 **设置页状态同步更稳** — 优化草稿保留、直接保存同步与冲突处理，减少模块级保存后前后端配置状态不一致的问题。
- 🎭 **登录页视觉基线回归** — 登录页恢复到既有 `006` 分支的视觉基线，同时保留新的认证状态逻辑和统一表单交互模型。
- 🏛️ **AI 协作治理资产加固** — 收敛并加强 `AGENTS.md`、`CLAUDE.md`、Copilot 指令和校验脚本的一致性约束，降低治理资产长期漂移风险。

### Added

- **Web UI foundation refresh** — rebuilt shared design tokens and common primitives, introduced the app shell, theme provider, sidebar navigation, and Electron loading background alignment for the upgraded desktop/web experience
- **Settings and auth workflow overhaul** — rebuilt the Login, Settings, and Auth management flows, added explicit auth setup-state handling, and aligned the Web UI with the runtime auth configuration APIs
- **UI regression coverage and smoke checks** — expanded targeted frontend tests and added Playwright smoke coverage for login, home, chat, mobile shell, settings, and backtest entry flows

### Changed

- **Shell-driven page integration** — aligned Home, Chat, Settings, and Backtest with the new shell layout contract so routing, drawer behavior, and page-level scrolling are consistent during the UI migration
- **Settings state consistency** — refined draft preservation, direct-save synchronization, and conflict handling so module-level saves no longer leave the page out of sync with backend config state
- **Login visual baseline** — restored the login page visual treatment to the established `006` branch baseline while keeping the newer auth-state logic and unified form interaction model

### 修复

- ⏰ **定时启动立即执行兼容旧配置**（Issue #726）— `SCHEDULE_RUN_IMMEDIATELY` 未设置时会回退读取 `RUN_IMMEDIATELY`，修复升级后旧 `.env` 在定时模式下的兼容性问题；同时澄清 `.env.example` / README 中两个配置项的适用范围，并注明 Outlook / Exchange 强制 OAuth2 暂不支持。
- 🧵 **运行期 `MAX_WORKERS` 配置生效与可解释性增强**（#633）— 修复异步分析队列未按 `MAX_WORKERS` 同步的问题；新增任务队列并发 in-place 同步机制（空闲即时生效、繁忙延后），并在设置保存反馈与运行日志中明确输出 `profile/max/effective`，减少“参数未生效”误解。
- 🔐 **退出登录立即失效现有会话** — `POST /api/v1/auth/logout` 现在会轮换 session secret，避免旧 cookie 在退出后仍可继续访问受保护接口；同浏览器标签页和并发页面会被同步登出。认证开启时，该接口也不再属于匿名白名单，未登录请求会返回 `401`，避免匿名请求触发全局 session 失效。
- 🧮 **Tushare 板块/筹码调用限流与跨日缓存修复** — 新增的 `trade_cal`、行业板块排行、筹码分布链路统一接入 `_check_rate_limit()`；交易日历缓存改为按自然日刷新，避免服务跨天运行后继续沿用旧交易日判断取数日期。
- 💼 **持仓超售拦截与错误流水恢复**（#718）— `POST /api/v1/portfolio/trades` 现在会在写入前校验可卖数量，超售返回 `409 portfolio_oversell`；持仓页新增交易 / 资金流水 / 公司行为删除能力，删除后会同步失效仓位缓存与未来快照，便于从错误流水中直接恢复。
- 📧 **邮件中文发件人名编码**（#708）— 邮件通知现在会对包含中文的 `EMAIL_SENDER_NAME` 自动做 RFC 2047 编码，并在异常路径补充 SMTP 连接清理，修复 GitHub Actions / QQ SMTP 下 `'ascii' codec can't encode characters` 导致的发送失败。
- 🐛 **港股 Agent 实时行情去重与快速路由** — 统一 `HK01810` / `1810.HK` / `01810` 等港股代码归一规则；港股实时行情改为直接走单次 `akshare_hk` 路径，避免按 A 股 source priority 重复触发同一失败接口；Agent 运行期对显式 `retriable=false` 的工具失败增加短路缓存，减少同轮分析中的重复失败调用。
- 📰 **新闻时效硬过滤与策略分窗**（#697）— 新增 `NEWS_STRATEGY_PROFILE`（`ultra_short/short/medium/long`）并与 `NEWS_MAX_AGE_DAYS` 统一计算有效窗口；搜索结果在返回后执行发布时间硬过滤（时间未知剔除、超窗剔除、未来仅容忍 1 天），并在历史 fallback 链路追加相同约束，避免旧闻再次进入“最新动态/风险警报”。

### 文档

- ☁️ **新增云服务器 Web 界面部署与访问教程**（Fixes #686）— 补充从云端部署到外部访问的落地说明，降低远程自托管门槛。
- 🌍 **补齐英文文档索引与协作文档** — 新增英文文档索引、贡献指南、Bot 命令文档，并补充中英双语 issue / PR 模板，方便中英文协作与外部贡献者理解项目入口。
- 🏷️ **本地化 README 补充 Trendshift badge** — 在多语言 README 中同步补上新版能力入口标识，减少中英文说明面不一致。

## [3.7.0] - 2026-03-15

### 新功能

- 💼 **持仓管理 P0 全功能上线**（#677，对应 Issue #627）
  - **核心账本与快照闭环**：新增账户、交易、现金流水、企业行为、持仓缓存、每日快照等核心数据模型与 API 端点；支持 FIFO / AVG 双成本法回放；同日事件顺序固定为 `现金 → 企业行为 → 交易`；持仓快照写入采用原子事务。
  - **券商 CSV 导入**：支持华泰 / 中信 / 招商首批适配，含列名别名兼容；两阶段接口（解析预览 + 确认提交）；`trade_uid` 优先、key-field hash 兜底的幂等去重；前导零股票代码完整保留。
  - **组合风险报告**：集中度风险（Top Positions + A 股板块口径）、历史回撤监控（支持回填缺失快照）、止损接近预警；多币种统一换算 CNY 口径；汲取失败时回退最近成功汇率并标记 stale。
  - **Web 持仓页**（`/portfolio`）：组合总览、持仓明细、集中度饼图、风险摘要、全组合 / 单账户切换；手工录入交易 / 资金流水 / 企业行为；内嵌账户创建入口；CSV 解析 + 提交闭环与券商选择器。
  - **Agent 持仓工具**：新增 `get_portfolio_snapshot` 数据工具，默认紧凑摘要，可选持仓明细与风险数据。
  - **事件查询 API**：新增 `GET /portfolio/trades`、`GET /portfolio/cash-ledger`、`GET /portfolio/corporate-actions`，支持日期过滤与分页。
  - **可扩展 Parser Registry**：应用级共享注册，支持运行时注册新券商；新增 `GET /portfolio/imports/csv/brokers` 发现接口。

- 🎨 **前端设计系统与原子组件库**（#662）
  - 引入渐进式双主题架构（HSL 变量化设计令牌），清理历史 Legacy CSS；重构 Button / Card / Badge / Collapsible / Input / Select 等 20+ 核心组件；新增 `clsx` + `tailwind-merge` 类名合并工具；提升历史记录、LLM 配置等页面可读性。

- ⚡ **分析 API 异步契约与启动优化**（#656）
  - 规范 `POST /api/v1/analysis/analyze` 异步请求的返回契约；优化服务启动辅助逻辑；修复前端报告类型联合定义与后端响应对齐问题。

### 修复

- 🔔 **Discord 环境变量向后兼容**（#659）：运行时新增 `DISCORD_CHANNEL_ID` → `DISCORD_MAIN_CHANNEL_ID` 的 fallback 读取；历史配置用户无需修改即可恢复 Discord Bot 通知；全部相关文档与 `.env.example` 对齐。
- 🔧 **GitHub Actions Node 24 升级**（#665）：将所有 GitHub 官方 actions 升级至 Node 24 兼容版本，消除 CI 日志中的 Node.js 20 deprecation warning（影响 2026-06-02 强制升级窗口）。
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
