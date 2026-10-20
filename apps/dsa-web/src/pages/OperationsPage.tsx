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

const ageLabel = (seconds?: number): string => (
  typeof seconds === 'number' && Number.isFinite(seconds) ? `${Math.max(0, Math.round(seconds))}s` : '未知'
);

const USLiveMonitorCard: React.FC<{ monitor: USLiveMonitor | null; error: string | null }> = ({ monitor, error }) => {
  const symbols = monitor?.market.symbols ?? {};
  const pushObservations = monitor?.health.latest_push_observations ?? {};
  return (
    <Card className="mt-4" title="OpenD 行情监控" subtitle="只读云端 canonical cache">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Signal className="h-5 w-5 text-primary" aria-hidden="true" />
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${monitor?.status === 'REALTIME_SOURCE_EVIDENCE' ? 'bg-success/15 text-success' : 'bg-warning/15 text-warning'}`}>
          {monitor?.status === 'REALTIME_SOURCE_EVIDENCE' ? '源级实时证据' : '阻塞 / 过期 / 未验证'}
        </span>
        <span className="text-xs text-secondary-text">数据源：{monitor?.source ?? 'CLOUD_CANONICAL_OPEND_CACHE'}</span>
      </div>
      {error && <p className="mb-3 text-sm text-warning">监控接口暂不可用：{error}</p>}
      {!error && !monitor && <p className="text-sm text-secondary-text">正在读取 canonical cache…</p>}
      {monitor && (
        <>
          <div className="grid gap-2 text-xs text-secondary-text sm:grid-cols-2 lg:grid-cols-4">
            <div>服务心跳：{monitor.health.status ?? '未知'} · {ageLabel(monitor.health.heartbeat_age_seconds)}</div>
            <div>行情新鲜度：{monitor.market.status ?? '未知'} · {ageLabel(monitor.market.source_age_seconds)}</div>
            <div>Provider callback：{typeof monitor.health.provider_callback_latency_ms === 'number' ? `${monitor.health.provider_callback_latency_ms.toFixed(1)} ms` : '未知'}</div>
            <div>读取耗时：{typeof monitor.market.read_latency_ms === 'number' ? `${monitor.market.read_latency_ms.toFixed(1)} ms` : '未知'}</div>
          </div>
          <div className="mt-2 text-xs text-secondary-text">
            K 线闭合验收：{monitor.health.bar_closure_proven ? '已验证' : '未验证'} · delivery mode {monitor.health.delivery_mode ?? '未知'}
          </div>
          <div className="mt-3 text-xs text-secondary-text">
            Runtime {monitor.health.runtime_instance_id ?? '未知'} · SHA {monitor.health.repo_sha?.slice(0, 10) ?? '未知'} · 身份匹配 {monitor.source_identity_matched ? '是' : '否'}
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-xs">
              <thead className="text-secondary-text"><tr><th className="py-2 pr-3">标的 / 周期</th><th className="pr-3">Feed</th><th className="pr-3">K线时间 UTC</th><th className="pr-3">OHLC</th><th className="pr-3">成交量</th><th>质量</th></tr></thead>
              <tbody>
                {Object.entries(symbols).flatMap(([symbol, item]) => ['1m', '5m', '15m', '1h'].map((frame) => {
                  const bar = item.latest?.[frame];
                  return (
                    <tr className="border-t border-border/60" key={`${symbol}-${frame}`}>
                      <td className="py-2 pr-3 font-medium">{symbol} / {frame}</td>
                      <td className="pr-3">{item.provider ?? '未知'} / {item.feed ?? '未知'}</td>
                      <td className="pr-3">{bar?.bar_end_utc ?? bar?.source_timestamp_utc ?? '无数据'}</td>
                      <td className="pr-3">{bar ? `${bar.open ?? '—'} / ${bar.high ?? '—'} / ${bar.low ?? '—'} / ${bar.close ?? '—'}` : '—'}</td>
                      <td className="pr-3">{bar?.volume ?? '—'}</td>
                      <td>{bar ? `${bar.is_closed === true ? 'source tag: closed' : 'source tag: open/unknown'}${bar.health?.grade ? ` · ${bar.health.grade}` : ''}${bar.health?.quality_flags?.length ? ` · ${bar.health.quality_flags.join(', ')}` : ''}` : '—'}</td>
                    </tr>
                  );
                }))}
              </tbody>
            </table>
          </div>
          <section className="mt-4 rounded-lg border border-border/60 p-3" aria-label="Unclosed OpenD callback observations">
            <h3 className="text-sm font-semibold">Premarket and after-hours callbacks (closure unproven)</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-secondary-text"><tr><th className="py-2 pr-3">Symbol</th><th className="pr-3">Provider time key (raw)</th><th className="pr-3">Received UTC</th><th className="pr-3">OHLC</th><th className="pr-3">Volume</th><th>Freshness / closure</th></tr></thead>
                <tbody>
                  {Object.entries(pushObservations).map(([symbol, observation]) => (
                    <tr key={symbol} className="border-t border-border/40">
                      <td className="py-2 pr-3">{symbol}</td>
                      <td className="pr-3">{observation.time_key ?? 'unknown'}</td>
                      <td className="pr-3">{observation.received_at_utc ?? 'unknown'}</td>
                      <td className="pr-3">{[observation.open, observation.high, observation.low, observation.close].every((value) => typeof value === 'number') ? `${observation.open} / ${observation.high} / ${observation.low} / ${observation.close}` : 'invalid'}</td>
                      <td className="pr-3">{observation.volume ?? 'unknown'}</td>
                      <td>{`${observation.freshness_status ?? 'unknown'} · ${observation.age_seconds !== undefined ? `${observation.age_seconds.toFixed(1)}s` : 'unknown'} · ${observation.bar_closure ?? 'UNPROVEN'}`}</td>
                    </tr>
                  ))}
                  {Object.keys(pushObservations).length === 0 && <tr><td className="py-2 text-secondary-text" colSpan={6}>No qualified OpenD push callback is available.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
          <p className="mt-3 text-xs text-warning">此处只读取云端 canonical cache；源级实时证据不代表逐标的验收。Radar 始终 BLOCKED，Live Trade 始终关闭。</p>
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
    document.title = '运行控制台 - Stock Razor';
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
              onClick={() => void loadStatus()}
              disabled={refreshing}
            >
              <RefreshCw className={refreshing ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} aria-hidden="true" />
              刷新状态
            </button>
          </div>
        )}
      />
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
          <Gate label="离线模拟盘" value={status.offline_simulation_status} safe={status.offline_simulation_status.startsWith('READY_')} />
          <Gate label="Web 自动执行入口" value={status.paper_runtime_api_status} />
          <Gate label="异常执行复核投影" value={status.execution_recovery_projection_status} />
          <Gate label="Paper Store 配置" value={status.paper_runtime_store_config_status} />
          <Gate label="Trade Plan" value={status.trade_plan_status} />
          <Gate label="Position Management" value={status.position_management_status} />
          <Gate label="Trade Lifecycle" value={status.trade_lifecycle_status} />
          <Gate label="Live Trade" value={status.live_trade ? 'ON' : 'NO'} />
          <p className="pt-3 text-xs text-secondary-text">自动执行仍需独立重启、重连与对账验收。</p>
        </Card>
      </div>
      <USLiveMonitorCard monitor={liveMonitor} error={liveMonitorError} />
      <Card className="mt-4" title="待验收事项" subtitle="ACCEPTANCE QUEUE">
        <ul className="space-y-2 text-sm text-secondary-text">
          {status.pending_acceptance.map((item) => <li key={item}>• {item}</li>)}
        </ul>
      </Card>
    </AppPage>
  );
};

export default OperationsPage;

