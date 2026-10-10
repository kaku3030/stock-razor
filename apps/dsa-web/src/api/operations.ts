import apiClient from './index';

export type OperationsStatus = {
  mode: string;
  radar_admission: string;
  source_arbiter_admission: string;
  live_trade: boolean;
  paper_auto_ready: boolean;
  paper_engine_status: string;
  paper_runtime_api_status: string;
  notification_channels_configured: string[];
  notification_ready: boolean;
  pending_acceptance: string[];
};

export const operationsApi = {
  async getStatus(): Promise<OperationsStatus> {
    const response = await apiClient.get<OperationsStatus>('/v1/operations/status');
    return response.data;
  },
};

