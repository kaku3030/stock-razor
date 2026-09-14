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

- GET /api/v1/research-validation/artifact：服务端读取最新成功的 GitHub Artifact，并返回 JSON 证据。需要在部署环境设置 RADAR_GITHUB_TOKEN（令牌永不下发给浏览器），可选覆盖 RADAR_GITHUB_REPOSITORY、RADAR_GITHUB_BRANCH、RADAR_GITHUB_WORKFLOW。
- POST /api/v1/research-validation/submit：只校验并登记研究参数，返回 202 accepted_for_research；research_only 必须为 true，不会触发交易或生产 Promotion。

未配置令牌时 Artifact 接口明确返回 503，不会回退到前端直连 GitHub。
