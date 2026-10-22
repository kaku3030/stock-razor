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

- [改进] 运行控制台增加隔离的手动离线买入场景演练，可选本地模拟成交，不调用券商或行情源。
- [修复] Radar 研究计算与源闭合/实时证明分开报告；源证明未齐时事件仍阻断且零写入，重复轮询保留事件门禁与隔离原因。

- [修复] US Radar 隔离已知单标的成交额质量异常，保留正常闭合间隔与隔离诊断，并支持固定现有 LiveFeed SHA 的独立 worker 部署。

- [新功能] 扩展未注册到运行时路由的 `StockDataHubHistoricalAdapter`，供 Replay Lab 只读读取 A 股 15m/1h 历史与 stockdata-hub 缓存，并复用现有日线适配器分页提供 1d/1w/1y 回测数据；未改变 TickFlow/OpenD、交易或 Radar 门禁。

- [??] Windows TickFlow ?????????????????? 1m ????????????????????????K ??????????

- [修复] TickFlow minute-period single-symbol recovery now uses the intraday endpoint; D1 remains on the history endpoint.

- [修复] Windows TickFlow 五周期只读审计将分钟K线改走专用 intraday 接口，并接受盘中部分 60m 行；最终闭合与交易准入仍保持未验证/阻断。

- [修复] Engineering Autonomy 120m 的固定测试命令禁用全局 `tests/conftest.py`，保持 pytest-only 云端环境可执行并防止缺少应用依赖时队列虚报完成。

- [改进] STOCK RAZOR 跨窗口同步 V1.4.1 新增固定 GitHub 最新讨论索引 `#924/6269031171`，一条直读快速发现当前去敏工程事件，无需浏览整段 PR 历史或等待 AWS Actions 排队；重要讨论由当前连接窗口同步写入 append-only 事件与固定指针并独立验证，私人聊天全文不上传公开仓库。

- [新功能] STOCK RAZOR V1.4 新增以“交易/雷达/OpenD/TickFlow/策略”等关键词触发的跨窗口快速上下文预读取与 OWNER 去敏决策事件发布：专用 GitHub issue_comment 工作流将 #924 结构化更新经 AWS SSM 写入现有 Context Manager，增设主题/时间/来源校验及对应回归；真实发布到云端到达和旧聊天自动重载仍需独立验收。

- [改进] Self-Improvement V1.3 要求所有 STOCK RAZOR 运行窗口先关联检索已知中英同义故障及邻接案例，再决定是否重试；降低用户重复提醒的需求，但相似症状并不证明相同根因，未知事故必须先脱敏记录、经回归验证后纳入永久记忆。

- [新功能] Self-Improvement V1.2 自动记录 Engineering Autonomy 未知退出错误的脱敏指纹并阻止同条件下盲目重试，同时在 GitHub CI / Research Radar Tests 失败后通过只读 workflow_run 保存异常任务分类至 30 天 Actions artifact 供跨窗口检索；根因自动修复及永久登记仍须独立证据和受保护主线 PR，交易/付费/通知权限不改变。

- [改进] Self-Improvement V1.1 为跨窗口与工程自主任务新增简短共享错误摘要（`--brief`）及精确主线 SHA 校验；Engineering Autonomy 120m 与 DeepSeek Coding 试点在执行任务/付费模型调用前阻断过期主线和失效错误登记。报告时延仍必须实测，云端实例/数据/通知资格另行验收。

- [新功能] 增加 STOCK RAZOR Self-Improvement V1.0 仓库级跨窗口技能、当前 main 共享故障签名登记、相同 SHA/错误重复尝试阻断工具和必须经过的 ai-governance 检查；只对读取 GitHub 最新主线的工作窗口生效，不能主动向未打开的独立聊天推送新规则，亦不改变交易安全门禁。

- [新功能] 美股云端 OpenD 增加 GitHub XNYS 日历约束的 15 分钟研究级缓存审计与 Discord Radar 摘要通知：只读现有 15m/1H K线与 Radar D1 研究状态，严格阻断过期、未闭合、异常和来源不一致，不开启任何交易门禁；实际 GitHub 调度精度与 Discord 到达率仍待云端验收。

- [改进] Vibe-Trading historical capture preserves the Yahoo Chart raw payload hash and audits timezone/DST, XNYS calendar, source manifest, bar closure, and provider finality separately; missing evidence continues to block historical replay eligibility.
- [改进] Vibe-Trading Replay Lab V0.6 将 CSV 数据审计绑定到 Replay 报告并支持 JSON/Markdown 输出；fixture 仅标记为 `FIXTURE_SMOKE`，未验证证据继续阻断历史回放资格与 OOS 声明。
- [改进] Vibe-Trading Replay Lab V0.5 增加离线 OHLCV 数据血缘、时间戳、质量、closure、provider finality、新鲜度与 replay eligibility 的 fail-closed 审计报告；UNKNOWN 不升级为 PASS。
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
- [改进] TickFlow 私有研究缓存将封套 schema、provider 与状态不匹配分成固定脱敏错误码，便于云端定位并继续 fail-closed。=��u����k�w��r unknown")
        if len(recon.open_order_ids)>=self.limits.max_open_orders: raise ExecutionBlocked("outstanding-order cap reached")
        if intent.qty>self.limits.max_order_qty: raise ExecutionBlocked("order quantity exceeds limit")
        if intent.limit_price is None: raise ExecutionBlocked("paper V0.1 requires a limit reference price")
        notional=intent.qty*intent.limit_price
        if notional>self.limits.max_order_notional: raise ExecutionBlocked("order notional exceeds limit")
        if intent.side is Side.BUY and notional>recon.account.buying_power: raise ExecutionBlocked("insufficient buying power")
        if intent.max_slippage is None or intent.max_slippage>self.limits.max_slippage: raise ExecutionBlocked("slippage budget is missing or exceeds limit")
        if self.limits.daily_max_loss>0 and _decimal(context.daily_loss,"daily_loss")>=self.limits.daily_max_loss: raise ExecutionBlocked("daily loss limit reached")
        symbol=sum((p.market_value for p in recon.positions if p.symbol==intent.symbol),Decimal("0")); portfolio=sum((p.market_value for p in recon.positions),Decimal("0"))
        if symbol+notional>self.limits.max_symbol_exposure: raise ExecutionBlocked("symbol exposure exceeds limit")
        if portfolio+notional>self.limits.max_portfolio_exposure: raise ExecutionBlocked("portfolio exposure exceeds limit")

class ExecutionEngine:
    def __init__(self, capability: _PaperCapability, risk_guard: RiskGuard, store: ExecutionStore | None = None) -> None:
        if not isinstance(capability,_PaperCapability): raise ExecutionBlocked("only factory-issued paper capability is enabled")
        self.adapter=capability.adapter; self.risk_guard=risk_guard; self.store=store or ExecutionStore(); self.journal=tuple(self.store.events()); self.adapter.resume_order_sequence(self.store.broker_order_ids()); self.records={intent.intent_id: OrderRecord(intent) for intent in self.store.intents()}
        for event in self.journal:
            record = self.records.get(event.intent_id)
            if record is not None and event.state is not None: record.state = event.state
            if record is not None:
                details = dict(event.details)
                if details.get("broker_order_id"): record.broker_order_id = details["broker_order_id"]
                if details.get("fill_id") and details["fill_id"] not in record.fill_ids:
                    record.fill_ids.append(details["fill_id"]); record.filled_qty += Decimal(details.get("quantity", "0"))
        if self.store.has_ambiguous_submission(): raise ExecutionBlocked("ambiguous submission requires resync; automatic resubmit is blocked")
        self.reconciliation=None
        self.ledger = PaperBalanceLedger(self.store.connection, "paper")
    def _append(self, kind: str, record: OrderRecord, at: datetime, **details: object) -> None:
        event=JournalEvent(len(self.journal)+1,kind,record.intent.intent_id,details.pop("_state",record.state),(record.intent.evidence_snapshot_id,*record.fill_ids),_utc(at),tuple(sorted((str(k),str(v)) for k,v in details.items())))
        self.store.append(event); self.journal+=(event,)
    def _transition(self, record: OrderRecord, state: OrderState, at: datetime, **details: object) -> None:
        if state not in ALLOWED_TRANSITIONS[record.state]: raise ExecutionBlocked(f"invalid transition {record.state}->{state}")
        self._append(state.value,record,at,_state=state,**details); record.state=state
    def _mutation_gate(self, intent: OrderIntent, context: RiskContext) -> None:
        if self.reconciliation is None: raise ExecutionBlocked("reconciliation is required")
        self.risk_guard.check(intent,self.reconciliation,context)
        if self.store.has_ambiguous_submission(): raise ExecutionBlocked("pending mutation requires resync")
    def reconcile(self) -> ReconciliationSnapshot:
        balance = self.ledger.balance()
        if balance.status == "KNOWN":
            positions = tuple(PositionSnapshot(p.symbol, p.qty, p.market_value) for p in self.ledger.positions())
            now = balance.as_of
            account = AccountSnapshot("paper", balance.buying_power, balance.equity, now, "paper")
            snapshot = ReconciliationSnapshot(account, positions, as_of=now)
        else:
            snapshot=self.adapter.reconcile()
        self.reconciliation=snapshot
        if snapshot.as_of is None or not snapshot.complete or any(r.identity != snapshot.account.account_id or r.source != snapshot.account.source or not r.complete or not r.fresh for r in snapshot.resources()): raise ExecutionBlocked("reconciliation is incomplete or stale")
        return snapshot
    def submit(self, intent: OrderIntent, context: RiskContext) -> OrderRecord:
        if intent.intent_id in self.records or any(e.intent_id==intent.intent_id for e in self.journal): raise ExecutionBlocked("duplicate intent_id")
        if self.reconciliation is None: raise ExecutionBlocked("startup reconciliation is required")
        self.risk_guard.check(intent,self.reconciliation,context)
        ledger_known = self.ledger.balance().status == "KNOWN"
        cash_reserved = ledger_known and intent.side is Side.BUY
        # Check and durably reserve *before* writing SUBMITTING or contacting
        # any adapter. Otherwise a harmless insufficient-cash rejection leaves
        # an ambiguous order journal that unnecessarily blocks later recovery.
        if cash_reserved:
            self.ledger.reserve(intent.intent_id, intent.qty * intent.limit_price, context.now)
        try:
            self.store.save_intent(intent)
        except Exception:
            if cash_reserved:
                self.ledger.release(intent.intent_id, context.now)
            raise
        record=OrderRecord(intent); self.records[intent.intent_id]=record
        self._transition(record,OrderState.VALIDATED,context.now); self._transition(record,OrderState.SUBMITTING,context.now)
        try: broker_order_id,fills=self.adapter.place(intent)
        except PaperOrderRejected:
            if cash_reserved:
                self.ledger.release(intent.intent_id, context.now)
            self._transition(record,OrderState.REJECTED,context.now); return record
        if not broker_order_id: raise ExecutionBlocked("paper broker order identity is missing")
        fills=tuple(fills); seen=set(); validated=[]; total=Decimal("0")
        for fill_id,quantity,price in fills:
            quantity=_decimal(quantity,"fill quantity"); price=_decimal(price,"fill price")
            if not fill_id or fill_id in seen or self.store.fill_exists(fill_id) or price<=0 or quantity<=0 or total+quantity>intent.qty: raise ExecutionBlocked("invalid or duplicate paper fill")
            if ledger_known and self.ledger.has_fill_receipt(fill_id):
                # Offline seeding or replay can have legitimate ledger fills
                # absent from the order journal. Never record a false FILLED
                # journal before discovering this independent collision.
                raise ExecutionBlocked("fill identity already exists in paper ledger; reconciliation required")
            # Each LIMIT execution must honor the side-specific limit, not
            # merely average out an invalid price with a favorable fill.
            # Reject the entire synthetic batch before journal ACCEPTED.
            if (intent.side is Side.BUY and price > intent.limit_price) or (
                intent.side is Side.SELL and price < intent.limit_price
            ):
                raise ExecutionBlocked("paper fill violates side-specific limit price; reconciliation required")
            seen.add(fill_id); total+=quantity; validated.append((fill_id,quantity,price))
        # Check the entire returned batch against the already reserved
        # cash / owned position BEFORE appending even the first FILLED or
        # PARTIAL journal event. An over-limit synthetic receipt must leave
        # the submission pending reconciliation, never claim a durable fill
        # while the independent ledger rejects it.
        if ledger_known and validated:
            if cash_reserved:
                total_cost = sum(
                    (quantity * price for _, quantity, price in validated),
                    Decimal("0"),
                )
                if total_cost > intent.qty * intent.limit_price:
                    raise ExecutionBlocked(
                        "paper buy receipts exceed own reservation; reconciliation required"
                    )
            elif intent.side is Side.SELL:
                owned_qty = next(
                    (position.qty for position in self.ledger.positions()
                     if position.symbol == intent.symbol.upper()),
                    Decimal("0"),
                )
                if total > owned_qty:
                    raise ExecutionBlocked(
                        "paper sell receipts exceed owned quantity; reconciliation required"
                    )
        record.broker_order_id=broker_order_id; self._transition(record,OrderState.ACCEPTED,context.now,broker_order_id=broker_order_id)
        for fill_id,quantity,price in validated:
            record.fill_ids.append(fill_id); record.filled_qty+=quantity; self._transition(record,OrderState.FILLED if record.filled_qty==intent.qty else OrderState.PARTIAL,context.now,fill_id=fill_id,quantity=quantity,price=price,broker_order_id=broker_order_id)
            if ledger_known:
                self.ledger.record_fill(
                    fill_id=fill_id, intent_id=intent.intent_id,
                    reservation_id=(intent.intent_id if cash_reserved else None),
                    symbol=intent.symbol, side=intent.side.value,
                    quantity=quantity, price=price, at=context.now,
                )
        if cash_reserved and record.state is OrderState.FILLED:
            # Full execution may cost less than the limit-price reservation.
            # Return only unused cash from this order, not from other intents.
            self.ledger.release(intent.intent_id, context.now)
        return record
    def cancel(self, intent_id: str, at: datetime) -> OrderRecord:
        record=self.records.get(intent_id)
        if record is None or record.broker_order_id is None or record.state not in {OrderState.ACCEPTED,OrderState.PARTIAL}: raise ExecutionBlocked("order cannot be cancelled")
        self._mutation_gate(record.intent, RiskContext(at, at, record.intent.allowed_session)); self._append("CANCEL_REQUESTED",record,at,broker_order_id=record.broker_order_id); self.adapter.cancel(record.broker_order_id); self._transition(record,OrderState.CANCELLED,at,broker_order_id=record.broker_order_id)
        if self.ledger.balance().status == "KNOWN" and record.intent.side is Side.BUY:
            self.ledger.release(intent_id, at)
        return record
    def replace(self, intent_id: str, replacement: OrderIntent, context: RiskContext) -> OrderRecord:
        record=self.records.get(intent_id)
        if record is None or record.broker_order_id is None or record.state not in {OrderState.ACCEPTED,OrderState.PARTIAL}: raise ExecutionBlocked("order cannot be replaced")
        if replacement.intent_id in self.records or self.reconciliation is None: raise ExecutionBlocked("replacement intent_id already exists or reconciliation is missing")
        if self.ledger.balance().status == "KNOWN":
            # Original and new reservations cannot be atomically reassigned
            # across an external broker replace callback. Until independent
            # receipts/reconciliation exist, fail before any adapter mutation.
            raise ExecutionBlocked("ledger-backed replace requires receipt reconciliation")
        self._mutation_gate(replacement,context); self.store.save_intent(replacement); self._append("REPLACE_REQUESTED",record,context.now,replaced_by=replacement.intent_id); new_broker_order_id=self.adapter.replace(record.broker_order_id,replacement); self._transition(record,OrderState.SUPERSEDED,context.now,replaced_by=replacement.intent_id)
        new_record=OrderRecord(replacement,OrderState.ACCEPTED,new_broker_order_id); self.records[replacement.intent_id]=new_record; self._append("ACCEPTED",new_record,context.now,_state=OrderState.ACCEPTED,broker_order_id=new_broker_order_id,replaces=intent_id)
        return new_record
