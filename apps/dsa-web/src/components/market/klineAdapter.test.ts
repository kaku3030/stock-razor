import { describe, expect, it } from 'vitest';

import {
  canonicalBarsToKLineData,
  timeframeToKLinePeriod,
  type CanonicalMarketBar,
} from './klineAdapter';

function bar(overrides: Partial<CanonicalMarketBar> = {}): CanonicalMarketBar {
  return {
    bar_start_utc: '2026-10-07T13:30:00+00:00',
    bar_end_utc: '2026-10-07T13:31:00+00:00',
    open: 100,
    high: 102,
    low: 99,
    close: 101,
    volume: 1000,
    amount: 100_000,
    ...overrides,
  };
}

describe('canonicalBarsToKLineData', () => {
  it('uses millisecond timestamps and maps amount to turnover', () => {
    const result = canonicalBarsToKLineData([bar()]);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      timestamp: Date.parse('2026-10-07T13:30:00+00:00'),
      open: 100,
      high: 102,
      low: 99,
      close: 101,
      volume: 1000,
      turnover: 100_000,
    });
  });

  it('sorts and deduplicates by timestamp with latest payload winning', () => {
    const first = bar({ close: 101 });
    const duplicate = bar({ close: 103 });
    const later = bar({
      bar_start_utc: '2026-10-07T13:31:00+00:00',
      bar_end_utc: '2026-10-07T13:32:00+00:00',
      close: 104,
    });

    const result = canonicalBarsToKLineData([later, first, duplicate]);

    expect(result.map((item) => item.close)).toEqual([103, 104]);
  });

  it('drops invalid OHLC or timestamps instead of inventing chart data', () => {
    const result = canonicalBarsToKLineData([
      bar({ close: Number.NaN }),
      bar({ bar_start_utc: 'not-a-date' }),
    ]);

    expect(result).toEqual([]);
  });
});

describe('timeframeToKLinePeriod', () => {
  it('maps canonical timeframes to KLineChart v10 periods', () => {
    expect(timeframeToKLinePeriod('1m')).toEqual({ span: 1, type: 'minute' });
    expect(timeframeToKLinePeriod('15m')).toEqual({ span: 15, type: 'minute' });
    expect(timeframeToKLinePeriod('1h')).toEqual({ span: 1, type: 'hour' });
    expect(timeframeToKLinePeriod('1d')).toEqual({ span: 1, type: 'day' });
  });
});
