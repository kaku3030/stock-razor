import type React from 'react';
import { useEffect, useMemo, useRef } from 'react';
import { dispose, init } from 'klinecharts';

import {
  canonicalBarsToKLineData,
  timeframeToKLinePeriod,
  type CanonicalMarketBar,
  type CanonicalTimeframe,
} from './klineAdapter';

export interface CanonicalKLineChartProps {
  symbol: string;
  timeframe: CanonicalTimeframe;
  bars: CanonicalMarketBar[];
  locale?: string;
  timezone?: string;
  theme?: 'light' | 'dark';
  pricePrecision?: number;
  volumePrecision?: number;
  className?: string;
}

/**
 * Read-only chart renderer for already-qualified canonical bars.
 *
 * The component performs no provider I/O and owns no market-data authority.
 * Streaming/fetching must remain in the backend data plane. Realtime wiring
 * should feed this component only after server-side auth and currentness gates.
 */
export const CanonicalKLineChart: React.FC<CanonicalKLineChartProps> = ({
  symbol,
  timeframe,
  bars,
  locale = 'zh-CN',
  timezone = 'Asia/Shanghai',
  theme = 'dark',
  pricePrecision = 2,
  volumePrecision = 0,
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const data = useMemo(() => canonicalBarsToKLineData(bars), [bars]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

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
    if (!chart) return undefined;

    chart.setSymbol({
      ticker: symbol,
      pricePrecision,
      volumePrecision,
    });
    chart.setPeriod(timeframeToKLinePeriod(timeframe));
    chart.setDataLoader({
      getBars: ({ callback }) => {
        callback(data, { forward: false, backward: false });
      },
    });
    chart.resetData();

    return () => {
      dispose(container);
    };
  }, [
    data,
    locale,
    pricePrecision,
    symbol,
    theme,
    timeframe,
    timezone,
    volumePrecision,
  ]);

  return (
    <div
      ref={containerRef}
      className={'min-h-[320px] w-full ' + className}
      data-testid="canonical-kline-chart"
    />
  );
};
