"""Перерисовка сравнения FV для трех режимов по сохраненным сводкам.

Новых симуляций, бутстрепа и выбора поправки нет. Верхние границы берутся
из исходного теста без уменьшения семейства множественных сравнений.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import tempfile

cache = Path(tempfile.gettempdir()) / 'pnd-article-cache'
cache.mkdir(exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(cache / 'matplotlib'))
os.environ.setdefault('NUMBA_CACHE_DIR', str(cache / 'numba'))
os.environ.setdefault('XDG_CACHE_HOME', str(cache))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ARTICLE = Path(__file__).resolve().parents[1]
PROJECT = ARTICLE.parents[1]
sys.path.insert(0, str(PROJECT))
from hrfx.protocol import FlatArtifacts


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path,
                        default=PROJECT / 'experiments/correction_fv_frozen_test')
    args = parser.parse_args()
    out = ARTICLE / '_analysis'
    out.mkdir(exist_ok=True)
    source = args.input_dir
    regimes = ['nominal', 'param', 'structure']
    config = {
        'regimes': regimes,
        'weights': 'equal squared risks across 27 groups',
        'upper_bounds': 'unchanged from original test',
        'delta_eq': 0.001,
        'sources': {n: sha256(source / n)
                    for n in ['strata_test.csv', 'pooled_by_regime.csv', 'config.json']},
    }
    config_path = out / 'config.json'
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    run = FlatArtifacts(__file__, 'article-fv-three-regimes', 'saved_summary',
                        config_path=str(config_path), out_dir=str(out))

    raw = pd.read_csv(source / 'strata_test.csv', keep_default_na=False)
    groups = raw.loc[raw.regime.isin(regimes),
                     ['regime', 'dclass', 'soa', 'R_C', 'F3_R', 'F3_H_R', 'F3_H_R_U']].copy()
    assert len(groups) == 27
    assert not groups.duplicated(['regime', 'dclass', 'soa']).any()
    assert set(groups.dclass) == {'nonzero', 'small', 'null'}
    assert set(groups.soa) == {2, 4, 8}
    groups['_regime'] = pd.Categorical(groups.regime, regimes, ordered=True)
    groups['_class'] = pd.Categorical(groups.dclass, ['nonzero', 'small', 'null'], ordered=True)
    groups = groups.sort_values(['_regime', '_class', 'soa']).drop(columns=['_regime', '_class'])
    assert np.allclose(groups.F3_H_R, groups.F3_R - groups.R_C, atol=1e-12)
    groups.to_csv(out / 'fv_groups.csv', index=False)

    pooled = []
    old = pd.read_csv(source / 'pooled_by_regime.csv')
    for regime in regimes + ['overall']:
        g = groups if regime == 'overall' else groups[groups.regime == regime]
        c = float(np.sqrt(np.mean(g.R_C ** 2)))
        fv = float(np.sqrt(np.mean(g.F3_R ** 2)))
        if regime != 'overall':
            reference = old[old.regime == regime].iloc[0]
            assert abs(c - reference.C) < 1e-10
            assert abs(fv - reference.F3) < 1e-10
        pooled.append({'regime': regime, 'C': c, 'FV': fv, 'reduction': c - fv})
    pooled = pd.DataFrame(pooled)
    pooled.to_csv(out / 'fv_pooled.csv', index=False)
    summary = {
        'groups': len(groups),
        'upper_bound_above_tolerance': int((groups.F3_H_R_U > 0.001).sum()),
        'point_estimate_above_tolerance': int((groups.F3_H_R > 0.001).sum()),
        'overall': pooled.iloc[-1].to_dict(),
        'interpretation': 'descriptive subset; original simultaneous bounds retained',
    }
    (out / 'correction_summary.json').write_text(json.dumps(summary, indent=2) + '\n')

    plt.rcParams.update({
        'font.family': 'serif', 'font.serif': ['Times New Roman', 'Times', 'DejaVu Serif'],
        'mathtext.fontset': 'stix', 'pdf.fonttype': 42, 'ps.fonttype': 42,
        'font.size': 8.5, 'axes.labelsize': 9, 'axes.titlesize': 9,
        'xtick.labelsize': 8, 'ytick.labelsize': 8, 'legend.fontsize': 8,
        'axes.linewidth': 0.8,
    })
    fig = plt.figure(figsize=(16 / 2.54, 9 / 2.54))
    left = fig.add_axes([0.11, 0.23, 0.35, 0.53])
    right = fig.add_axes([0.62, 0.23, 0.35, 0.53])
    xs = np.arange(4)
    bars_c = left.bar(xs - 0.18, pooled.C, 0.36, color='#4a7bb0', label='C')
    bars_fv = left.bar(xs + 0.18, pooled.FV, 0.36, color='#e67e22', label='FV')
    left.set_xticks(xs, ['Nominal', 'Param.', 'Struct.', 'Overall'])
    left.set_ylabel(r'Contrast RMSE ($a$ units)')
    left.set_title('Contrast RMSE by regime')
    left.set_ylim(0, 0.026)
    fig.legend(handles=[bars_c, bars_fv], loc='upper center',
               bbox_to_anchor=(0.29, 0.985), ncol=2, frameon=False)

    x = np.arange(27)
    point, = right.plot(x, groups.F3_H_R, 'o', ms=3.5, color='#e67e22', label='Point estimate')
    upper, = right.plot(x, groups.F3_H_R_U, '_', ms=5, mew=1.2,
                        color='#2c3e50', label='Upper bound')
    right.axhline(0, color='gray', lw=0.5, ls=':')
    limit = right.axhline(0.001, color='red', ls='--', lw=1, label='Limit = 0.001')
    for sep in [8.5, 17.5]:
        right.axvline(sep, color='lightgray', lw=0.8, ls=':')
    for center, label in zip([4, 13, 22], ['Nominal', 'Parameter', 'Structure']):
        right.text(center, 0.004, label, fontsize=8, ha='center', color='#555555')
    right.set_xlim(-1, 27)
    right.set_ylim(-0.026, 0.007)
    right.set_xticks([0, 4, 8, 13, 17, 21, 26])
    right.set_xlabel('Group index')
    right.set_ylabel(r'$H_R=R_{\mathrm{FV}}-R_C$')
    right.set_title('Deterioration across 27 groups')
    fig.legend(handles=[point, upper, limit], loc='upper center',
               bbox_to_anchor=(0.80, 0.985), ncol=1, frameon=False)
    for ax, label in [(left, 'a'), (right, 'b')]:
        pos = ax.get_position()
        fig.text(pos.x0 - 0.025, 0.09, label, fontstyle='italic', fontsize=11)
    for ext in ['pdf', 'png']:
        fig.savefig(ARTICLE / 'Figure' / f'fig_7.{ext}', dpi=300)
    plt.close(fig)
    run.log()
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
