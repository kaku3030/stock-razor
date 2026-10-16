# TickFlow 开源项目核查

## 结论

公开检索到的项目不能按名称直接视为同一项目：

| 项目 | 身份 | 与 Radar 的关系 |
| --- | --- | --- |
| [tickflow-org/tickflow](https://github.com/tickflow-org/tickflow) | TickFlow 官方 Python SDK，MIT | 当前 REST/WebSocket 接入的上游；继续以官方文档和 SDK 契约为准 |
| [shy3130/tick-stock-panel](https://github.com/shy3130/tick-stock-panel) | 独立的自托管量化工作台，MIT；依赖 TickFlow 数据服务 | 非官方 Radar；可参考能力探测、数据源插件抽象和 Windows/Docker 运行方式 |
| [hzy1522/tickflow-stock-panel](https://github.com/hzy1522/tickflow-stock-panel) | 上游看板的多市场 fork，MIT | 非官方 fork；不作为 TickFlow 协议或实时性证据 |
| [axiomying/tickflow](https://github.com/axiomying/tickflow) | 独立的高频时间序列分析 Python 库，MIT | 与官方 TickFlow API 没有确认关联；暂不接入 |
| [tickflow-org/tickflow-skills](https://github.com/tickflow-org/tickflow-skills) | 官方组织发布的 Skill 示例 | 可参考环境配置和 SDK 调用说明；不替代 Radar 的运行时验证 |

## 对 Radar 有用的内容

1. **能力驱动而不是名称驱动。** Stock Panel 将数据源能力探测与业务页面分离，文档明确要求策略、监控和 API 不直接硬编码 SDK 调用。Radar 已有独立的 provider/cache/准入边界，因此不复制一套平行数据源控制面。
2. **TickFlow 套餐能力必须实探。** Stock Panel 的 `tiers.yaml` 只是 UI/探测参考，不是运行时能力证明；其中部分批量能力还明确标注为推断。Radar 不采纳静态套餐表作为实时、WebSocket、分钟 K 或最终闭合证明。
3. **Windows 配置可直接复用。** 官方 SDK README 给出了 PowerShell/CMD 环境变量方式；本项目 `.env.example` 已补充 `TICKFLOW_RESEARCH_WS_ENABLED=false`，测试侧会自动发现已安装的 Git Bash。
4. **不要把看板功能等同于 Radar 证据。** 看板的选股、监控、回测和 SSE UI 是产品能力；它们不能证明 TickFlow provider 的连续性、服务器 ACK、K 线最终闭合或交易准入。

## 处理决定

- **保留官方 SDK 接入。** 继续使用 `tickflow-org/tickflow` 的 REST/K 线与可选 WebSocket 研究观察层。
- **不接入 Stock Panel 代码。** 它与 Radar 的权威边界、缓存语义和交易门禁不同，接入会增加重复控制面。
- **不接入 `axiomying/tickflow`。** 该库的 tick/volume/dollar bars、微观结构和实现短缺指标面向本地分析数组，不是 TickFlow 行情服务客户端；如将来研究订单流，只能作为离线特征研究候选。
- **保留研究状态。** 公开项目的 README、套餐表或 UI 能力描述不能替代当前精确 SHA、实际账号权限、真实回调和跨时间窗口的验收。

## 来源边界

本记录基于 2026-10-16 可访问的 GitHub 仓库、README、贡献指南、`tiers.yaml`、官方 SDK README 与官方组织仓库列表。没有安装、启动或导入第三方项目，也没有使用它们的凭证或网络服务。
