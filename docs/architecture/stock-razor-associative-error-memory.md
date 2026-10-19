# STOCK RAZOR | 关联故障记忆库 V1.3

此处是 **真实可执行的仓库级跨窗口故障检索**，而非 ChatGPT 基础模型训练或聊天窗口自动广播。

## 使用方式

每次 Main Control / OpenD / TickFlow / 策略实验窗口开始工作时：

1. 从 GitHub 拉取当前 `main` 精确 SHA，在**同一 SHA**读取 `AGENTS.md`、Self-Improvement `SKILL.md`、`failure-registry.json` 和 `associations.json`。
2. 看到旧错误、**相似症状**、新工具异常时，不必用户提醒，首先查询：

```bash
python scripts/self_improvement_gate.py --brief
python scripts/self_improvement_recall.py --query "D1 日线接口不支持"
python scripts/self_improvement_recall.py --query "心跳正常但是行情一直不更新"
python scripts/self_improvement_recall.py --check-associations
```

3. 搜索返回既往案例的编号、症状命中、已确认的前次诊断、证据链接、回归测试与下一步非重复动作；并会展开最相关案例的**一层关联故障**，避免重新研究本已出现过的方向。
4. `RELATED_CASES_FOUND` 仅为相关性提示；**绝对不能**声称相同根因或解除 `BLOCKED`。当前问题必须独立确认实际来源、参数、运行 SHA、时间和数据闭合。若无命中，返回 `UNKNOWN_NEW_CASE_NEEDS_RECEIPT`，而不是凭空猜测。
5. 未知错误在 Engineering Autonomy / CI 自动生成脱敏临时回执（见 V1.2）；证实根因、复现方法和回归测试后，经 PR 写入长期主线 `failure-registry.json`。如出现新的别名或相关性，给 `associations.json` 一并增量更新。
6. 该检索完全离线，**不调用 DeepSeek/OpenAI/付费行情**，不需要人工持续提醒；更不会重复触发高成本探针。

## 记忆架构与边界

- **永久规则/案例（主线 GitHub）**：经过验证的修复经验，可按窗口检索；没有额外的向量数据库、收费 embedding 或后台推送依赖。
- **检索同义关联（associations.json）**：中文、英文、常见术语/错误码的确定性别名和已知关联路径；支持命中不同说法，不依赖模型理解。其覆盖度随经验证的新案例增量扩张。
- **未确认未知错误（Action Artifacts / incident receipts）**：保留原始观察的脱敏故障家族，自动触发、可能 30 日到期，不等于长期主线案例。必须主动合并经过核验的事故 PR 才能成为永久知识。
- **Context Manager**：仅共享当前工程事件状态和实际版本，不假装自动推送到所有历史 ChatGPT 聊天会话。

## 验收标准

- 测试中文/英文同义词、近似关联案例、无命中新错误、短词误命中、非法映射、跨窗口相同来源读取。
- `ai-governance` 每个 PR 校验检索关联图，防止因失效 ID / 映射重复导致故障记忆退化。
- 同步断言：已关闭案例可供历史检索，但不存在“历史相似 ⇒ 当前数据 PASS”的捷径。
- 通知、安全门禁、模型费用和实际交易门禁完全不变。

## 反复出现的问题真正如何减少？

**先联想 → 再比对证据 → 只执行信息增量最大的下一步 → 把验证后的修复写回主线。**
每个窗口无需用户重新叙述上次尝试的全过程，但仍必须读取最新权威仓库。无法读取时报告 `SYNC_NOT_VERIFIED`，不能冒充已同步。
