import type React from 'react';
import { useEffect, useState } from 'react';
import { Activity, BellRing, ShieldCheck } from 'lucide-react';
import { operationsApi, type OperationsStatus } from '../api/operations';
import { ApiErrorAlert, AppPage, Card, Loading, PageHeader } from '../components/common';
import { getParsedApiError, type ParsedApiError } from '../api/error';

const Gate: React.FC<{ label: string; value: string; safe?: boolean }> = ({ label, value, safe = false }) => (
  <div className="flex items-center justify-between gap-4 border-b border-border/60 py-3 last:border-b-0">
    <span className="text-sm text-secondary-text">{label}</span>
    <span className={safe ? 'rounded-full bg-success/15 px-2.5 py-1 text-xs font-semibold text-success' : 'rounded-full bg-warning/15 px-2.5 py-1 text-xs font-semibold text-warning'}>
      {value}
    </span>
  </div>
);

const notificationLabel = (channel: string): string => ({
  wechat: '企业微信',
  telegram: 'Telegram',
  feishu: '飞书',
  dingtalk: '钉钉',
  pushplus: 'PushPlus',
  serverchan3: 'Server酱',
}[channel] ?? channel);

const OperationsPage: React.FC = () => {
  const [status, setStatus] = useState<OperationsStatus | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);

  useEffect(() => {
    document.title = '运行控制台 - Stock Razor';
    void operationsApi.getStatus().then(setStatus).catch((err) => setError(getParsedApiError(err)));
  }, []);

  if (error) return <AppPage><ApiErrorAlert error={error} /></AppPage>;
  if (!status) return <AppPage><Loading /></AppPage>;

  return (
    <AppPage>
      <PageHeader title="运行控制台" description="通知、数据门禁与 Paper Trading 状态" />
      <div className="mt-4 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm text-warning">
        本页面只读。LIVE_TRADE 永远显示为关闭，不能从 WebUI 解锁真实交易。
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
          <p className="pt-2 text-xs text-secondary-text">配置成功不等于手机已收到；需完成真实接收回执。</p>
          <a className="mt-4 inline-block text-sm text-primary underline" href="/alerts">打开告警中心</a>
        </Card>
        <Card title="Paper Trading" subtitle="EXECUTION">
          <ShieldCheck className="mb-3 h-5 w-5 text-primary" />
          <Gate label="Paper Auto" value={status.paper_auto_ready ? 'READY' : 'BLOCKED'} safe={status.paper_auto_ready} />
          <Gate label="Live Trade" value={status.live_trade ? 'ON' : 'NO'} />
          <p className="pt-3 text-xs text-secondary-text">自动执行仍需独立重启、重连与对账验收。</p>
        </Card>
      </div>
      <Card className="mt-4" title="待验收事项" subtitle="ACCEPTANCE QUEUE">
        <ul className="space-y-2 text-sm text-secondary-text">
          {status.pending_acceptance.map((item) => <li key={item}>• {item}</li>)}
        </ul>
      </Card>
    </AppPage>
  );
};

export default OperationsPage;

