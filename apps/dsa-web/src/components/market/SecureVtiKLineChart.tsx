import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { dispose, init } from 'klinecharts';

import { vtiApi, type VtiTimeframe } from '../../api/vti';
import {
  canonicalBarsToKLineData,
  timeframeToKLinePeriod,
} from './klineAdapter';

export type VtiBridgeState = {
  status: string;
  source: string;
  sourceStatus: string;
  cacheStatus: string;
  barCount: number;
  sourceAgeSeconds?: number | null;
};

export interface SecureVtiKLineChartProps {
  symbol: string;
  timeframe: VtiTimeframe;
  refreshIntervalMs?: number;
  locale?: string;
  timezone?: string;
  theme?: 'light' | 'dark';
  pricePrecision?: number;
  volumePrecision?: number;
  className?: string;
  onBridgeState?: (state: VtiBridgeState) => void;
}

/**
 * Browser-safe VTI component.
 *
 * All data travels through the same-origin server bridge using the HttpOnly
 * admin session cookie. The browser never sees provider/OpenD credentials or
 * the internal snapshot-read bearer token.
 */
export const SecureVtiKLineChart: React.FC<SecureVtiKLineChartProps> = ({
  symbol,
  timeframe,
  refreshIntervalMs = 15_000,
  locale = 'zh-CN',
  timezone = 'America/New_York',
  theme = 'dark',
  pricePrecision = 2,
  volumePrecision = 0,
  className = '',
  onBridgeState,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    let disposed = false;
    let pollHandle: number | null = null;
    const chart = init(container, {
      locale,
      timezone,
      styles: theme,
      layout: {
        barSpaceLimit: { min: 2, max: 40 },
        pane: { minHeight: 120 },
        yAxis: { position: 'right' },
      },
    });
    if (!chart) {
      queueMicrotask(() => {
        if (!disposed) setError('Unable to initialize chart');
      });
      return undefined;
    }

    const emitState = (response: Awaited<ReturnType<typeof vtiApi.getBars>>) => {
      if (disposed) return;
      onBridgeState?.({
        status: response.status,
        source: response.source,
        sourceStatus: response.sourceStatus,
        cacheStatus: response.cacheStatus,
        barCount: response.barCount,
        sourceAgeSeconds: response.sourceAgeSeconds,
      });
    };

    chart.setSymbol({
      ticker: symbol.trim().toUpperCase(),
      pricePrecision,
      volumePrecision,
    });
    chart.setPeriod(timeframeToKLinePeriod(timeframe));
    chart.setDataLoader({
      async getBars({ type, timestamp, callback }) {
        if (disposed) return;
        if (type === 'backward') {
          callback([], { forward: false, backward: false });
          return;
        }

        try {
          const before = type === 'forward' && typeof timestamp === 'number'
            ? new Date(timestamp).toISOString()
            : undefined;
          const response = await vtiApi.getBars({
            symbol,
            timeframe,
            limit: 240,
            before,
          });
          if (disposed) return;
          const bars = canonicalBarsToKLineData(response.bars);
          setError(null);
          emitState(response);
          callback(bars, {
            forward: response.hasMoreBefore,
            backward: false,
          });
        } catch (err) {
          if (disposed) return;
          setError(err instanceof Error ? err.message : 'VTI data request failed');
          callback([], { forward: false, backward: false });
        }
      },
      subscribeBar({ callback }) {
        if (refreshIntervalMs <= 0 || disposed) return;

        const pollLatest = async () => {
          try {
            const response = await vtiApi.getBars({
              symbol,
              timeframe,
              limit: 2,
            });
            if (disposed) return;
            const bars = canonicalBarsToKLineData(response.bars);
            const latest = bars.at(-1);
            if (latest) {
              callback(latest);
            }
            setError(null);
            emitState(response);
          } catch (err) {
            if (disposed) return;
            setError(err instanceof Error ? err.message : 'VTI refresh failed');
          }
        };

        pollHandle = window.setInterval(() => {
          void pollLatest();
        }, refreshIntervalMs);
      },
      unsubscribeBar() {
        if (pollHandle !== null) {
          window.clearInterval(pollHandle);
          pollHandle = null;
        }
      },
    });
    chart.resetData();

    return () => {
      disposed = true;
      if (pollHandle !== null) {
        window.clearInterval(pollHandle);
        pollHandle = null;
      }
      dispose(container);
    };
  }, [
    locale,
    onBridgeState,
    pricePrecision,
    refreshIntervalMs,
    symbol,
    theme,
    timeframe,
    timezone,
    volumePrecision,
  ]);

  return (
    <div className={className}>
      {error ? (
        <div
          className="mb-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger"
          role="alert"
        >
          {error}
        </div>
      ) : null}
      <div
        ref={containerRef}
        className="min-h-[420px] w-full"
        data-testid="secure-vti-kline-chart"
      />
    </div>
  );
};
