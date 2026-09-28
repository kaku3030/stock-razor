#!/usr/bin/env python3
"""Summarize recorded RS replay into research-only diagnostic split metrics."""
import argparse
import json
from pathlib import Path


def summarize(rows, top_k):
    values = [x['forward_return'] for row in rows for x in row['top'][:top_k]]
    return {
        'observations': len(values),
        'average_forward_return': sum(values) / len(values) if values else 0.0,
        'win_rate': sum(v > 0 for v in values) / len(values) if values else 0.0,
    }


def summarize_replay(data, source):
    forward_bars = data.get('forward_bars')
    if type(forward_bars) is not int or forward_bars < 1:
        raise ValueError('positive integer forward_bars is required for split-boundary safety')
    rows = data['rows']
    top_k = data.get('top_k', 3)
    c1, c2 = len(rows) // 3, 2 * len(rows) // 3
    result = {
        'schema': 'radar-rs-summary-v0.1',
        'source': str(source),
        'status': 'RESEARCH_ONLY',
        'guard': {
            'pit': 'UNKNOWN',
            'holdout_exposure': 'UNKNOWN',
            'holdout_mode': 'DIAGNOSTIC_THIRD_ONLY',
            'promotion_eligible': False,
            'cross_split_forward_windows_excluded': True,
        },
        'splits': {},
    }
    for name, part in (
        ('development', rows[:c1]),
        ('validation', rows[c1:c2]),
        ('diagnostic_third', rows[c2:]),
    ):
        # An entry in the final forward_bars of a split has its outcome in the
        # following split; never include it in a split's reported metrics.
        result['splits'][name] = summarize(part[:-forward_bars], top_k)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    data = json.loads(a.input.read_text(encoding='utf-8'))
    result = summarize_replay(data, a.input)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps({'status': 'SUMMARIZED', 'output': str(a.output), 'summary': result}, sort_keys=True))


if __name__ == '__main__':
    main()
