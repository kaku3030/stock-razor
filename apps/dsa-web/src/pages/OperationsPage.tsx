import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { Activity, BellRing, RefreshCw, ShieldCheck } from 'lucide-react';
import { operationsApi, type OperationsStatus, type PaperOperatorControls } from '../api/operations';
import { ApiErrorAlert, AppPage, Card, Loading, PageHeader } from '../components/common';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import OfflineSimulationCard from '../components/OfflineSimulationCard';

const Gate: React.FC<{ label: string; value: string; safe?: boolean }> = ({ label, value, safe = false }) => (
  <div className="flex items-center justify-between gap-4 border-b border-border/60 py-3 last:border-b-0">
    <span className="text-sm text-secondary-text">{label}</span>
    <span className={safe ? 'rounded-full bg-success/15 px-2.5 py-1 text-xs font-semibold text-success' : 'rounded-full bg-warning/15 px-2.5 py-1 text-xs font-semibold text-warning'}>
      {value}
    </span>
  </div>
);

const notificationLabel = (channel: string): string => ({
  discord: 'Discord',
  wechat: '企业微信',
  telegram: 'Telegram',
  feishu: '飞书',
  dingtalk: '钉钉',
  pushplus: 'PushPlus',
  serverchan3: 'Server酱',
}[channel] ?? channel);

const routeLabel = (route: string): string => ({
  report: '报告',
  alert: '告警',
  system_error: '系统错误',
}[route] ?? route);

const paperActionLabel = (action: string): string => ({
  inspect_operator_controls: '查看模拟盘权限',
  run_offline_simulation: '运行离线模拟',
  discover_external_paper_account: '读取模拟账户',
  submit_external_paper_order: '提交模拟订单',
  cancel_or_replace_external_paper_order: '撤销或替换模拟订单',
  send_phone_alert: '发送手机通知',
}[action] ?? action);

const paperReasonLabel = (reason: string): string => ({
  READ_ONLY_NO_SIDE_EFFECTS: '只读查看，无副作用',
  LOCAL_SYNTHETIC_SCENARIO_ONLY_NO_EXTERNAL_IO: '仅运行独立的手动场景演练，不触发外部 IO',
  CLOUD_ACCOUNT_IDENTITY_NOT_VERIFIED: '云端模拟账户身份尚未验证',
  NO_AUTHORIZED_OPERATOR_OR_VERIFIED_ACCOUNT: '操作身份或模拟账户尚未验证',
  NO_VERIFIED_PHONE_RECEIPT_OR_SEND_APPROVAL: '尚无手机送达回执',
}[reason] ?? reason);

const paperStatusLabel = (status: string): string => ({
  READY_EXPLICIT_OFFLINE_RUN_EXTERNAL_BROKER_NOT_CONNECTED: '离线可运行 / 未连券商',
  READY_READ_ONLY_UNVERIFIED_CLOUD_ACCOUNT: '只读契约 / 云账户未验证',
}[status] ?? status);

const OperationsPage: React.FC = () => {
  const [status, setStatus] = useState<OperationsStatus | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [paperControls, setPaperControls] = useState<PaperOperatorControls | null>(null);
  const [paperControlsError, setPaperControlsError] = useState<string | null>(null);
  const [paperControlsLoading, setPaperControlsLoading] = useState(false);

  const loadStatus = useCallback(async () => {
    setRefreshing(true);
    try {
      setStatus(await operationsApi.getStatus());
      setError(null);
      setCheckedAt(new Date());
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setRefreshing(false);
    }
  }, []);

  const loadPaperControls = useCallback(async () => {
    setPaperControlsLoading(true);
    try {
      setPaperControls(await operationsApi.getPaperControls());
      setPaperControlsError(null);
    } catch (err) {
      setPaperControlsError(getParsedApiError(err).message);
    } finally {
      setPaperControlsLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = '运行控制台 - Stock Razor';
    void loadStatus();
    void loadPaperControls();
    const timer = window.setInterval(() => {
      void loadStatus();
      void loadPaperControls();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [loadStatus, loadPaperControls]);

  if (error) return <AppPage><ApiErrorAlert error={error} /></AppPage>;
  if (!status) return <AppPage><Loading /></AppPage>;

  return (
    <AppPage>
      <PageHeader
        title="运行控制台"
        description="通知、数据门禁与 Paper Trading 状态"
        actions={(
          <div className="flex items-center gap-3">
            <span className="text-xs text-secondary-text">
              {checkedAt ? `最近检查 ${checkedAt.toLocaleTimeString()}` : '正在检查'}
            </span>
            <button
              type="button"
              className="btn-secondary inline-flex items-center gap-2"
              onClick={() => { void loadStatus(); void loadPaperControls(); }}
              disabled={refreshing || paperControlsLoading}
            >
              <RefreshCw className={refreshing ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} aria-hidden="true" />
              刷新状态
            </button>
          </div>
        )}
      />
      <div className="mt-4 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm text-warning">
        外部账户、行情与自动执行控制保持只读；仅提供下方独立的本地离线场景演练。LIVE_TRADE 保持关闭。
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <Card title="数据门禁" subtitle="ADMISSION">
          <Activity className="mb-3 h-5 w-5 text-primary" />
          <Gate label="Radar" value={status.radar_admission} safe={status.radar_admission === 'PASS'} />
          <Gate label="Source Arbiter" value={status.source_arbiter_admission} safe={status.source_arbiter_admission === 'PASS'} />
          <Gate label="运行模式" value={status.mode} safe={status.mode === 'paper_only'} />
        </Card>
        <Card title="通知提醒" subtitle="NOTIFICATIONS">
          <BellRing className="mb-3 h-5 w-5 text-primary" />
          <Gate label="Webhook 配置" value={status.notification_ready ? '已配置' : '未配置'} safe={status.notification_ready} />
          <div className="pt-3 text-sm text-secondary-text">
            渠道：{status.notification_channels_configured.length ? status.notification_channels_configured.map(notificationLabel).join('、') : '暂无'}
          </div>
          <div className="mt-3 space-y-1 text-xs text-secondary-text">
            {Object.entries(status.notification_routes).map(([route, channels]) => (
              <div key={route} className="flex justify-between gap-3">
                <span>{routeLabel(route)}</span>
                <span>{channels.length ? channels.map(notificationLabel).join('、') : '未配置可用渠道'}</span>
              </div>
            ))}
          </div>
          <div className="pt-2 text-xs text-warning">
            手机接收证据：{status.notification_delivery_evidence}
          </div>
          <p className="pt-2 text-xs text-secondary-text">配置成功不等于手机已收到；需完成真实接收回执。</p>
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            <a className="text-primary underline" href="/alerts">打开告警中心</a>
            <a className="text-primary underline" href="/settings">通知设置与测试</a>
          </div>
        </Card>
        <Card title="Paper Trading" subtitle="EXECUTION">
          <ShieldCheck className="mb-3 h-5 w-5 text-primary" />
          <Gate label="Paper Auto" value={status.paper_auto_ready ? 'READY' : 'BLOCKED'} safe={status.paper_auto_ready} />
          <Gate label="Paper 引擎" value={status.paper_engine_status} safe={status.paper_engine_status === 'IMPLEMENTED_OFFLINE_ONLY'} />
          <Gate label="离线模拟盘" value={paperStatusLabel(status.offline_simulation_status)} safe={status.offline_simulation_status.startsWith('READY_')} />
          <Gate label="Web 自动执行入口" value={status.paper_runtime_api_status} />
          <Gate label="异常执行复核投影" value={status.execution_recovery_projection_status} />
          <Gate label="Paper Store 配置" value={status.paper_runtime_store_config_status} />
          <Gate label="Trade Plan" value={status.trade_plan_status} />
          <Gate label="Position Management" value={status.position_management_status} />
          <Gate label="Trade Lifecycle" value={status.trade_lifecycle_status} />
          <Gate label="外部模拟盘契约" value={paperStatusLabel(status.external_simulator_contract_status)} />
          <Gate label="模拟账户证据" value={status.simulated_account_evidence} />
          <Gate label="Live Trade" value={status.live_trade ? 'ON' : 'NO'} />
          <p className="pt-3 text-xs text-secondary-text">自动执行仍需独立重启、重连与对账验收。</p>
        </Card>
      </div>
      <Card className="mt-4" title="Paper 操作权限" subtitle="READ ONLY / NO BROKER IO">
        {paperControlsError && <p className="mb-3 text-sm text-warning">权限状态读取失败：{paperControlsError}</p>}
        {!paperControls && !paperControlsError && <p className="text-sm text-secondary-text">正在读取只读权限状态…</p>}
        {paperControls && (
          <>
            <div className="grid gap-2 text-sm sm:grid-cols-3">
              <Gate label="界面权限" value={paperControls.read_only ? '只读' : '未知'} safe={paperControls.read_only} />
              <Gate label="HTTP 修改" value={paperControls.mutation_allowed ? '开放' : '关闭'} safe={!paperControls.mutation_allowed} />
              <Gate label="券商 IO" value={paperControls.broker_io_allowed ? '开放' : '关闭'} safe={!paperControls.broker_io_allowed} />
              <Gate label="行情 Provider IO" value={paperControls.provider_io_allowed ? '开放' : '关闭'} safe={!paperControls.provider_io_allowed} />
              <Gate label="外部账户证据" value={paperControls.external_paper_account_evidence} />
              <Gate label="手机送达回执" value={paperControls.phone_notification_receipt} />
            </div>
            <ul className="mt-4 divide-y divide-border/60">
              {paperControls.actions.map((action) => (
                <li key={action.action} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <span className="text-sm">{paperActionLabel(action.action)}</span>
                  <span className="text-xs text-secondary-text">{paperReasonLabel(action.reason)}</span>
                  <span className={action.available ? 'rounded-full bg-success/15 px-2.5 py-1 text-xs font-semibold text-success' : 'rounded-full bg-warning/15 px-2.5 py-1 text-xs font-semibold text-warning'}>
                    {action.available ? (action.action === 'run_offline_simulation' ? '可运行' : '可查看') : '未开放'}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-warning">权限接口固定为只读：不连接券商、不读取行情、不提交或撤改单。</p>
          </>
        )}
      </Card>
      <OfflineSimulationCard />
      <Card className="mt-4" title="待验收事项" subtitle="ACCEPTANCE QUEUE">
        <ul className="space-y-2 text-sm text-secondary-text">
          {status.pending_acceptance.map((item) => <li key={item}>• {item}</li>)}
        </ul>
      </Card>
    </AppPage>
  );
};

export default OperationsPage;

