"""Independently audit exported historical S3 ledgers; never calls market/broker APIs.

This verifies ledger arithmetic, causality and entry-time risk constraints only.
It cannot rerun signals, mark-to-market returns or reconstruct missing OHLC paths.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ts(value):
    return datetime.fromisoformat(value)


def close(a, b, tol=1e-7):
    return abs(a-b) <= tol


def audit_ledger(path, summary):
    rows = read_csv(path)
    pnl=[]; active=[]; violations=[]; residuals=[]; riskfracs=[]
    max_open=0.;max_sector=0.;max_symbol=0.;max_positions=0;max_sector_positions=0
    holds=[];delays=[]
    for r in sorted(rows, key=lambda x: (x['entry_time'], x['symbol'])):
        n=float(r['units']); entry=float(r['entry_price']); exit=float(r['exit_price'])
        stop=float(r['stop_price']); rate=float(r['cost_bps_per_side'])/10000
        equity=float(r['equity_before']); recorded=float(r['net_pnl'])
        computed=n*(exit-entry-rate*(entry+exit))
        risk=n*(entry-stop+rate*(entry+stop))
        residuals.append(abs(recorded-computed));pnl.append(computed)
        riskfracs.append(risk/equity)
        entry_at=ts(r['entry_time']);decision_at=ts(r['decision_at'])
        checks={
            'NET_PNL':close(recorded,computed),
            'RISK_PER_SHARE':close(float(r['risk_per_share_at_entry']),risk/n),
            'PLANNED_RISK':close(float(r['planned_net_stop_risk']),risk),
            'NET_R':close(float(r['net_R']),computed/risk),
            'ENTRY_AFTER_DECISION':entry_at>decision_at,
            'DECISION_AFTER_SIGNAL_CLOSE':decision_at>ts(r['signal_bar_end']),
            'D1_AVAILABLE':ts(r['d1_available_at'])<=decision_at,
            'TARGET_2R':close(float(r['target_price']),entry+2*(entry-stop)),
            'POSITIVE_UNITS':n>0 and n==int(n),
            'STOP_BELOW_ENTRY':0<stop<entry,
            'RISK_025_PERCENT':risk/equity<=.0025+1e-12,
            'SYMBOL_NOTIONAL_20_PERCENT':n*entry/equity<=.20+1e-12,
            'CASH_NONNEGATIVE':float(r['cash_after_entry'])>=-1e-7,
        }
        active=[p for p in active if ts(p['exit_time'])>entry_at]
        same=[p for p in active if p['sector']==r['sector']]
        open_fraction=(sum(float(p['planned_net_stop_risk']) for p in active)+risk)/equity
        sector_fraction=(sum(float(p['planned_net_stop_risk']) for p in same)+risk)/equity
        max_open=max(max_open,open_fraction);max_sector=max(max_sector,sector_fraction)
        max_symbol=max(max_symbol,n*entry/equity)
        max_positions=max(max_positions,len(active)+1)
        max_sector_positions=max(max_sector_positions,len(same)+1)
        checks.update(OPEN_RISK_075_PERCENT=open_fraction<=.0075+1e-12,
                      SECTOR_RISK_050_PERCENT=sector_fraction<=.005+1e-12,
                      POSITIONS_CAP=len(active)<3,
                      SECTOR_POSITIONS_CAP=len(same)<2,
                      NO_DUPLICATE_SYMBOL=all(p['symbol']!=r['symbol'] for p in active))
        violations.extend({'signal_id':r['signal_id'],'check':k} for k,v in checks.items() if not v)
        active.append(r)
        holds.append((ts(r['exit_time'])-entry_at).total_seconds()/86400)
        delays.append((entry_at-decision_at).total_seconds()/60)
    winners=[p for p in pnl if p>0];losers=[p for p in pnl if p<0]
    net=sum(pnl);pf=sum(winners)/-sum(losers) if losers else None
    result={
        'file':str(path), 'sha256':digest(path), 'status':'LEDGER_ARITHMETIC_PASS' if not violations else 'FAIL',
        'scope':'EXISTING_HISTORICAL_LEDGER_AUDIT_NOT_NEW_BACKTEST',
        'trades':len(rows), 'net_pnl':net,'ending_cash_if_all_trades_settled':100000+net,
        'profit_factor':pf, 'win_rate':len(winners)/len(rows),
        'average_win_loss_ratio':(sum(winners)/len(winners))/(-sum(losers)/len(losers)),
        'average_holding_calendar_days':sum(holds)/len(holds),
        'average_observed_m5_holding_hours':sum(float(r['hold_m5_bars']) for r in rows)/len(rows)/12,
        'sample_end_liquidations':sum(r['boundary_liquidation'].lower()=='true' for r in rows),
        'max_pnl_formula_absolute_residual':max(residuals),
        'max_planned_trade_risk_fraction':max(riskfracs),
        'max_open_planned_risk_fraction_at_entry':max_open,
        'max_sector_planned_risk_fraction_at_entry':max_sector,
        'max_entry_symbol_notional_fraction':max_symbol,
        'max_positions_at_entry':max_positions,'max_sector_positions_at_entry':max_sector_positions,
        'min_entry_delay_minutes_after_decision':min(delays),
        'violations':violations,
        'summary_matches':{
            'trades':len(rows)==int(float(summary['trades'])),
            'net_pnl':close(net,float(summary['net_pnl'])),
            'profit_factor':close(pf,float(summary['profit_factor'])),
            'win_rate':close(len(winners)/len(rows),float(summary['win_rate'])),
            'ending_cash':close(100000+net,float(summary['final_equity'])),
        },
        'NOT_RECOMPUTABLE_WITHOUT_PRICE_PATHS':['mark_to_market_MDD','Sharpe','CAGR_including_exact_cashflow_timeline','recovery_time','gross_exposure_at_historical_marks','gap_or_intrabar_execution_correctness'],
    }
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    results=[]
    for folder in ['srvp_ablation_v1','srvp_ablation_58_gap_sensitivity']:
        summaries=read_csv(args.input/folder/'portfolio_comparison.csv')
        for path in sorted((args.input/folder).glob('*_10bps_trade_ledger.csv')):
            suffix='_10bps_trade_ledger.csv';base=path.name[:-len(suffix)]
            arm='SRVP_OFF' if base.endswith('SRVP_OFF') else 'SRVP_ON'
            window=base[:-len(arm)-1]
            summary=next(r for r in summaries if r['window']==window and r['arm']==arm and float(r['cost_bps_per_side'])==10)
            record=audit_ledger(path,summary);record.update(window=window,arm=arm,universe_scope=folder)
            results.append(record)
    signals=read_csv(args.input/'srvp_ablation_v1/full_2019_2026_signal_level_comparison_10bps.csv')
    signal_groups=[]
    for label, subset in [('full_exported_history',signals),('reused_2024_2026',[r for r in signals if r['decision_at']>='2024-01-01'])]:
        group={'window':label}
        for flag in ['True','False']:
            vals=[float(r['net_R']) for r in subset if r['srvp_pass']==flag and r['net_R']]
            group[flag]={'signals':len(vals),'mean_net_R':sum(vals)/len(vals)}
        group['SRVP_pass_minus_fail_mean_R']=group['True']['mean_net_R']-group['False']['mean_net_R']
        signal_groups.append(group)
    engine=args.input/'s3_candidate.py';source=engine.read_text()
    report={
        'stage':'EXISTING_ASSET_AUDIT_ONLY','TRADE_EXECUTION':'NO','promotion':'NO',
        'engine_sha256':digest(engine),
        'A_original_D1_H1_M15':{'status':'NOT_RECOVERED','evidence':[
            's3_candidate.py build_candidates consumes D1 and hourly, no M15 input.',
            's3_candidate.py entry uses next M5 open, not M15 confirmation.',
            'prior_audit report says US_SWING_D1_H1_M15 is next-stage research formalization and continuous M15 event path is not reconstructed.'
        ],'proxy_identity':'III_CAUSAL_RC0_D1_H1_BREAKOUT_NOT_ORIGINAL_S3',
        'no_15m_token_in_engine':all(s not in source.lower() for s in ['15m','m15','15min'])},
        'ledger_audits':results,
        'signal_group_arithmetic':signal_groups,
        'signal_ledger':{'rows':len(signals),'models':sorted({r['signal_model'] for r in signals}),
            'd1_available_after_decision':sum(ts(r['d1_available_at'])>ts(r['decision_at']) for r in signals),
            'last_decision_after_declared_20261016_160000_boundary':sum(ts(r['decision_at'])>datetime(2026,10,16,16) for r in signals)},
        'reusable':['sealed RC0 candidate/exit/risk functions as explicitly labeled proxy','existing signal/fill/skip/trade ledgers','D1/H1/M5 source-file hashes','real calendar and causal clock audit code'],
        'missing':['raw D1/H1/M5 OHLCV on currently offline Windows','complete executable original D1+H1+M15 rule contract','unseen/untouched OOS period','PIT historical membership and delisted universe','PIT corporate-action semantics','qualified exact QQQ baseline price path','actual brokerage fee schedule'],
        'limits':['2024-2026 history has already been repeatedly inspected: reused holdout is not untouched OOS','US60 current survivor universe; 58-name variant excludes LLY/VRT after data-quality review','60-name full SRVP_OFF remains BLOCKED_INCOMPLETE_PATH on LLY; do not replace it with 58-name performance','MDD values in original summary were not independently recomputed here; raw MTM paths unavailable','arithmetic and clock checks do not prove raw source correctness or statistical edge']
    }
    args.out.parent.mkdir(exist_ok=True,parents=True);args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'out':str(args.out),'ledgers':len(results),'trades':sum(r['trades'] for r in results),'violations':sum(len(r['violations']) for r in results),'all_summary_matches':all(all(r['summary_matches'].values()) for r in results)},indent=2))

if __name__=='__main__':main()
