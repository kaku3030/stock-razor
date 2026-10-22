import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OperationsPage from '../OperationsPage';

const { getStatus, getPaperControls } = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getPaperControls: vi.fn(),
}));

vi.mock('../../api/operations', () => ({
  operationsApi: { getStatus, getPaperControls },
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
    external_simulator_contract_status: 'READY_READ_ONLY_UNVERIFIED_CLOUD_ACCOUNT',
    simulated_account_evidence: 'NOT_VERIFIED',
    notification_channels_configured: [],
    notification_routes: { report: [], alert: [], system_error: [] },
    notification_delivery_evidence: 'NOT_VERIFIED',
    notification_ready: false,
    pending_acceptance: [],
  });
  getPaperControls.mockResolvedValue({
    schema_version: 'paper_operator_controls_v0_1',
    read_only: true,
    mutation_allowed: false,
    broker_io_allowed: false,
    provider_io_allowed: false,
    external_paper_account_evidence: 'NOT_VERIFIED',
    phone_notification_receipt: 'NOT_VERIFIED',
    actions: [
      { action: 'inspect_operator_controls', available: true, reason: 'READ_ONLY_NO_SIDE_EFFECTS' },
      { action: 'submit_external_paper_order', available: false, reason: 'NO_AUTHORIZED_OPERATOR_OR_VERIFIED_ACCOUNT' },
    ],
  });
});

describe('OperationsPage paper permissions', () => {
  it('shows the read-only paper capability and blocked actions', async () => {
    render(<OperationsPage />);

    expect(await screen.findByText('Paper 操作权限')).toBeInTheDocument();
    expect(screen.getByText('提交模拟订单')).toBeInTheDocument();
    expect(screen.getByText('操作身份或模拟账户尚未验证')).toBeInTheDocument();
    expect(screen.getByText('未开放')).toBeInTheDocument();
    expect(screen.getByText('外部模拟盘契约')).toBeInTheDocument();
    expect(screen.getByText('离线可运行 / 未连券商')).toBeInTheDocument();
    expect(screen.getByText('只读契约 / 云账户未验证')).toBeInTheDocument();
    expect(screen.getAllByText('NOT_VERIFIED')).toHaveLength(3);
    expect(getPaperControls).toHaveBeenCalledWith();
  });

  it('keeps the operations page available when paper controls cannot be read', async () => {
    getPaperControls.mockRejectedValueOnce(new Error('controls unavailable'));
    render(<OperationsPage />);

    expect(await screen.findByText(/权限状态读取失败：/)).toBeInTheDocument();
    expect(screen.getByText('运行控制台')).toBeInTheDocument();
  });
});
