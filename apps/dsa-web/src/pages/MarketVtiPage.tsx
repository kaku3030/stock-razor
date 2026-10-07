import type React from 'react';
import { useCallback, useMemo, useState } from 'react';
import { useTheme } from 'next-themes';

import { SecureVtiKLineChart, type VtiBridgeState } from '../components/market/SecureVtiKLineChart';
import type { VtiTimeframe } from '../api/vti';
import { useUiLanguage } from '../contexts/UiLanguageContext';

const TIMEFRAMES: VtiTimeframe[] = ['1m', '5m', '15m', '1h'];

function normalizeSymbol(value: string): string {
  return value.trim().toUpperCase().replace(/^US./, '');
}

const MarketVtiPage: React.FC = () => {
  const { t } = useUiLanguage();
  const { resolvedTheme } = useTheme();
  const [draftSymbol, setDraftSymbol] = useState('AMD');
  const [symbol, setSymbol] = useState('AMD');
  const [timeframe, setTimeframe] = useState<VtiTimeframe>('15m');
  const [bridgeState, setBridgeState] = useState<VtiBridgeState | null>(null);

  const chartTheme = resolvedTheme === 'light' ? 'light' : 'dark';
  const normalizedDraft = useMemo(() => normalizeSymbol(draftSymbol), [draftSymbol]);

  const applySymbol = useCallback(() => {
    if (!normalizedDraft) return;
    setBridgeState(null);
    setSymbol(normalizedDraft);
  }, [normalizedDraft]);

  const sourceAge = typeof bridgeState?.sourceAgeSeconds === 'number'
    ? bridgeState.sourceAgeSeconds.toFixed(1) + 's'
    : '--';

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-4 px-4 py-4 sm:px-6">
      <section className="rounded-2xl border border-subtle bg-surface/80 p-4 shadow-sm">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
          <div>
            <h1 className="text-xl font-semibold text-foreground">{t('vti.title')}</h1>
            <p className="mt-1 max-w-3xl text-sm text-secondary-text">{t('vti.description')}</p>
            <p className="mt-2 text-xs font-medium text-warning">{t('vti.researchOnly')}</p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="grid gap-1 text-xs text-secondary-text">
              <span>{t('vti.symbol')}</span>
              <div className="flex gap-2">
                <input
                  value={draftSymbol}
                  onChange={(event) => setDraftSymbol(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') applySymbol();
                  }}
                  placeholder={t('vti.symbolPlaceholder')}
                  className="input-surface input-focus-glow h-10 w-44 rounded-xl border bg-transparent px-3 text-sm uppercase text-foreground outline-none"
                  aria-label={t('vti.symbol')}
                />
                <button
                  type="button"
                  className="btn-primary h-10 rounded-xl px-4 text-sm"
                  disabled={!normalizedDraft}
                  onClick={applySymbol}
                >
                  {t('vti.apply')}
                </button>
              </div>
            </label>

            <div className="grid gap-1 text-xs text-secondary-text">
              <span>{t('vti.timeframe')}</span>
              <div className="flex rounded-xl border border-subtle bg-base/50 p-1">
                {TIMEFRAMES.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={
                      'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ' +
                      (timeframe === item
                        ? 'bg-primary text-primary-foreground'
                        : 'text-secondary-text hover:bg-surface hover:text-foreground')
                    }
                    onClick={() => {
                      setBridgeState(null);
                      setTimeframe(item);
                    }}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          [t('vti.status'), bridgeState?.status ?? '--'],
          [t('vti.source'), bridgeState?.source ?? '--'],
          [t('vti.cache'), bridgeState?.cacheStatus ?? '--'],
          [t('vti.sourceAge'), sourceAge],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border border-subtle bg-surface/70 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-muted-text">{label}</div>
            <div className="mt-1 truncate font-mono text-xs text-foreground" title={value}>
              {value}
            </div>
          </div>
        ))}
      </section>

      <section className="rounded-2xl border border-subtle bg-surface/80 p-3 shadow-sm">
        <div className="mb-2 flex items-center justify-between px-1">
          <div>
            <span className="font-mono text-sm font-semibold text-foreground">US.{symbol}</span>
            <span className="ml-2 text-xs text-muted-text">{timeframe}</span>
          </div>
          <span className="text-[11px] text-muted-text">
            {bridgeState?.barCount ?? 0} bars
          </span>
        </div>

        <SecureVtiKLineChart
          symbol={symbol}
          timeframe={timeframe}
          theme={chartTheme}
          onBridgeState={setBridgeState}
          className="overflow-hidden rounded-xl"
        />
      </section>
    </div>
  );
};

export default MarketVtiPage;
