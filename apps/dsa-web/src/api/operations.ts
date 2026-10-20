import apiClient from './index';

export type OperationsStatus = {
  mode: string;
  radar_admission: string;
  source_arbiter_admission: string;
  live_trade: boolean;
  paper_auto_ready: boolean;
  paper_engine_status: string;
  offline_simulation_status: string;
  paper_runtime_api_status: string;
  execution_recovery_projection_status: string;
  paper_runtime_store_config_status: string;
  trade_plan_status: string;
  position_management_status: string;
  trade_lifecycle_status: string;
  notification_channels_configured: string[];
  notification_routes: Record<string, string[]>;
  notification_delivery_evidence: string;
  notification_ready: boolean;
  pending_acceptance: string[];
};

export type USLiveMonitorBar = {
  bar_end_utc?: string;
  source_timestamp_utc?: string;
  close?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  is_closed?: boolean;
  health?: { grade?: string; quality_flags?: string[] };
};

export type USLiveMonitorPush = {
  symbol?: string;
  time_key?: string;
  received_at_utc?: string;
  age_seconds?: number;
  freshness_status?: 'FRESH' | 'STALE';
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  bar_closure?: 'UNPROVEN';
  research_eligible?: false;
};

export type USLiveMonitor = {
  source: 'CLOUD_CANONICAL_OPEND_CACHE';
  status: string;
  source_identity_matched: boolean;
  source_sequence_matched: boolean;
  health: {
    status?: string;
    heartbeat_age_seconds?: number;
    emitted_at_utc?: string;
    runtime_instance_id?: string;
    repo_sha?: string;
    delivery_mode?: string;
    realtime_delivery_evidence?: boolean;
    realtime_evidence_scope?: string;
    bar_closure_proven?: boolean;
    bar_closure?: string;
    provider_callback_latency_ms?: number;
    last_push_utc?: string;
    last_push_age_seconds?: number;
    latest_push_status?: string;
    latest_push_observations?: Record<string, USLiveMonitorPush>;
    read_latency_ms?: number;
    radar_admission: 'BLOCKED';
    live_trade: false;
  };
  market: {
    status?: string;
    market_state_us?: string;
    cache_session_us?: string;
    source_age_seconds?: number;
    publication_age_seconds?: number;
    read_latency_ms?: number;
    symbols?: Record<string, {
      provider?: string;
      feed?: string;
      counts?: Record<string, number>;
      latest?: Record<string, USLiveMonitorBar | null>;
    }>;
    radar_admission: 'BLOCKED';
    live_trade: false;
  };
  radar_admission: 'BLOCKED';
  live_trade: false;
};

export const operationsApi = {
  async getStatus(): Promise<OperationsStatus> {
    const response = await apiClient.get<OperationsStatus>('/v1/operations/status');
    return response.data;
  },
  async getUSLiveMonitor(symbols = ['US.AMD', 'US.QQQ']): Promise<USLiveMonitor> {
    const response = await apiClient.get<USLiveMonitor>('/v1/operations/us-live-monitor', {
      params: { symbols: symbols.join(',') },
    });
    return response.data;
  },
};

