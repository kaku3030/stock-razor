import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { Activity, BellRing, RefreshCw, ShieldCheck, Signal } from 'lucide-react';
import { operationsApi, type OperationsStatus, type USLiveMonitor } from '../api/operations';
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
  discord: 'Discord',
  wechat: '��ҵ΢��',
  telegram: 'Telegram',
  feishu: '����',
  dingtalk: '����',
  pushplus: 'PushPlus',
  serverchan3: 'Server��',
}[channel] ?? channel);

const routeLabel = (route: string): string => ({
  report: '����',
  alert: '�澯',
  system_error: 'ϵͳ����',
}[route] ?? route);

const ageLabel = (seconds?: number): string => (
  typeof seconds === 'number' && Number.isFinite(seconds) ? `${Math.max(0, Math.round(seconds))}s` : 'δ֪'
);

const USLiveMonitorCard: React.FC<{ monitor: USLiveMonitor | null; error: string | null }> = ({ monitor, error }) => {
  const symbols = monitor?.market.symbols ?? {};
  const pushObservations = monitor?.health.latest_push_observations ?? {};
  return (
    <Card className="mt-4" title="OpenD ������" subtitle="ֻ���ƶ� canonical cache">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Signal className="h-5 w-5 text-primary" aria-hidden="true" />
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${monitor?.status === 'REALTIME_SOURCE_EVIDENCE' ? 'bg-success/15 text-success' : 'bg-warning/15 text-warning'}`}>
          {monitor?.status === 'REALTIME_SOURCE_EVIDENCE' ? 'Դ��ʵʱ֤��' : '���� / ���� / δ��֤'}
        </span>
        <span className="text-xs text-secondary-text">����Դ��{monitor?.source ?? 'CLOUD_CANONICAL_OPEND_CACHE'}</span>
      </div>
      {error && <p className="mb-3 text-sm text-warning">��ؽӿ��ݲ����ã�{error}</p>}
      {!error && !monitor && <p className="text-sm text-secondary-text">���ڶ�ȡ canonical cache��</p>}
      {monitor && (
        <>
          <div className="grid gap-2 text-xs text-secondary-text sm:grid-cols-2 lg:grid-cols-4">
            <div>����������{monitor.health.status ?? 'δ֪'} �� {ageLabel(monitor.health.heartbeat_age_seconds)}</div>
            <div>�������ʶȣ�{monitor.market.status ?? 'δ֪'} �� {ageLabel(monitor.market.source_age_seconds)}</div>
            <div>Provider callback��{typeof monitor.health.provider_callback_latency_ms === 'number' ? `${monitor.health.provider_callback_latency_ms.toFixed(1)} ms` : 'δ֪'}</div>
            <div>��ȡ��ʱ��{typeof monitor.market.read_latency_ms === 'number' ? `${monitor.market.read_latency_ms.toFixed(1)} ms` : 'δ֪'}</div>
          </div>
          <div className="mt-2 text-xs text-secondary-text">
            K �߱պ����գ�{monitor.health.bar_closure_proven ? '����֤' : 'δ��֤'} �� delivery mode {monitor.health.delivery_mode ?? 'δ֪'}
          </div>
          <div className="mt-3 text-xs text-secondary-text">
            Runtime {monitor.health.runtime_instance_id ?? 'δ֪'} �� SHA {monitor.health.repo_sha?.slice(0, 10) ?? 'δ֪'} �� ����ƥ�� {monitor.source_identity_matched ? '��' : '��'}
          </div>
          <section className="mt-4 rounded-lg border border-border/60 p-3" aria-label="Unclosed OpenD callback observations">
            <h3 className="text-sm font-semibold">Premarket and after-hours callbacks (closure unproven)</h3>
            <p className="mt-1 text-xs text-secondary-text">
              Last push {monitor.health.last_push_age_seconds !== undefined ? `${Math.round(monitor.health.last_push_age_seconds)}s ago` : 'unknown'} �� status {monitor.health.latest_push_status ?? 'unavailable'}
            </p>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[680px] text-left text-xs">
                <thead className="text-secondary-text"><tr><th className="py-2 pr-3">Symbol</th><th className="pr-3">Provider time key (raw)</th><th className="pr-3">Received UTC</th><th className="pr-3">OHLC</th><th className="pr-3">Volume</th><th>Freshness / closure</th></tr></thead>
                <tbody>
                  {Object.entries(pushObservations).map(([symbol, observation]) => (
                    <tr className="border-t border-border/60" key={`push-${symbol}`}>
                      <td className="py-2 pr-3 font-medium">{symbol}</td>
                      <td className="pr-3">{observation.time_key ?? 'unknown'}</td>
                      <td className="pr-3">{observation.received_at_utc ?? 'unknown'}</td>
                      <td className="pr-3">{`${observation.open ?? '��'} / ${observation.high ?? '��'} / ${observation.low ?? '��'} / ${observation.close ?? '��'}`}</td>
                      <td className="pr-3">{observation.volume ?? '��'}</td>
                      <td>{`${observation.freshness_status ?? 'unknown'} �� ${observation.age_seconds !== undefined ? `${observation.age_seconds.toFixed(1)}s` : 'unknown'} �� ${observation.bar_closure ?? 'UNPROVEN'}`}</td>
                    </tr>
                  ))}
                  {Object.keys(pushObservations).length === 0 && <tr><td className="py-2 text-secondary-text" colSpan={6}>No qualified OpenD push callback is available.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-xs">
              <thead className="text-secondary-text"><tr><th className="py-2 pr-3">��� / ����</th><th className="pr-3">Feed</th><th className="pr-3">K��ʱ�� UTC</th><th className="pr-3">OHLC</th><th className="pr-3">�ɽ���</th><th>����</th></tr></thead>
              <tbody>
                {Object.entries(symbols).flatMap(([symbol, item]) => ['1m', '5m', '15m', '1h'].map((frame) => {
                  const bar = item.latest?.[frame];
                  return (
                    <tr className="border-t border-border/60" key={`${symbol}-${frame}`}>
                      <td className="py-2 pr-3 font-medium">{symbol} / {frame}</td>
                      <td className="pr-3">{item.provider ?? 'δ֪'} / {item.feed ?? 'δ֪'}</td>
                      <td className="pr-3">{bar?.bar_end_utc ?? bar?.source_timestamp_utc ?? '������'}</td>
                      <td className="pr-3">{bar ? `${bar.open ?? '��'} / ${bar.high ?? '��'} / ${bar.low ?? '��'} / ${bar.close ?? '��'}` : '��'}</td>
                      <td className="pr-3">{bar?.volume ?? '��'}</td>
                      <td>{bar ? `${bar.is_closed === true ? 'source tag: closed' : 'source tag: open/unknown'}${bar.health?.grade ? ` �� ${bar.health.grade}` : ''}${bar.health?.quality_flags?.length ? ` �� ${bar.health.quality_flags.join(', ')}` : ''}` : '��'}</td>
                    </tr>
                  );
                }))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-warning">�˴�ֻ��ȡ�ƶ� canonical cache��Դ��ʵʱ֤�ݲ������������ա�Radar ʼ�� BLOCKED��Live Trade ʼ�չرա�</p>
        </>
      )}
    </Card>
  );
};

const OperationsPage: React.FC = () => {
  const [status, setStatus] = useState<OperationsStatus | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [liveMonitor, setLiveMonitor] = useState<USLiveMonitor | null>(null);
  const [liveMonitorError, setLiveMonitorError] = useState<string | null>(null);

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

  const loadLiveMonitor = useCallback(async () => {
    try {
      setLiveMonitor(await operationsApi.getUSLiveMonitor());
      setLiveMonitorError(null);
    } catch (err) {
      setLiveMonitorError(getParsedApiError(err).message);
    }
  }, []);

  useEffect(() => {
    document.title = '���п���̨ - Stock Razor';
    void loadStatus();
    void loadLiveMonitor();
    const timer = window.setInterval(() => void loadStatus(), 30_000);
    const monitorTimer = window.setInterval(() => void loadLiveMonitor(), 10_000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(monitorTimer);
    };
  }, [loadStatus, loadLiveMonitor]);

  if (error) return <AppPage><ApiErrorAlert error={error} /></AppPage>;
  if (!status) return <AppPage><Loading /></AppPage>;

  return (
    <AppPage>
      <PageHeader
        title="���п���̨"
        description="֪ͨ�������Ž��� Paper Trading ״̬"
        actions={(
          <div className="flex items-center gap-3">
            <span className="text-xs text-secondary-text">
              {checkedAt ? `������ ${checkedAt.toLocaleTimeString()}` : '���ڼ��'}
            </span>
            <button
              type="button"
              className="btn-secondary inline-flex items-center gap-2"
              onClick={() => void loadStatus()}
              disabled={refreshing}
            >
              <RefreshCw className={refreshing ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} aria-hidden="true" />
              ˢ��״̬
            </button>
          </div>
        )}
      />
      <div className="mt-4 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm text-warning">
        ��ҳ��ֻ����LIVE_TRADE ��Զ��ʾΪ�رգ����ܴ� WebUI ������ʵ���ס�
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <Card title="�����Ž�" subtitle="ADMISSION">
          <Activity className="mb-3 h-5 w-5 text-primary" />
          <Gate label="Radar" value={status.radar_admission} safe={status.radar_admission === 'PASS'} />
          <Gate label="Source Arbiter" value={status.source_arbiter_admission} safe={status.source_arbiter_admission === 'PASS'} />
          <Gate label="����ģʽ" value={status.mode} safe={status.mode === 'paper_only'} />
        </Card>
        <Card title="֪ͨ����" subtitle="NOTIFICATIONS">
          <BellRing className="mb-3 h-5 w-5 text-primary" />
          <Gate label="Webhook ����" value={status.notification_ready ? '������' : 'δ����'} safe={status.notification_ready} />
          <div className="pt-3 text-sm text-secondary-text">
            ������{status.notification_channels_configured.length ? status.notification_channels_configured.map(notificationLabel).join('��') : '����'}
          </div>
          <div className="mt-3 space-y-1 text-xs text-secondary-text">
            {Object.entries(status.notification_routes).map(([route, channels]) => (
              <div key={route} className="flex justify-between gap-3">
                <span>{routeLabel(route)}</span>
                <span>{channels.length ? channels.map(notificationLabel).join('��') : 'δ���ÿ�������'}</span>
              </div>
            ))}
          </div>
          <div className="pt-2 text-xs text-warning">
            �ֻ�����֤�ݣ�{status.notification_delivery_evidence}
          </div>
          <p className="pt-2 text-xs text-secondary-text">���óɹ��������ֻ����յ����������ʵ���ջ�ִ��</p>
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            <a className="text-primary underline" href="/alerts">�򿪸澯����</a>
            <a className="text-primary underline" href="/settings">֪ͨ���������</a>
          </div>
        </Card>
        <Card title="Paper Trading" subtitle="EXECUTION">
          <ShieldCheck className="mb-3 h-5 w-5 text-primary" />
          <Gate label="Paper Auto" value={status.paper_auto_ready ? 'READY' : 'BLOCKED'} safe={status.paper_auto_ready} />
          <Gate label="Paper ����" value={status.paper_engine_status} safe={status.paper_engine_status === 'IMPLEMENTED_OFFLINE_ONLY'} />
          <Gate label="����ģ����" value={status.offline_simulation_status} safe={status.offline_simulation_status.startsWith('READY_')} />
          <Gate label="Web �Զ�ִ�����" value={status.paper_runtime_api_status} />
          <Gate label="�쳣ִ�и���ͶӰ" value={status.execution_recovery_projection_status} />
          <Gate label="Paper Store ����" value={status.paper_runtime_store_config_status} />
          <Gate label="Trade Plan" value={status.trade_plan_status} />
          <Gate label="Position Management" value={status.position_management_status} />
          <Gate label="Trade Lifecycle" value={status.trade_lifecycle_status} />
          <Gate label="Live Trade" value={status.live_trade ? 'ON' : 'NO'} />
          <p className="pt-3 text-xs text-secondary-text">�Զ�ִ���������������������������ա�</p>
        </Card>
      </div>
      <USLiveMonitorCard monitor={liveMonitor} error={liveMonitorError} />
      <Card className="mt-4" title="����������" subtitle="ACCEPTANCE QUEUE">
        <ul className="space-y-2 text-sm text-secondary-text">
          {status.pending_acceptance.map((item) => <li key={item}>? {item}</li>)}
        </ul>
      </Card>
    </AppPage>
  );
};

export default OperationsPage;


