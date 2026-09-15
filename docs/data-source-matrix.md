# Radar 数据源矩阵（研究版）

| Provider | 市场 | 周期 | 认证 | 优先级 | 定位 |
|---|---|---|---|---:|---|
| Efinance / Akshare / Pytdx | A 股 | 日线及既有能力 | 视适配器 | 0–2 | 常规主数据源 |
| Baostock | A 股 | 日线 | 免费登录/登出 | 3 | 历史回补、交叉校验 |
| Yfinance | A 股/美股/港股等 | 日线及既有能力 | 无 Key | 4 | 国际市场兜底 |
| TencentFetcher | A 股 | 日线 | 无 Key | 5 | 国内直连回退 |
| SinaResearchFetcher | A 股 | 日/周/月、1/5/15/30/60 分钟 | 无 Key | 研究专用 | 显式研究回退、周期补充；不进入 `DataFetcherManager()` 默认 routing |

## 统一限制

- 所有源进入回测前必须通过 PIT/anti-leak、日期窗口、缺失值和标准列校验。
- 免费公共接口可能限流、延迟或变更；失败必须显式记录并触发回退，不得伪装成市场状态。
- 研究源结果不得直接授予生产交易权限。
- Never-Seen Holdout、实验预算和证据 lineage 规则不因数据源更换而放宽。
