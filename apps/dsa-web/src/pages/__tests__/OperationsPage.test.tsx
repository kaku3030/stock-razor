import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OperationsPage from '../OperationsPage';

const { getStatus, getUSLiveMonitor } = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getUSLiveMonitor: vi.fn(),
}));

vi.mock('../../api/operations', () => ({
  operationsApi: { getStatus, getUSLiveMonitor },
}));

beforeEach(() => {
  vi.clearAllMocks();
  getStatus.mockResolvedValue({
    mode: 'research_only',
    radar_admission: 'BLOCKED',
    source_arbiter_admission: 'BLOCKED',
    live_trade: false,
    paper_auto_ready: false,
    paper_engine_status: 'IMPLEMENTED_OFFLINE_ONLY',
    offline_simulation_status: 'READY_EXPLICIT_OFFLINE_RUN_EXTERNAL_BROKER_NOT_CONNECTED',
    paper_runtime_api_status: 'NOT_EXPOSED',
    execution_recovery_projection_status: 'READ_ONLY',
    paper_runtime_store_config_status: 'NOT_CONFIGURED',
    trade_plan_status: 'READ_ONLY',
    position_management_status: 'READ_ONLY',
    trade_lifecycle_status: 'READ_ONLY',
    notification_channels_configured: [],
    notification_routes: { report: [], alert: [], system_error: [] },
    notification_delivery_evidence: 'NOT_VERIFIED',
    notification_ready: false,
    pending_acceptance: [],
  });
  getUSLiveMonitor.mockResolvedValue({
    source: 'CLOUD_CANONICAL_OPEND_CACHE',
    status: 'BLOCKED_OR_STALE',
    source_identity_matched: false,
    health: {
      status: 'STALE', heartbeat_age_seconds: 45, bar_closure_proven: false,
      latest_push_observations: {
        'US.QQQ': {
          symbol: 'US.QQQ', time_key: '2026-10-20 06:30:00',
          received_at_utc: '2026-10-20T10:29:07Z', open: 715.5,
          high: 715.6, low: 715.4, close: 715.5082, volume: 1,
          age_seconds: 2, freshness_status: 'FRESH', bar_closure: 'UNPROVEN',
          research_eligible: false,
        },
      },
      radar_admission: 'BLOCKED', live_trade: false,
    },
    market: {
      status: 'STALE',
      source_age_seconds: 130,
      read_latency_ms: 2,
      symbols: {
        'US.QQQ': {
          latest: {
            '1m': {
              bar_end_utc: '2026-10-20T13:30:00Z',
              open: 600,
              high: 602,
              low: 599,
              close: 601,
              volume: 12345,
              is_closed: true,
              health: { grade: 'good', quality_flags: [] },
            },
          },
        },
      },
      radar_admission: 'BLOCKED',
      live_trade: false,
    },
    radar_admission: 'BLOCKED',
    live_trade: false,
  });
});

describe('OperationsPage', () => {
  it('shows cloud OpenD bars and keeps stale evidence visibly blocked', async () => {
    render(<OperationsPage />);

    expect(await screen.findByText('US.QQQ / 1m')).toBeInTheDocument();
    expect(screen.getByText('600 / 602 / 599 / 601')).toBeInTheDocument();
    expect(screen.getByText('12345')).toBeInTheDocument();
    expect(screen.getByText('阻塞 / 过期 / 未验证')).toBeInTheDocument();
    expect(screen.getByLabelText('Unclosed OpenD callback observations')).toBeInTheDocument();
    expect(screen.getByText('715.5 / 715.6 / 715.4 / 715.5082')).toBeInTheDocument();
    expect(screen.getAllByText(/BLOCKED/).length).toBeGreaterThan(0);
    expect(getUSLiveMonitor).toHaveBeenCalledWith();
  });
});
