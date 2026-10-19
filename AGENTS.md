# AGENTS.md

本文件用于约束本仓库的默认开发流程，目标是减少重复沟通、减少返工，并让改动和当前项目结构保持一致。

如果本文件与仓库中的脚本、工作流、代码现状不一致，以实际可执行内容为准，并在相关改动中顺手修正文档，避免规则继续漂移。

## 0. STOCK RAZOR 跨窗口自我进化启动门禁（所有工程窗口必读）

- **每次新建、恢复或切换 STOCK RAZOR 工作窗口，在分析/编码/行情查询/云端操作前，必须先获取 GitHub `kaku3030/stock-razor` 当前 `main` 的完整 SHA，再以同一个 SHA 读取 `AGENTS.md`、`.claude/skills/stock-razor-self-improvement/SKILL.md` 和 `.claude/skills/stock-razor-self-improvement/failure-registry.json`。** 上次对话、旧内存、本地 checkout 或未合并 PR 不替代最新共享规则。ChatGPT 窗口通过 GitHub 连接读取；其他工程 Agent 可通过 `git fetch` 获取。
- **出现相同故障时先查失败登记表和前一次验证 SHA，再决定重试。** 同签名+相同代码SHA+相同环境/探针参数+无新证据 = `STOP_DUPLICATE`；不得继续重复云端试探、收费 API 或 CI 重跑。只有新诊断、新代码、新环境变化或有证据的反例才允许下一步。
- **修复必须沉淀为一次根因说明、证据链接、回归测试及状态更新，并经 protected main 生效。** 未验收标记 `NOT_VERIFIED`，CI 绿灯、Heartbeat HEALTHY 和数据业务 PASS 独立报告。禁止虚报“所有窗口已经自动同步”或“同一错误永不复发”。
- `scripts/self_improvement_gate.py --check-registry` 纳入既有 `ai-governance` CI 检查；`--status` 快速取证；`--signature ... --sha ... --previous-sha ...` 在确有上次失败 SHA 证据时阻止重复重试。**其他窗口不会被 GitHub 改动主动插入一条新聊天消息；必须在该窗口下一次开始工作时重新读取最新 `main`。**
- 路线 Main Control / OpenD / TickFlow 使用同一共享规则及失败编号；按最新用户指令维持本地优先、今晚美股开盘期间 OpenD 云端暂时优先、云端 TickFlow 最后。交易安全门禁、凭据及付费授权不因本技能改变。

## 0.1 快速响应与有证据推进原则（所有 STOCK RAZOR 窗口）

- 用户发送“继续/推进/如何”时，应**立刻**读取当前 main、相关失败签名和实际 CI/部署/行情状态；优先执行能关闭 P0 阻断的最小非重复工程操作，避免再次堆叠计划和空进度百分比。建议把常规状态响应目标控制在约 2 分钟内，**逐次记录真实的获取/分析/汇报耗时，不保证固定时延**。
- 不相关且无冲突的只读检查可并发；同一文件/分支/部署/凭据操作必须串行，避免竞态、频繁重复 push 导致 CI 自动取消。
- 快速状态可运行 `python scripts/self_improvement_gate.py --brief`。自动工程 120m 队列、DeepSeek+Aider 测试试点在工作前强制校验 **当前 GitHub main SHA 与共享错误登记**；主线变化、网络不可核实时直接 `BLOCKED`，不继续付费或长循环。
- 每次进度要提供至少一项新增的**具体证据**：PR/SHA、准确失败原因、测试/运行记录、通知回执或确认无法取得；没有新增证据时坦诚说明，不虚构后台推进。

## 0.2 未来未知错误的自主留痕与禁止盲目重试（V1.2）

- **未知故障先持久化，而不是重新调用同一个任务碰运气。** Engineering Autonomy 120m 任务第一次非零退出 / 超时 / 未处理异常，在 `engineering_autonomy/incidents.json` 中创建仅含任务名、退出码、队列 SHA、来源 SHA、环境类别、运行 ID、指纹的脱敏记录，并将队列标记 `BLOCKED`；同条件下不进行第二次执行。记录中 `UNKNOWN_PENDING_ROOT_CAUSE` 不代表已修复。
- **未来 GitHub CI / Research Radar Tests 失败时自动留痕。** `.github/workflows/self-improvement-ci-failure-capture.yml` 从 GitHub 仅只读获取失败作业名称/状态（绝不下载原始日志），自动上传保留 30 天的 `stock-razor-unknown-ci-<run_id>` 匿名分类 artifact；相关窗口可在 Actions 运行记录中检索，从而识别是否再次遇到相同失败家族。
- **跨窗口永久沉淀规则：** 自主工程处理新的 artifact 时，必须查看精确 run/SHA、原始失败原因（若已获准查看）并生成可复现回归；只有找到可靠错误特征后，才能通过普通受 CI 约束的 PR 将其写入 `failure-registry.json`。Artifact 只提供暂存证据；**若未写回 GitHub 主线登记表，过期后不具备永久记忆保障**。
- **相似不等于同一个根因：** 相同 CI job 名或进程退出码只是“同一症状家族”，不自动证明根因相同；不得因此放松安全门禁、改动凭据或无限停止必要的新版本验收。
- **验收边界：** 代码被合并且 CI 全绿不等于 Actions 监听已实际触发、事故 artifact 已产生或所有历史聊天窗口已自动加载。必须分别验证 `workflow_run` 运行与 artifact 读回，并记录无权限或调度失败。

## 0.3 自主关联记忆与少打扰协作（V1.3）

- **不需要用户每次提醒历史错误、重述已有方案。** Main Control / OpenD / TickFlow / 策略窗口每次开始调查新的异常症状，除了 `--brief`，还必须先根据症状调用 `python scripts/self_improvement_recall.py --query "<脱敏的问题描述>"`，或读取同 SHA 的 `associations.json` 做等价检索，然后再提出新问题、运行云端探针或重复调试。
- 本模块从 `failure-registry.json` + `associations.json` 返回 **中英同义、既往错误根因/证据链接、回归测试、应避免的重复动作、相邻可迁移案例**。触发 `RELATED_CASES_FOUND` 只代表**类似症状的研究线索**；确认根因、数据新鲜度和交易门禁仍需当前独立证据。
- 遇到 `UNKNOWN_NEW_CASE_NEEDS_RECEIPT`：不要求用户先整理说明；优先用 V1.2 的脱敏 `incident_memory` / CI artifact 收集可核验错误状态，针对已知事实诊断，并通过受 CI 约束的 PR 将**确认过的**错误写回长期登记表。新词/新相似关系同步写入 `associations.json`，使下一次更容易关联。
- **少打扰用户，避免追问已知问题**：只在缺少不可推断的付费、交易、凭据许可或关键输入时询问。不要把同一失败以不同话术重复汇报；每次只报告真正变化的运行 SHA、日志原因、修复/回归证据、剩余阻断及非重复下一步。
- **现实限制：** 新技能立即对读取当前 GitHub 主线的工程 Agent 生效，并非向未激活的 ChatGPT 旧窗口自动推送，也不改变模型参数；若未取回最新主线必须标记 `SYNC_NOT_VERIFIED`。

## 0.4 V1.4 交易/雷达话题主动快速同步（所有 STOCK RAZOR 窗口）

- **关键词首次触发，不等用户提醒**：任意 STOCK RAZOR 专用窗口、新接管会话中，首次出现“交易、持仓、雷达、A股、美股、OpenD、TickFlow、D1/1H/15m、回测、策略、云端、STOCK RAZOR、Main Control、Feedback Hub”等具体项目话题时，必须立即执行**最新状态预读取**，再根据当前证据回答或操作。可先用 `python scripts/stock_razor_fast_sync.py --route "<脱敏的话题>"` 选择相关领域；关键词匹配属于项目上下文触发，不代表金融建议，也不能从毫无关联的普通聊天臆测用户要求查询个人持仓。
- **最短两路同步**：① 读取 GitHub 最新 `main` SHA 和同 SHA 的 `AGENTS.md` / Self-Improvement Skill / `failure-registry.json` / `associations.json`；② 读取已有 STOCK RAZOR MCP `get_market_analysis(symbols=["__CONTEXT_MANAGER_STATE__"])` 和 `get_cn_market_analysis(symbols=["__CONTEXT_MANAGER_STATE__"])`，并查看 GitHub #924 最近 OWNER 发布的 `STOCK_RAZOR_SYNC_V1` 决策事件，按 topic + 时间 + provenance 去重。只读可以并发；无连接直接 `SYNC_NOT_VERIFIED`，绝不假装读到跨窗口新信息。
- **重要决定立即发表**：在项目讨论中形成新的关键工程优先级、策略研究约束、已验证阻断、正式合并/回滚状态时，普通授权范围内自动向 GitHub PR #924 发布**去敏、简短且附来源证据**的 `STOCK_RAZOR_SYNC_V1` JSON 事件（见 `docs/architecture/stock-razor-fast-cross-window-sync.md`），不等待用户说“同步一下”。新 GitHub `issue_comment` workflow 只接受仓库 OWNER 在 #924 发布的有效事件，经 AWS SSM 追加到**现有** Context Manager；其他随意评论、凭据、用户隐私和未经验证的 PASS 不能进入。
- **只在变化时同步**：避免对“继续”、无新状态的重复汇报、一般闲聊、账户信息、个人持仓数量与收费/交易口令进行公开事件推送。只同步去敏的项目进展和确定的决策。需要用户私人状态时依赖其授权源，不公开复制到 GitHub。
- **新窗口第一轮响应**：优先给短报告 `main SHA / 事件时间 / 相关事项 / 未解决阻断 / 下一步`，只读无法验证则注明 `SYNC_NOT_VERIFIED`。Context Manager 最近事件只代表自己的 domain 快照，不等于所有主题同时完整；GitHub OWNER comment 作为可追溯事件源可按 topic 补齐。
- **速度与权限边界**：目标减少反复询问和重复查询，发布、Actions 排队、AWS 写入、MCP 读回的耗时必须分别测量；GitHub Actions 不是毫秒级推送。无法主动修改未激活的旧 ChatGPT 对话或模型权重；只有新窗口实际触发相关工具读取、并具备连接和这些规则时，才可验证已自动获知。任何实盘交易和密钥权限不受此协议影响。

## 1. 硬规则

- 遵循现有目录边界：
  - 后端逻辑优先放在 `src/`、`data_provider/`、`api/`、`bot/`
  - Web 前端改动在 `apps/dsa-web/`
  - 桌面端改动在 `apps/dsa-desktop/`
  - 部署与流水线改动在 `scripts/`、`.github/workflows/`、`docker/`
- STOCK RAZOR 普通工程任务已有用户持续授权：可按自动化质量门禁执行 `git commit`、`git push`、创建 PR、与最新 `main` 同步和通过后合并，**无需逐次向用户申请人工批准**。创建 Release/tag、增加付费服务、改变敏感凭据/权限、真实交易或解除关键风控门禁，不得由这项普通工程授权推定许可。
- commit message 使用英文，不添加 `Co-Authored-By`。
- 不写死密钥、账号、路径、模型名、端口或环境差异逻辑。
- 优先复用现有模块、配置入口、脚本和测试，不新增平行实现。
- 默认稳定性优先于“顺手优化”；非当前任务直接需要的重构、抽象和基础设施迁移一律克制。
- 新增配置项时，必须同步更新 `.env.example` 和相关文档。
- 涉及用户可见能力、CLI/API 行为、部署方式、通知方式、报告结构变化时，必须同步更新相关文档与 `docs/CHANGELOG.md`。
- 修改报告格式、报告渲染效果或 Web UI 界面时，PR 描述必须附受影响报告 / 页面截图；涉及前后差异时优先附前后对比，无法截图时说明原因与替代可视证据。
- Issue / PR 过程截图、审查截图、一次性验收截图和临时可视证据不得作为仓库文件合入；应放在 PR 描述、PR 评论、GitHub 附件、Actions artifact 或外部可访问证据链接中。产品长期文档确需保留的示意图除外，但文件名和文档语义必须脱离具体 issue / PR 编号。
- `docs/CHANGELOG.md` 的 `[Unreleased]` 段使用**扁平格式**：每条独立一行，格式为 `- [类型] 描述`，类型取值：`新功能`/`改进`/`修复`/`文档`/`测试`/`chore`；**禁止在 `[Unreleased]` 内新增 `### 类目标题`**，以减少并发 PR 的 merge 冲突。发版时由 maintainer 汇总整理成带标题的正式格式。
- `README.md` 只用于项目定位、核心能力总览、快速开始、主要入口、赞助/合作等首页级信息；非必要不更新 README，避免持续膨胀。
- 更细的模块行为、页面交互、专题配置、排障说明、字段契约、实现语义和边界条件，优先更新对应 `docs/*.md` 或专题文档，不写入 README。
- 变更中英双语文档之一时，需评估另一份是否需要同步；若未同步，交付说明里要写明原因。
- 注释、docstring、日志文案以清晰准确为准，不强制要求英文，但应与文件语境保持一致。

## 1.1 PR 标题规范（非阻断建议）

- 推荐使用 `<类型>: <修改内容>` 作为 PR 标题，例如 `fix: 修复大盘分析历史记录丢失`，优先类型为 `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`。
- 标题应描述实际变更内容，建议不添加 `[codex]`、`codex`、`autocode`、`copilot` 或其他工具/agent 来源前缀。
- 该规范仅用于协作可读性与一致性提示，不应单独作为 review process blocker。

## 1.2 贡献质量底线

- 本仓库不接受以堆叠代码量、扩大 diff 面、补丁式响应 review 来替代真实设计收敛的 PR。
- 贡献质量以是否解决明确问题、是否最小化影响面、是否保持现有契约一致、是否覆盖真实风险路径为准；不以新增行数、文件数量、功能宣传或“看起来完整”为准。
- 请不要把本仓库当作低成本试验场、简历展示场或 contribution farming 场所。任何 PR 都必须证明作者理解当前系统契约，并完成基本自审、集成和验证。
- 使用 AI 辅助开发允许自动化独立核验：未经可复现的需求/契约检查、自动化语义审查或测试验证、未收敛的 AI 生成代码仍视为低质量。**不得把人工 reviewer、人工 ACK、人工 Code Owner 审批重新加为普通工程 PR 的阻断条件**。
- review 反馈后，不接受只在被指出的位置追加局部 patch。作者必须重新检查同一业务语义涉及的所有入口、配置、测试、文档、workflow 和用户可见路径。
- 如果一个 PR 在多轮 review 后仍持续出现同类契约漂移、重复 fallback、测试绕过真实风险层、PR body 与实际 diff 不一致等问题，维护者可以要求关闭重做，而不是继续逐点 review。

## 1.3 STOCK RAZOR 零人工审批的默认开发与合并契约（2026-10-13 用户再次确认）

- **普通工程自动推进：**开发→隔离测试/自动化 Standards+Spec 审查→PR→与最新 `main` 保持一致→required CI PASS→自动合并；不因缺少人的 Approve、签字、评论、ACK 或“再确认”而暂停。审查是可核验的代码/测试工作，不是人工审批。
- **GitHub 主分支生效规则（2026-10-13 实际核验）：**仓库 ruleset `Protect main` 已为 `required_approving_review_count=0`、无 `Code Owner` 审核、`require_last_push_approval=false`；必须满足 `backend-gate`、`focused-tests` 和 strict-current-main 规则。仓库可启用 GitHub Auto-Merge，并在非 Draft PR 上按确切 HEAD 与 CI 状态启用；不得因 0 个 Approve 等待人工审核。
- **失败时机器阻断：**CI/安全检查失败、Head 不一致、不能快进、合并冲突或测试/数据质量 UNKNOWN 时**不合并、不伪装 PASS**；自动定位修复并复测，或明确报告工程阻断原因。异常不能以“等待审核人员”作为通用借口。
- **风险边界不变：**普通 PR 合并不代表部署成功、生产数据源准入、Radar 信号可执行或交易授权。`SOURCE_ARBITER_ADMISSION=BLOCKED`、`RADAR_ADMISSION=BLOCKED`、`PAPER_AUTO_READY=NO`、`LIVE_TRADE=NO`、`TRADE_EXECUTION=NO` 独立生效；任何实盘下单、资金权限/密钥等高风险操作仍须遵守各自独立许可与安全控制，不得借“取消人工审核”绕过。
- **跨窗口同一约束：**Main Control、ECT、A/US Radar、A/US 交易分析和持仓窗口均须默认使用零人工 PR 审批流程；不能让 Draft PR、内部备注中的 `independent review` 或协作者 ACK 变成新的人工门禁。沟通与同步用于留痕，而非逐次索要批准。

## 2. AI 协作资产治理

### Context Manager recovery entry

新窗口接管 STOCK RAZOR 时，先读取本文件和
`.claude/skills/context-manager-recovery/SKILL.md`，再尝试已有只读 MCP
sentinel：`get_market_analysis(symbols=["__CONTEXT_MANAGER_STATE__"])`，必要时
使用 `get_cn_market_analysis(symbols=["__CONTEXT_MANAGER_STATE__"])`。响应只能作为
带 provenance/TTL 的工程状态证据；缺失、过期、未验收或 BLOCKED 不得推断为 PASS，
也不得改变任何 Radar、paper 或交易门禁。

- `AGENTS.md` 是仓库内 AI 协作规则的唯一真源。
- `CLAUDE.md` 必须是指向 `AGENTS.md` 的软链接，用于兼容 Claude 生态。
- `.github/copilot-instructions.md` 与 `.github/instructions/*.instructions.md` 是 GitHub Copilot / Coding Agent 的镜像或分层补充；若与本文件冲突，以 `AGENTS.md` 为准。
- 仓库协作 skill 存放在 `.claude/skills/`，分析产物存放在 `.claude/reviews/`；前者可以入库，后者默认视为本地产物。
- 根目录 `SKILL.md` 与 `docs/openclaw-skill-integration.md` 属于产品或外部集成说明，不是仓库协作规则真源。
- 若未来新增 `.agents/skills/` 或其他 agent 专用目录，必须先明确单一真源，再通过脚本或镜像同步；禁止手工长期维护多份同义内容。
- 修改 AI 协作治理资产时，执行：

```bash
python scripts/check_ai_assets.py
```

## 3. 仓库速览

- 项目定位：股票智能分析系统，覆盖 A 股、港股、美股。
- 主流程：抓取数据 -> 技术分析/新闻检索 -> LLM 分析 -> 生成报告 -> 通知推送。
- 关键入口：
  - `main.py`：分析任务主入口
  - `server.py`：FastAPI 服务入口
  - `apps/dsa-web/`：Web 前端
  - `apps/dsa-desktop/`：Electron 桌面端
  - `.github/workflows/`：CI、发布、每日任务
- 核心职责：
  - `src/core/`：主流程编排
  - `src/services/`：业务服务层
  - `src/repositories/`：数据访问层
  - `src/reports/`：报告生成
  - `src/schemas/`：Schema / 数据结构
  - `data_provider/`：多数据源适配与 fallback
  - `api/`：FastAPI API
  - `bot/`：机器人接入
  - `scripts/`：本地脚本
  - `.github/scripts/`：GitHub 自动化脚本
  - `tests/`：pytest 测试
  - `docs/`：文档与说明

## 4. 常用命令

### 运行应用

```bash
python main.py
python main.py --debug
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL
python main.py --market-review
python main.py --schedule
python main.py --serve
python main.py --serve-only
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 后端验证

```bash
pip install -r requirements.txt
pip install flake8 pytest
./scripts/ci_gate.sh
python -m pytest -m "not network"
python -m py_compile <changed_python_files>
```

### Web / Desktop

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build

cd ../dsa-desktop
npm install
npm run build
```

### PR / CI 证据

```bash
gh pr view <pr_number>
gh pr checks <pr_number>
gh run view <run_id> --log-failed
```

## 5. 默认工作流

1. 先判断任务类型：`fix / feat / refactor / docs / chore / test / review`
2. 先读现有实现、配置、测试、脚本、工作流和文档，再动手修改。
3. 识别改动边界：后端 / API / Web / Desktop / Workflow / Docs / AI 协作资产。
4. 先判断是否命中高风险区域：配置语义、API / Schema、数据源 fallback、报告结构、认证、调度、发布流程、桌面端启动链路。
5. 只做和当前任务直接相关的最小改动，不顺手夹带无关重构。
6. 如果发现文档、脚本、工作流描述不一致，优先信任实际代码与工作流，再决定是否顺手修正文档。
7. 改完后按下面的验证矩阵执行检查。
8. 最终交付默认要说明：
   - 改了什么
   - 为什么这么改
   - 验证情况
   - 未验证项
   - 风险点
   - 回滚方式

## 6. 验证矩阵

### CI 覆盖原则

当前仓库 CI 主要包含：

| 检查项 | 来源 | 说明 | 是否阻断 |
| --- | --- | --- | --- |
| `ai-governance` | `.github/workflows/ci.yml` | 校验 `AGENTS.md` / `CLAUDE.md` / `.github` 指令 / `.claude/skills` 关系 | 是 |
| `backend-gate` | `.github/workflows/ci.yml` | 执行 `./scripts/ci_gate.sh` | 是 |
| `docker-build` | `.github/workflows/ci.yml` | Docker 构建与关键模块导入 smoke | 是 |
| `web-gate` | `.github/workflows/ci.yml` | 前端改动时执行 `npm run lint` + `npm run build` | 是（触发时） |
| `network-smoke` | `.github/workflows/network-smoke.yml` | `pytest -m network` + `scripts/test.sh quick` | 否，观测项 |
| `pr-review` | `.github/workflows/pr-review.yml` | PR 静态检查 + AI 审查 + 自动标签 | 否，辅助项 |

若 PR 上已有对应 CI 结果，可直接引用 CI 结论；若 CI 未覆盖改动面，或本地与 CI 环境差异较大，需要补充说明本地验证与缺口。

### 按改动面执行

- Python 后端改动：
  - 适用范围：`main.py`、`src/`、`data_provider/`、`api/`、`bot/`、`tests/`
  - 优先执行：`./scripts/ci_gate.sh`
  - 最低要求：`python -m py_compile <changed_python_files>`
  - 若影响 API、任务编排、报告生成、通知发送、数据源 fallback、认证、调度，交付说明中要写明是否覆盖了对应路径。

- Web 前端改动：
  - 适用范围：`apps/dsa-web/`
  - 默认执行：`cd apps/dsa-web && npm ci && npm run lint && npm run build`
  - 若涉及 API 联调、路由、状态管理、Markdown/图表渲染或认证状态，交付说明中要明确说明联动面和未覆盖风险。

- 桌面端改动：
  - 适用范围：`apps/dsa-desktop/`、`scripts/run-desktop.ps1`、`scripts/build-desktop*.ps1`、`scripts/build-*.sh`、`docs/desktop-package.md`
  - 默认执行：先构建 Web，再构建桌面端
  - 如受平台限制未能完整验证，需要明确说明是否验证了 Web 构建产物、Electron 构建以及 Release 工作流影响。

- API / Schema / 认证联动改动：
  - 适用范围：`api/**`、`src/schemas/**`、`src/services/**`、`apps/dsa-web/**`、`apps/dsa-desktop/**`
  - 至少覆盖对应后端验证 + 受影响客户端构建验证。
  - 若涉及登录、Cookie、会话、轮询状态、字段增删或枚举变化，必须明确写出兼容性影响。

- 文档与治理文件改动：
  - 适用范围：`README.md`、`docs/**`、`AGENTS.md`、`.github/copilot-instructions.md`、`.github/instructions/**`、`.claude/skills/**`
  - 不强制代码测试。
  - 需确认命令、配置项、文件名、工作流名称与实际仓库一致。
  - 改动 AI 协作治理资产时，执行 `python scripts/check_ai_assets.py`。

- 工作流 / 脚本 / Docker 改动：
  - 适用范围：`.github/**`、`scripts/**`、`docker/**`
  - 运行最接近改动面的本地验证。
  - 交付时说明影响了哪条流水线、发布路径或部署路径。
  - 若未执行 Docker / GitHub Actions 相关验证，明确说明原因与潜在风险。

- 网络或三方依赖相关改动：
  - 先跑离线或确定性检查。
  - 优先确认 timeout、retry、fallback、异常文案、降级路径是否仍然成立。
  - 若未执行在线验证，必须明确写出原因。

## 7. 稳定性护栏

- 配置与运行入口：
  - 修改 `.env` 语义、默认值、CLI 参数、服务启动方式、调度语义时，要同时评估本地运行、Docker、GitHub Actions、API、Web、Desktop 的影响。
  - 新配置优先做到“不配置也可运行，配置后增强能力”，避免叠加开关和互斥模式。

- 数据源与 fallback：
  - 修改 `data_provider/` 时，要关注数据源优先级、失败降级、字段标准化、缓存与超时策略。
  - 单一数据源失败不应拖垮整个分析流程，除非需求明确要求 fail-fast。

- API / Web / Desktop 兼容：
  - 改 API / Schema / 认证 / 报告载荷时，要同时检查后端、Web、Desktop 的兼容性。
  - 默认优先追加字段、保留旧字段或提供兼容层，避免无提示破坏现有客户端。

- 报告 / Prompt / 通知：
  - 修改报告结构、Prompt、提取器、通知模板、机器人链路时，要检查上游输入与下游消费方是否仍兼容。
  - 单一通知渠道失败不应拖垮整个分析主流程，除非需求明确要求 fail-fast。
  - 修改 `src/services/image_stock_extractor.py` 中 `EXTRACT_PROMPT` 时，要在 PR 描述中附完整最新 prompt。

- 工作流 / 发布 / 打包：
  - 修改自动 tag、Release、Docker 发布、日常分析或桌面端打包流程时，要评估触发条件、产物路径、权限边界和回滚方式。
  - 自动 tag 默认保持 opt-in：只有 commit title 含 `#patch`、`#minor`、`#major` 才触发版本号更新，除非需求明确要求改变发布策略。

## 8. Issue / PR / Skill 工作流

- 仓库内已有以下 skill，可优先复用：
  - `.claude/skills/analyze-issue/SKILL.md`
  - `.claude/skills/analyze-pr/SKILL.md`
  - `.claude/skills/fix-issue/SKILL.md`
- 如果任务明确是 issue 分析、PR 审查、issue 修复，优先按对应 skill 执行，并将产物保存到 `.claude/reviews/`。
- skill 中的命令、模板、验证顺序和交付结构必须与 `AGENTS.md` 保持一致。
- 每次进行 PR 创建 / 更新、PR 审查或 issue 分析前，必须先同步最新代码基线：先检查工作区状态并执行 `git fetch --all --prune`；若工作区干净且当前分支可 fast-forward，则执行 `git pull --ff-only`。如存在本地改动、冲突状态、未跟踪风险文件或无法 fast-forward，不得强行切分支、stash、reset 或覆盖本地状态；PR 审查 / issue 分析可改用已 fetch 的远端 refs/PR head 做分析，并在分析文档中明确记录未更新本地工作树的原因、当前本地 HEAD 与使用的远端基线；PR 创建 / 更新应先说明当前分支与目标基线差异，普通工程任务在隔离 worktree 中自行同步、rebase 或 merge 并验证；必要时记录差异及冲突，**不再要求用户逐次确认**。
- skill 默认优先读取 CI / 工作流证据，再决定是否补本地验证。
- 普通工程任务允许在**隔离 worktree/当前受控分支**内执行必要的 `git fetch`、安全同步、`git push` 和 `gh pr create`，不因缺少人工批准暂停；禁止破坏 canonical dirty 工作树或跨越尚未授权的生产/资金/密钥控制。Release/tag 与敏感权限变更属于单独控制范围。
- PR 审查默认顺序：
  1. 必要性
  2. 关联性
  3. 标题建议（`<类型>: <修改内容>`，且不含工具/agent 前缀；不作为硬性阻断项）
  4. 描述完整性（对照 `.github/PULL_REQUEST_TEMPLATE.md`）
  5. 验证证据
  6. 实现正确性
  7. 合入判定
- 对 `fix` 类 PR，必须说明：原问题、根因、修复点、回归风险。
- 合入阻断条件：
  - 正确性或安全性问题
  - 阻断型 CI 未通过
  - PR 描述与实际改动内容实质性矛盾
  - 缺少回滚方案
  - 反复出现未收敛的契约漂移、补丁堆叠或验证证据失真

## 8.1 Review 反馈处理与补丁堆叠禁止

当你处理 review 反馈时，禁止只在 reviewer 点名的位置追加局部 patch 后声称“已全部修复”。你必须先重新理解 reviewer 指出的业务契约，再检查同一语义涉及的所有入口、配置、测试、文档、workflow 和用户可见路径。

收到 review 反馈后，必须按以下顺序处理：

1. 逐条列出 reviewer 指出的原问题。
2. 说明根因，不能只描述“改了哪几行”。
3. 找出同一语义影响的所有相关路径，例如 runtime、API/Web、CLI、diagnostics、workflow、docs、tests。
4. 修复完整契约，而不是只修复当前失败测试或当前评论行。
5. 补充能覆盖 reviewer 反例的回归测试、最终入口验证，或明确说明无法验证的原因。
6. 同步更新 PR body，保证 scope、验证结果、兼容性、风险和回滚方案与当前 head 一致。

如果你无法完成上述收敛，不要继续堆叠补丁，不要声称 ready for merge。应主动说明当前 PR 需要拆分、关闭重做，或请求维护者确认新的最小范围。

以下行为会被视为低质量 PR：

- 用 broad fallback、静默降级、`return False/None/[]` 掩盖不清晰的契约。
- 测试 mock 掉真实风险层，只证明局部实现通过。
- CI 通过后声称问题已关闭，但没有覆盖 reviewer 指出的反例。
- PR body 与实际 diff、验证结果或兼容风险不一致。
- review 后继续追加零散 patch，而不是重新收敛完整语义。
- 同一业务语义在 runtime、Web/API、docs、workflow、tests 中表现不一致。

CI 通过只能说明运行过的检查通过；若自动化静态审查、契约/回归测试或其他验证发现反例，必须自动修复并复测，不得以 CI 绿灯掩盖缺口。**普通工程 PR 无需人工语义审查签字或 reviewer 审批才能合并。**

## 9. 交付与发布

- 默认交付结构：
  - `改了什么`
  - `为什么这么改`
  - `验证情况`
  - `未验证项`
  - `风险点`
  - `回滚方式`
- 如果是 `docs` 任务，可直接写：`Docs only, tests not run`，但仍需说明是否核对了命令和文件名。
- 自动 tag 默认不触发，只有 commit title 包含 `#patch`、`#minor`、`#major` 才会触发版本号更新。
- 手动打 tag 必须使用 annotated tag。
- 用户可见变更优先通过 PR 合入，并补齐 label 与验证说明。
