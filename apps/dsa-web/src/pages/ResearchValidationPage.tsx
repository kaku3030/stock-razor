import React, { useState } from 'react';

type Summary = { splits?: Record<string, { average_forward_return?: number; win_rate?: number; observations?: number }>; top_k?: Record<string, { average_forward_return?: number; win_rate?: number }> };
type Counterfactual = { variants?: Record<string, { cumulative_return_net?: number; hit_rate?: number; max_drawdown?: number; coverage?: number }> };

const pct = (value?: number) => value == null ? '--' : `${(value * 100).toFixed(2)}%`;

const ResearchValidationPage: React.FC = () => {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [counterfactual, setCounterfactual] = useState<Counterfactual | null>(null);
  const [error, setError] = useState('');

  const loadJson = (file: File, kind: 'summary' | 'counterfactual') => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result));
        if (kind === 'summary') setSummary(parsed); else setCounterfactual(parsed);
        setError('');
      } catch { setError('JSON 文件格式无法解析'); }
    };
    reader.readAsText(file);
  };

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 p-6">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-text">STOCK RAZOR / RADAR</p>
        <h1 className="mt-2 text-3xl font-semibold">Rule Validation Harness</h1>
        <p className="mt-2 text-sm text-secondary-text">研究回测控制台（证据读取模式）</p>
      </header>
      <section className="grid gap-4 lg:grid-cols-3">
        <div className="card-surface space-y-4 rounded-2xl p-5">
          <h2 className="font-medium">实验参数</h2>
          <label className="block text-sm">规则版本<input className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value="RS / baseline counterfactual v0.1" readOnly /></label>
          <label className="block text-sm">研究股票池<input className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value="Frozen universe · 17 symbols" readOnly /></label>
          <label className="block text-sm">加载 RS summary<input className="mt-2 block w-full text-xs" type="file" accept=".json" onChange={(e) => e.target.files?.[0] && loadJson(e.target.files[0], 'summary')} /></label>
          <label className="block text-sm">加载 counterfactual<input className="mt-2 block w-full text-xs" type="file" accept=".json" onChange={(e) => e.target.files?.[0] && loadJson(e.target.files[0], 'counterfactual')} /></label>
          <button className="btn-primary w-full" type="button" disabled>提交研究实验（即将开放）</button>
          <p className="text-xs text-muted-text">参数提交会经过 PIT、预算和 Holdout 门禁。</p>
          {error && <p className="text-xs text-danger">{error}</p>}
        </div>
        <div className="space-y-4 lg:col-span-2">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="card-surface rounded-2xl p-5"><p className="text-xs text-muted-text">主数据采集</p><p className="mt-2 text-2xl font-semibold text-success">17 / 17</p><p className="text-xs text-muted-text">Baostock / yfinance</p></div>
            <div className="card-surface rounded-2xl p-5"><p className="text-xs text-muted-text">RS Replay</p><p className="mt-2 text-2xl font-semibold">{summary ? Object.values(summary.splits || {}).reduce((n, x) => n + Number(x.observations || 0), 0).toLocaleString() : '1,900'}</p><p className="text-xs text-muted-text">观测记录</p></div>
            <div className="card-surface rounded-2xl p-5"><p className="text-xs text-muted-text">生产晋升</p><p className="mt-2 text-2xl font-semibold text-warning">LOCKED</p><p className="text-xs text-muted-text">研究证据只读</p></div>
          </div>
          <div className="card-surface rounded-2xl p-5"><h2 className="font-medium">分阶段结果</h2><div className="mt-4 grid gap-3 sm:grid-cols-3">{Object.entries(summary?.splits || {}).map(([name, value]) => <div key={name} className="rounded-xl border p-3"><p className="text-xs text-muted-text">{name}</p><p className="mt-2 text-sm">收益 {pct(value.average_forward_return)}</p><p className="text-sm">胜率 {pct(value.win_rate)}</p></div>)}</div>{!summary && <p className="mt-3 text-sm text-muted-text">加载 CI Artifact 的 rs_summary.json 后显示真实结果。</p>}</div>
          <div className="card-surface rounded-2xl p-5"><h2 className="font-medium">反事实结果</h2><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{Object.entries(counterfactual?.variants || {}).map(([name, value]) => <div key={name} className="rounded-xl border p-3"><p className="text-xs text-muted-text">{name}</p><p className="mt-2 text-sm">净收益 {pct(value.cumulative_return_net)}</p><p className="text-xs text-muted-text">回撤 {pct(value.max_drawdown)} · 覆盖 {pct(value.coverage)}</p></div>)}</div>{!counterfactual && <p className="mt-3 text-sm text-muted-text">加载 CI Artifact 的 counterfactual JSON 后显示真实结果。</p>}</div>
          <div className="card-surface rounded-2xl p-5"><h2 className="font-medium">治理状态</h2><p className="mt-3 text-sm text-secondary-text">PIT / anti-leak：HARD GATE · Never-Seen Holdout：PROTECTED · Data status：NOT_APPROVED</p></div>
        </div>
      </section>
    </main>
  );
};

export default ResearchValidationPage;
