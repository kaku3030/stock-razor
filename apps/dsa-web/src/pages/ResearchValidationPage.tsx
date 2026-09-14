import React, { useState } from 'react';

type Summary = { splits?: Record<string, { average_forward_return?: number; win_rate?: number; observations?: number }>; top_k?: Record<string, { average_forward_return?: number; win_rate?: number }> };
type Counterfactual = { variants?: Record<string, { cumulative_return_net?: number; hit_rate?: number; max_drawdown?: number; coverage?: number }> };

const pct = (value?: number) => value == null ? '--' : `${(value * 100).toFixed(2)}%`;

const ResearchValidationPage: React.FC = () => {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [counterfactual, setCounterfactual] = useState<Counterfactual | null>(null);
  const [error, setError] = useState('');
  const [ruleId, setRuleId] = useState('rs-baseline');
  const [symbol, setSymbol] = useState('universe');
  const [holdoutId, setHoldoutId] = useState('never-seen-v0.1');
  const [developmentEnd, setDevelopmentEnd] = useState('2024-12-31');
  const [validationEnd, setValidationEnd] = useState('2025-12-31');

  const loadLatestArtifact = async () => {
    try {
      const response = await fetch('/api/v1/research-validation/artifact');
      if (!response.ok) throw new Error('artifact unavailable');
      const payload = await response.json();
      const files = payload.files || {};
      const summaryFile = Object.entries(files).find(([name]) => name.endsWith('rs_summary.json'))?.[1] as Summary | undefined;
      const counterfactualFile = Object.entries(files).find(([name]) => name.endsWith('counterfactual.json'))?.[1] as Counterfactual | undefined;
      if (summaryFile) setSummary(summaryFile);
      if (counterfactualFile) setCounterfactual(counterfactualFile);
      setError(summaryFile || counterfactualFile ? '' : 'Artifact 中未找到研究 JSON');
    } catch { setError('无法读取最新 Artifact，请确认服务端已配置 RADAR_GITHUB_TOKEN'); }
  };

  const submitResearch = async () => {
    try {
      const response = await fetch('/api/v1/research-validation/submit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rule_id: ruleId, symbol, development_end: developmentEnd, validation_end: validationEnd, holdout_id: holdoutId, research_only: true }) });
      if (!response.ok) throw new Error('submit failed');
      const payload = await response.json();
      setError(`已登记研究任务：${payload.task_id}`);
    } catch { setError('研究任务登记失败'); }
  };

  const exportConfig = () => {
    const payload = { schema: 'radar-rule-validation-experiment-v0.1', rule_version: 'RS / baseline counterfactual v0.1', universe: 'frozen-research-universe-v0.1', symbols: 17, cost_bps: 10, slippage_bps: 5, splits: ['development', 'validation', 'never_seen_holdout'], production_promotion: 'LOCKED' };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'radar-experiment-config.json'; anchor.click(); URL.revokeObjectURL(url);
  };

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
        <div className="mt-2 flex flex-wrap items-center gap-3"><p className="text-sm text-secondary-text">研究回测控制台（证据读取模式）</p><a className="text-sm text-primary underline" href="https://github.com/kaku3030/stock-razor/actions/workflows/research-universe-capture.yml" target="_blank" rel="noreferrer">打开最新 CI / 下载 Artifact</a></div>
      </header>
      <section className="grid gap-4 lg:grid-cols-3">
        <div className="card-surface space-y-4 rounded-2xl p-5">
          <h2 className="font-medium">实验参数</h2>
          <label className="block text-sm">规则 ID<input className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value={ruleId} onChange={(e) => setRuleId(e.target.value)} /></label>
          <label className="block text-sm">研究股票池<input className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value={symbol} onChange={(e) => setSymbol(e.target.value)} /></label>\n          <label className="block text-sm">开发结束日<input type="date" className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value={developmentEnd} onChange={(e) => setDevelopmentEnd(e.target.value)} /></label>\n          <label className="block text-sm">验证结束日<input type="date" className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value={validationEnd} onChange={(e) => setValidationEnd(e.target.value)} /></label>\n          <label className="block text-sm">Holdout ID<input className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value={holdoutId} onChange={(e) => setHoldoutId(e.target.value)} /></label>
          <label className="block text-sm">加载 RS summary<input className="mt-2 block w-full text-xs" type="file" accept=".json" onChange={(e) => e.target.files?.[0] && loadJson(e.target.files[0], 'summary')} /></label>
          <label className="block text-sm">加载 counterfactual<input className="mt-2 block w-full text-xs" type="file" accept=".json" onChange={(e) => e.target.files?.[0] && loadJson(e.target.files[0], 'counterfactual')} /></label>
          <button className="btn-primary w-full" type="button" onClick={exportConfig}>导出实验配置 JSON</button>\n          <button className="btn-secondary w-full" type="button" onClick={loadLatestArtifact}>读取最新 CI Artifact</button>\n          <button className="btn-secondary w-full" type="button" onClick={submitResearch}>登记研究实验（仅研究）</button>
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
