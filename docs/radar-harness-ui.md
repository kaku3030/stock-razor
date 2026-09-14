# Radar Rule Validation Harness UI

## 研究页面

启动 WebUI 后访问 `/research-validation`，或从左侧导航进入“研究验证 / Research Lab”。

页面当前为研究证据读取模式，不连接交易执行。

## 查看一次 CI 回测

1. 打开 GitHub Actions 的 **Research Universe Capture** 成功运行。
2. 下载该运行生成的 `research-universe-<run_id>` Artifact。
3. 在 Artifact 中找到：
   - `rs_summary.json`
   - `cn_sh_600000_counterfactual.json`
4. 在研究验证页分别加载两个 JSON 文件。
5. 页面会显示分阶段结果和反事实结果。

## 结果解释

- `development`：规则开发区间。
- `validation`：样本外验证区间。
- `never_seen_holdout`：从未查看的保留区间。
- `with_rule` 与 `without_rule`：规则增量对比。
- `delayed_rule`：时序延迟反事实。
- `shuffled_placebo`：随机安慰剂反事实。
- `regime_conditioned`：按前一日状态过滤的反事实。

## 安全边界

页面不会把研究结果直接升级为生产规则。PIT/anti-leak、Holdout 污染、实验预算和 Control Tower Promotion Gate 仍由后端与 CI 控制。不要把生产凭据放入浏览器或前端配置。

## 后端自动读取与受控提交

后端提供两个研究专用接口：

- GET /api/v1/research-validation/status：返回代理就绪状态（不返回令牌）。\n- GET /api/v1/research-validation/artifact：服务端读取最新成功的 GitHub Artifact，并返回 JSON 证据。需要在部署环境设置 RADAR_GITHUB_TOKEN（令牌永不下发给浏览器），可选覆盖 RADAR_GITHUB_REPOSITORY、RADAR_GITHUB_BRANCH、RADAR_GITHUB_WORKFLOW。
- POST /api/v1/research-validation/submit：只校验并登记研究参数，返回 202 accepted_for_research；research_only 必须为 true，不会触发交易或生产 Promotion。

未配置令牌时 Artifact 接口明确返回 503，不会回退到前端直连 GitHub。


## Ashare 思路的新浪研究回退

Harness 的 A 股日线管理器已接入 `SinaResearchFetcher`（Priority 6），实现独立的新浪 K 线适配，不复制第三方仓库文件。适配器支持日/周/月及 1/5/15/30/60 分钟频率，统一输出标准 OHLCV 列，并固定请求超时、代码校验、日期窗口过滤和空结果处理。

参考了 [mpquant/Ashare](https://github.com/mpquant/Ashare) 的公开接口思路；该仓库未提供明确许可证，因此本项目仅采用公开接口行为并保留本地实现。新浪接口属于免费公共行情入口，可能限流或变更，仅用于研究回测与故障回退，不作为生产授权或实时交易依据。


运维覆盖：可设置 `STOCK_RAZOR_SINA_KLINE_URL` 替换接口地址，`STOCK_RAZOR_SINA_TIMEOUT_SECONDS` 调整超时（最低 1 秒）。默认配置无需额外 Key 或积分。


双直连回退顺序：常规数据源失败后，先尝试 `TencentFetcher`，再尝试 `SinaResearchFetcher`；两者均只提供 A 股日线研究回退，不改变主数据源优先级。


### 双直连源验证

离线单元测试（不会访问行情网络）：

```bash
python -m pytest -q tests/test_sina_research_fetcher.py tests/test_tencent_fetcher.py
```

需要实际检查公共接口时，可在研究环境中执行：

```bash
python scripts/check_direct_market_sources.py --symbol 600000 --days 5
```

真实联网检查只用于数据源可用性诊断；结果不得直接作为生产交易授权或策略结论。


脚本位置：`scripts/check_direct_market_sources.py`。退出码为 0 表示两个源均成功，非 0 仅表示本次诊断有源失败，不代表市场状态或策略结论。


诊断脚本的离线行为由 `tests/test_direct_market_sources.py` 覆盖，成功与单源失败均不会访问外网。


### Baostock 回补与校验

`BaostockFetcher` 作为免费历史数据源，用于 A 股日线回补和交叉校验。每次请求都显式执行登录→查询→登出；登录失败、查询失败或空结果会进入统一回退链。Baostock 不覆盖美股、港股和北交所，这些代码会直接交给其他数据源处理。


CI 快速门禁还会先编译新浪、腾讯、Baostock 和诊断脚本，语法错误会在联网测试前直接失败。


### 当前交付状态（2026-09-14）

- 新浪：IMPLEMENTED / TEST_COVERED
- 腾讯：IMPLEMENTED / TEST_COVERED
- Baostock：IMPLEMENTED / SESSION_TEST_COVERED
- yfinance：既有适配器 / 错误归一化已覆盖
- CI：快速编译门禁 + 双直连源测试 + 完整研究测试
- 生产交易：NOT_AUTHORIZED；仍需通过 PIT、回放和 Never-Seen Holdout 验收


### 验收证据记录

- 专用研究 CI：Run [34824621114](https://github.com/kaku3030/stock-razor/actions/runs/34824621114)，结论 SUCCESS。
- 全仓 CI：Run [34824621027](https://github.com/kaku3030/stock-razor/actions/runs/34824621027)，Docker、Web、Backend、治理检查全部 SUCCESS。
- 交付 PR：[ #120](https://github.com/kaku3030/stock-razor/pull/120)，当前 OPEN，未合并。
- 生产授权：NOT_AUTHORIZED；数据源仍限于研究、回补、校验和故障回退。
