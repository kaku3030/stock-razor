import type React from 'react';

const ResearchValidationPage: React.FC = () => (
  <main className="mx-auto w-full max-w-7xl space-y-6 p-6">
    <header>
      <p className="text-xs uppercase tracking-widest text-muted-text">STOCK RAZOR / RADAR</p>
      <h1 className="mt-2 text-3xl font-semibold">Rule Validation Harness</h1>
      <p className="mt-2 text-sm text-secondary-text">研究回测控制台（只读证据模式）</p>
    </header>
    <section className="grid gap-4 lg:grid-cols-3">
      <div className="card-surface space-y-4 rounded-2xl p-5 lg:col-span-1">
        <h2 className="font-medium">实验参数</h2>
        <label className="block text-sm">规则版本<input className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value="RS / baseline counterfactual v0.1" readOnly /></label>
        <label className="block text-sm">研究股票池<input className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value="Frozen universe · 17 symbols" readOnly /></label>
        <label className="block text-sm">成本与滑点<input className="input-surface mt-2 h-10 w-full rounded-xl border px-3" value="10 bps + 5 bps" readOnly /></label>
        <button className="btn-primary w-full" type="button" disabled>提交研究实验（即将开放）</button>
        <p className="text-xs text-muted-text">参数提交会经过 PIT、预算和 Holdout 门禁。</p>
      </div>
      <div className="space-y-4 lg:col-span-2">
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="card-surface rounded-2xl p-5"><p className="text-xs text-muted-text">主数据采集</p><p className="mt-2 text-2xl font-semibold text-success">17 / 17</p><p className="text-xs text-muted-text">Baostock / yfinance</p></div>
          <div className="card-surface rounded-2xl p-5"><p className="text-xs text-muted-text">RS Replay</p><p className="mt-2 text-2xl font-semibold">1,900</p><p className="text-xs text-muted-text">交易日</p></div>
          <div className="card-surface rounded-2xl p-5"><p className="text-xs text-muted-text">生产晋升</p><p className="mt-2 text-2xl font-semibold text-warning">LOCKED</p><p className="text-xs text-muted-text">研究证据 בלבד</p></div>
        </div>
        <div className="card-surface rounded-2xl p-5">
          <h2 className="font-medium">反事实结果</h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {['without_rule','with_rule','delayed_rule','shuffled_placebo','regime_conditioned'].map((name) => <div key={name} className="rounded-xl border p-3"><p className="text-xs text-muted-text">{name}</p><p className="mt-2 text-sm">等待最新 Artifact</p></div>)}
          </div>
        </div>
        <div className="card-surface rounded-2xl p-5"><h2 className="font-medium">治理状态</h2><p className="mt-3 text-sm text-secondary-text">PIT / anti-leak：HARD GATE · Never-Seen Holdout：PROTECTED · Data status：NOT_APPROVED</p></div>
      </div>
    </section>
  </main>
);

export default ResearchValidationPage;
