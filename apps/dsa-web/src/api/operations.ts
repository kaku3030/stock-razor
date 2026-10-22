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
  external_simulator_contract_status: string;
  simulated_account_evidence: string;
  notification_channels_configured: string[];
  notification_routes: Record<string, string[]>;
  notification_delivery_evidence: string;
  notification_ready: boolean;
  pending_acceptance: string[];
};

export type PaperOperatorControls = {
  schema_version: string;
  read_only: boolean;
  mutation_allowed: boolean;
  broker_io_allowed: boolean;
  provider_io_allowed: boolean;
  external_paper_account_evidence: string;
  phone_notification_receipt: string;
  actions: Array<{ action: string; available: boolean; reason: string }>;
};

export type OfflineSimulationRequest = {
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: string;
  limit_price: string;
  max_slippage?: string;
  simulate_fill?: boolean;
};

export type OfflineSimulationResponse = {
  scenario_id: string;
  environment: 'LOCAL_OFFLINE_SIMULATION';
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: string;
  limit_price: string;
  currency: 'USD' | 'CNY';
  runtime_state: string;
  order_state: string;
  filled_quantity: string;
  external_fill_confirmation: false;
  fill_source: 'LOCAL_SCENARIO_FIXTURE' | 'NONE';
  broker_io: false;
  provider_io: false;
  live_trade: false;
  note: string;
};

export const operationsApi = {
  async getStatus(): Promise<OperationsStatus> {
    const response = await apiClient.get<OperationsStatus>('/v1/operations/status');
    return response.data;
  },
  async getPaperControls(): Promise<PaperOperatorControls> {
    const response = await apiClient.get<PaperOperatorControls>('/v1/operations/paper-controls');
    return response.data;
  },
  async runOfflineSimulation(params: OfflineSimulationRequest): Promise<OfflineSimulationResponse> {
    const response = await apiClient.post<OfflineSimulationResponse>(
      '/v1/operations/offline-simulation',
      params,
    );
    return response.data;
  },
};

