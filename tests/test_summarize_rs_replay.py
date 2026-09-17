"""Regression guards for diagnostic replay summary / holdout boundaries."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.summarize_rs_replay import summarize_replay


def _replay():
    # Three equal partitions; the last two rows in each partition have
    # forward outcomes past its boundary and must not enter split metrics.
    return {
        'schema': 'radar-rs-replay-v0.1',
        'top_k': 2,
        'forward_bars': 2,
        'rows': [
            {'as_of': f'2026-01-{i + 1:02}', 'top': [
                {'symbol': 'AAA', 'forward_return': 9.0 if i % 6 >= 4 else 0.1},
                {'symbol': 'BBB', 'forward_return': -9.0 if i % 6 >= 4 else -0.1},
            ]}
            for i in range(18)
        ],
    }


def test_replay_summary_excludes_global_metrics_and_false_holdout_label():
    result = summarize_replay(_replay(), 'recorded.json')

    assert result['status'] == 'RESEARCH_ONLY'
    assert result['guard'] == {
        'pit': 'RECORDED_CAPTURE_ONLY',
        'holdout_mode': 'DIAGNOSTIC_THIRD_ONLY',
        'promotion_eligible': False,
        'cross_split_forward_windows_excluded': True,
    }
    assert set(result['splits']) == {'development', 'validation', 'diagnostic_third'}
    assert 'top_k' not in result
    assert 'overall' not in result
    assert 'never_seen_holdout' not in json.dumps(result)
    assert all(metrics['observations'] == 8 for metrics in result['splits'].values())
    assert all(metrics['average_forward_return'] == pytest.approx(0.0)
               for metrics in result['splits'].values())
    assert all(metrics['win_rate'] == 0.5 for metrics in result['splits'].values())


@pytest.mark.parametrize('forward_bars', [None, 0, -1, True, 1.5])
def test_replay_summary_fails_closed_without_valid_forward_horizon(forward_bars):
    replay = _replay()
    replay['forward_bars'] = forward_bars
    with pytest.raises(ValueError, match='forward_bars'):
        summarize_replay(replay, 'recorded.json')


def test_cli_preserves_auditable_research_only_output(tmp_path):
    source = tmp_path / 'rs_replay.json'
    output = tmp_path / 'summary' / 'rs_summary.json'
    source.write_text(json.dumps(_replay()), encoding='utf-8')
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts' / 'summarize_rs_replay.py'),
               '--input', str(source), '--output', str(output)]
    process = subprocess.run(command, text=True, capture_output=True, check=True)
    assert json.loads(process.stdout)['status'] == 'SUMMARIZED'
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['source'] == str(source)
    assert result['guard']['promotion_eligible'] is False
    assert 'never_seen_holdout' not in output.read_text(encoding='utf-8')
    assert 'top_k' not in result
