import type { KLineData } from 'klinecharts';

export type CanonicalMarketBar = {
  bar_start_utc?: string | null;
  bar_end_utc: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  amount?: number | null;
  turnover?: number | null;
};

export type CanonicalTimeframe = '1m' | '5m' | '15m' | '60m' | '1h' | '1d';

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function canonicalBarsToKLineData(bars: CanonicalMarketBar[]): KLineData[] {
  const byTimestamp = new Map<number, KLineData>();

  for (const bar of bars) {
    if (![bar.open, bar.high, bar.low, bar.close].every(finite)) continue;

    const timestamp = Date.parse(bar.bar_start_utc || bar.bar_end_utc);
    if (!Number.isFinite(timestamp)) continue;

    const item: KLineData = {
      timestamp,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      volume: finite(bar.volume) ? bar.volume : 0,
    };

    const turnover = finite(bar.turnover)
      ? bar.turnover
      : finite(bar.amount)
        ? bar.amount
        : undefined;
    if (turnover !== undefined) {
      item.turnover = turnover;
    }

    byTimestamp.set(timestamp, item);
  }

  return [...byTimestamp.values()].sort((a, b) => a.timestamp - b.timestamp);
}

export function timeframeToKLinePeriod(timeframe: CanonicalTimeframe) {
  switch (timeframe) {
    case '1m':
      return { span: 1, type: 'minute' as const };
    case '5m':
      return { span: 5, type: 'minute' as const };
    case '15m':
      return { span: 15, type: 'minute' as const };
    case '60m':
    case '1h':
      return { span: 1, type: 'hour' as const };
    case '1d':
      return { span: 1, type: 'day' as const };
  }
}
