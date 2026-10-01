# 启动正式 PIT 验证

在 GitHub 打开 Actions → Research PIT Validation → Run workflow。

填写：

- run_id：选择最近一次成功的 Research Universe Capture 运行编号
- artifact_name：对应 Artifact 的完整名称，例如 research-universe-34845078037
- approver：user-approved
- reason：用户批准正式验证

执行后，工作流会自动：

1. 下载 Artifact
2. 校验 CSV SHA-256
3. 写入 PIT 审批审计字段
4. 强制要求 PIT_APPROVED
5. 运行严格 recorded-capture 验证
6. 上传 research-pit-validation 证据包

任何校验失败都会停止，不会生成正式验证结论。生产晋升和实盘交易仍保持锁定。
