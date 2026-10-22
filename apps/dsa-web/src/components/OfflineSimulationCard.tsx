import { useState, type FormEvent } from 'react';
import { operationsApi, type OfflineSimulationResponse } from '../api/operations';
import { Card } from './common';
import { getParsedApiError } from '../api/error';

const OfflineSimulationCard = () => {
  const [symbol, setSymbol] = useState('TSLA');
  const [simulateFill, setSimulateFill] = useState(false);
  const [quantity, setQuantity] = useState('1');
  const [limitPrice, setLimitPrice] = useState('100');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<OfflineSimulationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const response = await operationsApi.runOfflineSimulation({
        symbol: symbol.trim().toUpperCase(),
        side: 'BUY',
        quantity,
        limit_price: limitPrice,
        simulate_fill: simulateFill,
      });
      setResult(response);
    } catch (err) {
      setError(getParsedApiError(err).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <Card className="mt-4" title="本地离线场景模拟" subtitle="只使用手动输入 / 每次运行独立隔离">
      <p className="mb-4 text-sm text-warning">
        这是手动场景演练，不读取实时行情或策略信号，也不连接券商；结果不会成为真实成交、账户余额或 Paper 自动运行凭证。
      </p>
      <form onSubmit={run} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="离线模拟参数">
        <label className="flex flex-col gap-1 text-xs text-secondary-text">
          标的代码
          <input
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            maxLength={12}
            required
            aria-label="标的代码"
            className="rounded border border-border bg-card px-3 py-2 text-sm text-foreground"
          />
        </label>
        <div className="flex flex-col justify-end gap-1 text-xs text-secondary-text">
          <span>方向</span>
          <span className="rounded border border-border bg-card px-3 py-2 text-sm text-foreground">买入</span>
        </div>
        <label className="flex flex-col gap-1 text-xs text-secondary-text">
          数量（A股按100份整手）
          <input
            type="number"
            min="0.000001"
            step="0.000001"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            required
            aria-label="数量"
            className="rounded border border-border bg-card px-3 py-2 text-sm text-foreground"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-secondary-text">
          限价
          <input
            type="number"
            min="0.000001"
            step="0.000001"
            value={limitPrice}
            onChange={(event) => setLimitPrice(event.target.value)}
            required
            aria-label="限价"
            className="rounded border border-border bg-card px-3 py-2 text-sm text-foreground"
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-secondary-text sm:col-span-2 lg:col-span-4">
          <input
            type="checkbox"
            checked={simulateFill}
            onChange={(event) => setSimulateFill(event.target.checked)}
          />
          演练时生成模拟成交（本地 fixture；不代表真实成交回报）
        </label>
        <button
          type="submit"
          disabled={running || !symbol.trim() || Number(quantity) <= 0 || Number(limitPrice) <= 0}
          className="btn-primary self-end"
        >
          {running ? '运行中…' : '运行离线模拟'}
        </button>
      </form>
      {error && <p role="alert" className="mt-3 text-sm text-danger">模拟运行失败：{error}</p>}
      {result && (
        <div role="status" className="mt-4 rounded border border-border p-3 text-sm">
          <div className="font-semibold">
            {result.symbol} · 买入 · {result.order_state}
          </div>
          <p className="mt-1 text-secondary-text">
            数量 {result.quantity} · 限价 {result.limit_price} {result.currency} · 场景模拟成交 {result.filled_quantity}
          </p>
          <p className="mt-1 text-xs text-warning">
            {result.fill_source === 'LOCAL_SCENARIO_FIXTURE'
              ? '成交由本地演练选项生成；external_fill_confirmation=false，不是券商成交回执。'
              : '委托处于本地模拟器的接受状态，未模拟成交；不代表真实券商接受。'}
          </p>
        </div>
      )}
    </Card>
  );
};

export default OfflineSimulationCard;
