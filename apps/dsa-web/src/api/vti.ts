import apiClient from './index';
import type { CanonicalMarketBar, CanonicalTimeframe } from '../components/market/klineAdapter';

export type VtiTimeframe = '1m' | '5m' | '15m' | '1h';

export type VtiBarsResponse = {
  ok: boolean;
  status: string;
  market: 'us';
  symbol: string;
  timeframe: CanonicalTimeframe;
  bars: CanonicalMarketBar[];
  barCount: number;
  hasMoreBefore: boolean;
  hasMoreAfter: boolean;
  source: string;
  sourceStatus: string;
  sourceAgeSeconds?: number | null;
  cacheStatus: string;
  cacheError?: string | null;
  researchOnly: boolean;
  canonicalAuthority: boolean;
  radarAdmission?: string;
  liveTrade: boolean;
};

type RawResponse = {
  ok?: boolean;
  status?: string;
  market?: string;
  symbol?: string;
  timeframe?: CanonicalTimeframe;
  bars?: CanonicalMarketBar[];
  bar_count?: number;
  has_more_before?: boolean;
  has_more_after?: boolean;
  source?: string;
  source_status?: string;
  source_age_seconds?: number | null;
  cache_status?: string;
  cache_error?: string | null;
  research_only?: boolean;
  canonical_authority?: boolean;
  radar_admission?: string;
  live_trade?: boolean;
};

export const vtiApi = {
  async getBars(params: {
    symbol: string;
    timeframe: VtiTimeframe;
    limit?: number;
    before?: string;
  }): Promise<VtiBarsResponse> {
    const response = await apiClient.get(
      '/api/v1/data/vti/bars/' + encodeURIComponent(params.symbol),
      {
        params: {
          timeframe: params.timeframe,
          limit: params.limit ?? 240,
          before: params.before,
        },
      },
    );
    const data = response.data as RawResponse;
    return {
      ok: Boolean(data.ok),
      status: data.status ?? 'UNKNOWN',
      market: 'us',
      symbol: data.symbol ?? params.symbol.toUpperCase(),
      timeframe: data.timeframe ?? params.timeframe,
      bars: Array.isArray(data.bars) ? data.bars : [],
      barCount: data.bar_count ?? 0,
      hasMoreBefore: Boolean(data.has_more_before),
      hasMoreAfter: Boolean(data.has_more_after),
      source: data.source ?? 'unknown',
      sourceStatus: data.source_status ?? 'UNKNOWN',
      sourceAgeSeconds: data.source_age_seconds,
      cacheStatus: data.cache_status ?? 'UNKNOWN',
      cacheError: data.cache_error,
      researchOnly: data.research_only !== false,
      canonicalAuthority: Boolean(data.canonical_authority),
      radarAdmission: data.radar_admission,
      liveTrade: Boolean(data.live_trade),
    };
  },
};
