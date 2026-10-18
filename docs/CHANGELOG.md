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
- [改进] TickFlow 隔离 Premium 探针在显式标准模式下对照 15m/60m 单票与批量读取深度，只导出有界根数与网格枚举；报价-only 路径及全部 Radar/交易门禁不变。
- [新功能] Vibe-Trading Replay Lab 支持显式复用已有本地 OHLC CSV，记录来源哈希并按符号输出成本敏感性；不改变研究、Radar 或交易门禁。
- [改进] Vibe-Trading Replay Lab V0.4 为每个策略/标的/成本场景输出权益曲线、交易次数、净收益和 bar-low/close 最大回撤，并增加哈希绑定的严格 Walk-Forward 样本门禁；样本不足仍阻断 OOS claim。

- [修复] 多周期分析在历史不足或空数据分支保留调用方的未闭合标记，短历史仍输出明确不足告警；TickFlow 研究状态新增历史深度不足风险，防止 4 根 1H / 16 根 15m 被误标为非部分 K 线。

- [新功能] CN Radar 可显式选择现有 TickFlow 缓存，复用同一隔离服务生成四只基线标的的 D1/60m/15m 历史研究状态；独立核对来源版本与时效，保留未闭合及门禁阻断，不新增供应商调用。

- [修复] 美国 Radar 部署验收按 systemctl 的时长显示格式核对 90 秒 watchdog；增加完整 shell 路径回归测试，拒绝关闭、错误时长及无单位原始数字，保持数据和交易门禁关闭。
- [修复] A股只读 Radar 部署增加 owner/精确 main/显式重启校验、安装与验收脚本双哈希检查，阻止完整 SSM 输出进入公开日志；美股 Radar 部署仅在研究事件零入队且门禁关闭时识别未闭合源的合法阻断。
- [修复] OpenD 无订阅变更探针仅使用当前连接的订阅，避免借用其他连接状态后产生误导性拒绝；无自有订阅时零 K 线调用并明确阻断。
- [修复] TickFlow 批量响应漏项时每周期最多对四个缺失符号执行单票补取、每次五周期观察最多二十次；补取失败或超限时继续阻断缓存。
- [修复] Vibe-Trading 导入器仅在完整摩擦字段和受治理 holdout 证据存在时通过成本/OOS 验证，并增加 B0/V0.2/Strong Pullback 的只读自然语言研究入口。
- [新功能] Vibe-Trading 研究入口支持离线 Replay Lab 三策略比较、显式成本敏感性、不可变 fixture 来源哈希与两行诊断 holdout 且不宣称 OOS 验证；无持仓盯市路径时最大回撤明确为 NOT_COMPUTED；小样本统计能力仍明确为不足，研究/交易门禁保持关闭。
- [改进] TickFlow 私有研究缓存将封套 schema、provider 与状态不匹配分成固定脱敏错误码，便于云端定位并继续 fail-closed。
- [修复] 美股历史K线分页游标绑定查询条件，阻止跨日期范围复用后跳过数据。
- [新功能] 增加只读 `get_historical_bars` 缓存读取契约：限定 US 五周期、QFQ/RTH、日期范围，逐根校验来源元数据、时区、日历、闭合状态、OHLCV 与快照绑定分页；不执行 provider I/O，finality 与 Radar/交易门禁保持 UNKNOWN/BLOCKED。

- [新功能] 默认关闭地接通 US Radar 持久事件队列，增加有界 AI 消费循环、停止与断点回执恢复，以及独立超时/积压/未知状态审计；保留行情服务网络隔离，不启用付费调用或云端服务。
- [修复] OpenD 缓存首包等待订阅 ACK 后按完整 session 身份、有界顺序发布；拒绝/异常/溢出不发布待定批次，并收敛历史与实时源分钟 VWAP 越界阻断。
- [修复] TickFlow AUTO_200 在总量上限内保留基础 ETF 观察集，仅填充活跃股票；批量采集失败保留固定阶段与原因枚举，审计覆盖全部五周期及 200 标的边界。

- [新功能] 新增默认关闭的 Radar 单请求研究模型后端：SDK 禁重试、固定子进程硬超时、受限输出与脱敏回执，复用持久化预算及 UNKNOWN 防重放门禁；不启用付费调用或云端运行。

- [新功能] 闭合行情账本增加默认关闭的研究 AI 消费回执：调用前持久占位、结果先保存后 ACK、重启去重、持久调用上限；超时及未知结果阻断重试，继续关闭信号与交易门禁。
- [修复] OpenAI 用量与 Costs 采用各自有效的每日桶上限，保留完整账单窗口及分页阻断；Aider 有 Token 但零估价时费用标记未知，监控恶意大载荷回归兼容 Windows。