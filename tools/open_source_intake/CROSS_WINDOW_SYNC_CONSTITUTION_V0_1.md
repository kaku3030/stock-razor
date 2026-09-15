# STOCK RAZOR — Cross-Window Sync Constitution V0.1

> **适用范围：**
>
> - Open-Source Intake / Harvesting Lane
> - Architecture & Promotion Control Tower
> - STOCK RAZOR 主线协调

## 1. Engineering Truth First

GitHub 当前工程事实优先于聊天记录、旧 summary、旧 ledger 和历史描述。

对以下状态，必须以最新 GitHub 事实为准：

- PR 状态
- branch
- exact head SHA
- commit
- CI / Research Radar Tests
- implementation status
- independent review status
- merge status
- promotion status

如果旧文档与 GitHub 不一致：

**GitHub = 当前 Engineering Truth**

文档必须随后同步修正。

---

## 2. Current State 必须与 Historical Record 分离

所有 Ledger / Summary / Control Tower 状态页都应维护一个明确的：

**CURRENT AUTHORITATIVE STATUS**

历史过程可以继续保留，但不得让旧描述看起来仍是当前状态。

例如：

`implementation has NOT started`

如果后续已经存在真实 implementation PR，则必须更新 Current State，而不是只在后面追加一段新记录。

---

## 3. 状态变化后主动同步

以下任一事件发生后，应主动同步主线，不等待用户人工搬运：

- 新 PR 创建
- branch 创建或改变
- head SHA 改变
- implementation 开始
- implementation 完成
- CI 开始/结束
- Research Radar Tests 开始/结束
- independent review 完成
- finding severity 改变
- blocker 新增/解除
- frozen contract / design freeze 改变
- promotion status 改变
- merge / close / retarget 发生

---

## 4. 最小同步状态包

每次状态同步至少包含：

- PR number
- branch
- exact head SHA
- current implementation status
- CI status
- review status
- promotion status
- unresolved dependency / blocker

推荐格式：

`PR #XX | head <sha> | IMPLEMENTED | CI PASS | REVIEW ACCEPTED | VALIDATING | blocker: ...`

---

## 5. 禁止旧聊天覆盖新事实

任何窗口都不得仅凭旧聊天记忆断言当前工程状态。

如果聊天上下文与 GitHub 事实冲突：

1. 先核 GitHub
2. 采用最新事实
3. 更新本窗口 Current State
4. 主动同步主线

---

## 6. 状态维度必须分开

不得把不同维度混成一个“完成/未完成”。

必须明确区分：

- `DESIGN STATUS`
- `IMPLEMENTATION STATUS`
- `CI STATUS`
- `REVIEW STATUS`
- `PROVIDER EVIDENCE STATUS`
- `PROMOTION STATUS`

例如：

`Provider evidence = UNKNOWN`

不等于：

`implementation not started`

同样：

`CI PASS`

也不等于：

`semantic contract CLOSED`

---

## 7. 推荐统一状态机

代码实现轨：

`DESIGN:FROZEN`
→ `IMPLEMENTED`
→ `VALIDATING`
→ `INDEPENDENT_REVIEWED`
→ `PROMOTION-ELIGIBLE`

证据轨：

`UNKNOWN`
→ `PARTIALLY_VERIFIED`
→ `VERIFIED`

两条轨道不能互相替代。

---

## 8. Exact-Head Rule

所有 CI / review / validation 结论都必须绑定 exact head SHA。

旧 head 的 PASS：

**不得继承到新 head。**

head 一旦改变：

- 旧 CI 变成 historical evidence
- 当前状态重新进入待验证

---

## 9. Cross-Window Share by Default

两个支线与主线之间的：

- 审计结果
- 设计冻结
- provider evidence
- 测试
- failure cases
- fixtures
- PR 状态
- CI 结果
- promotion 决策

默认允许相互读取、复用、同步。

无需再次请求用户授权。

---

## 10. No Duplicate Work

在开始新任务前，先检查：

- 是否已有实现
- 是否已有 PR
- 是否已有测试
- 是否已有冻结设计
- 是否已有另一支线正在推进

优先流程：

**Existing implementation check**
→ **Compliance audit**
→ **Gap confirmation**
→ **Minimal patch**

禁止因为旧任务书写着 “Implement” 就默认重新造一套。

---

## 11. Mainline Coordination Rule

主线在讨论任何：

- 下一步
- 后续
- 接下来
- 给哪个模型
- 是否进入下一阶段
- 是否开始下一 Slice
- 是否 Promotion

之前，必须先：

**同步两支线最新状态**
→ **核对 GitHub/CI**
→ **检查 frozen boundary / dependencies**
→ **再分配模型任务**

---

## 12. 模型任务不等于支线任务

两个支线是：

**状态源 / 治理源 / 证据源**

不是默认的“任务接收模型”。

主线最终任务应明确分配给具体模型，例如：

- ChatGPT
- Claude
- DeepSeek
- Flash

并注明：

- model
- reasoning/thinking level
- task type
- scope

---

## 13. Drift Detection Rule

如果发现：

`Ledger status != GitHub reality`

或

`Control Tower status != exact-head evidence`

必须明确标记：

**STATUS DRIFT**

然后：

1. 更新 Current State
2. 保留旧内容为 Historical Record
3. 主动通知主线

不允许静默忽略。

---

## 14. 核心原则

**GitHub tells us what exists.**

**CI tells us what passed.**

**Review tells us what was examined.**

**Evidence tells us what is actually known.**

**Governance decides what may be promoted.**

这五者不得互相替代。
