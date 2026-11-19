#!/usr/bin/env python3
"""Build a deterministic, allowlisted numerical teaching dataset (inputs read-only).

Run with env -u PYTHONPATH .venv/bin/python scripts/docs_site_data.py.
All age calculations use the other engine's interpreter and the shared AGE_WORKER.
No source identities, calendar times or acquisition paths enter the public payload.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

from rawtims import branding
from rawtims.contract import (
    write_csv,
)
from rawtims.fractions import Fraction, fraction_row
from rawtims.oxide import correct
from rawtims.parity import (
    _view,
    drive_path,
    read_sheet_references,
    replay_project,
    sheets_path,
)
from rawtims.readers import open_run
from rawtims.readers.ionvantage_raw import (
    PB_WORKBOOK_RTOL,
    acquisition_config,
    dead_time,
    decode_raw,
    raw_folder,
    rejection_mean,
)
from rawtims.readers.trip import read_trip
from rawtims.recalculation import AGE_WORKER, PINNED_EXPORT_TIME, read_kd33_setup
from rawtims.reduction_params import as_acquired
from rawtims.reprocess import reprocess
from rawtims.rules import legacy_two_sigma_rejections

ROOT = Path(__file__).resolve().parents[1]
AGE_REPO = Path.home() / 'Github' / 'IDTIMS_UPbRPy'
PAIRS = ((206, 204), (206, 207), (206, 205), (207, 205), (204, 205), (208, 205))
LABELS = [f'{a}/{b}' for a, b in PAIRS]


def clean(value):
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    return value


def analysis(run, project):
    result = replay_project(_view(run, project), project)
    result.remember_legacy_masks()
    return result


def summary(a):
    return {label: {'mean': a.stats(f'{label} D').mean,
                    'se_pct': a.stats(f'{label} D').se_pct}
            for label in LABELS}


def worked_chain(run, params, decoded):
    """Expose one full decoder chain without changing engine code or source bytes.

    Same array shape/order as decode_raw is deliberate: its final subtraction is
    compared bit for bit. Only the first block's first three peak histories leave
    this function; all published times are seconds since run start.
    """
    folder = raw_folder(Path(run.raw.path))
    config, _ = acquisition_config(folder)
    method = next(folder.glob('*.ief')).read_text(errors='replace')
    integrations = [(int(total), int(step)) for total, step in
                    re.findall(r'^INTEGRATE,(\d+),(\d+)', method, re.MULTILINE)]
    counts = tuple(total // step for total, step in integrations[2:6])
    assert counts == (10, 5, 5, 5)
    assert all(step == 1000 and total % step == 0 for total, step in integrations)
    baseline_count = integrations[0][0] // integrations[0][1]
    assert baseline_count == integrations[1][0] // integrations[1][1] == 30
    raw = np.fromfile(folder / '_FUNC001.DAT', dtype='<f4').reshape(-1, 32, 2)
    channels = [int(config['CollectorMapping'][c]) for c in decoded.collectors]
    vals = raw[:, channels, 0].astype(float)
    d = decoded.collectors.index('Multiplier')
    f = decoded.collectors.index('High1')
    observed = vals[:, d].copy()
    for j, c in enumerate(decoded.collectors):
        if c == 'Multiplier':
            vals[:, j] = dead_time(vals[:, j], params.daly_dead_time_ns) * params.multiplier_gain
        else:
            vals[:, j] = (vals[:, j] - params.adc_zero) * params.adc_volts_per_code * params.faraday_gains[c]
            vals[:, j] /= params.faraday_resistors_ohm[c] * params.electron_charge_c
    avg = lambda x: rejection_mean(x, params.integration_rejection.sigma, params.integration_rejection.max_percent)
    baseline_halves = np.array([avg(vals[:30]), avg(vals[30:60])])
    baseline = baseline_halves.mean(axis=0)
    yy, tt, scan_rows = [], [], []
    pos = 60
    for history in range(3):
        cy, ct = [], []
        for seq, count in enumerate(counts):
            cy.append(avg(vals[pos:pos+count]))
            ct.append(raw[pos:pos+count, 0, 1].astype(float).mean())
            if history == 2 and seq == 2:
                scan_rows = [{'observed': float(observed[k]), 'corrected': float(vals[k, d])}
                             for k in range(pos, pos+count)]
                scan_start = pos
            pos += count
        yy.append(cy)
        tt.append(ct)
    yy, tt = np.array(yy), np.array(tt)
    t0 = (tt[0, 0] + tt[2, -1]) / 2
    tm, vm = tt.mean(axis=0), yy.mean(axis=0)
    slope = ((tt-tm)[:, :, None] * (yy-vm)).sum(axis=0) / (((tt-tm)**2).sum(axis=0)[:, None])
    gross = vm + slope * (t0-tm)[:, None]
    net = gross - baseline
    assert np.array_equal(net, decoded.intensities[0])
    # Entire first cycle with the alternative physics, including its baselines.
    alt = vals.copy()
    tau = params.daly_dead_time_ns * 1e-9
    par = observed.copy()
    for _ in range(12):
        ex = np.exp(-par*tau)
        par -= (par*ex-observed)/(ex*(1-par*tau))
    alt[:, d] = par * params.multiplier_gain
    alt_base = np.array([avg(alt[:30]), avg(alt[30:60])]).mean(axis=0)
    ay = []
    pos = 60
    for _ in range(3):
        cy = []
        for count in counts:
            cy.append(avg(alt[pos:pos+count])); pos += count
        ay.append(cy)
    ay = np.array(ay)
    avm = ay.mean(axis=0)
    asl = ((tt-tm)[:, :, None] * (ay-avm)).sum(axis=0) / (((tt-tm)**2).sum(axis=0)[:, None])
    anet = avm + asl * (t0-tm)[:, None] - alt_base
    workbook = float(run.column('206 D')[0])
    faraday_scan = scan_start-5  # S2: real mass-206 beam on High1
    code = float(raw[faraday_scan, channels[f], 0])
    volts = (code-params.adc_zero)*params.adc_volts_per_code*params.faraday_gains['High1']
    first = vals[scan_start:scan_start+5, d]
    return {'scans': scan_rows, 'scan_mean': float(avg(first)[0]),
            'scan_sd': float(first.std(ddof=1)), 'scan_arithmetic': float(first.mean()),
            'faraday': {'code': code, 'zero': params.adc_zero, 'v_per_code': params.adc_volts_per_code,
                        'gain': params.faraday_gains['High1'], 'volts': volts,
                        'resistor': params.faraday_resistors_ohm['High1'], 'charge': params.electron_charge_c,
                        'cps': float(vals[faraday_scan, f])},
            'history': [{'seconds': float(tt[k, 2]), 'mean': float(yy[k, 2, d])} for k in range(3)],
            't0': float(t0), 'time_mean': float(tm[2]),
            'value_mean': float(vm[2, d]), 'slope': float(slope[2, d]),
            'gross': float(gross[2, d]), 'baseline_low': float(baseline_halves[0, d]),
            'baseline_high': float(baseline_halves[1, d]), 'baseline': float(baseline[d]),
            'net': float(net[2, d]), 'decoded': float(decoded.intensities[0, 2, d]),
            'workbook': workbook, 'nonpar_relative_error': float(net[2, d]/workbook-1),
            'paralysable_net': float(anet[2, d]), 'par_relative_error': float(anet[2, d]/workbook-1)}


def build_data(*, folder=None, sheet=None, age_repo=AGE_REPO):
    folder = Path(folder) if folder else drive_path()
    sheet = Path(sheet) if sheet else sheets_path() / 'KD33_ BSULab_UPbR24XML.xls'
    runs = {e: open_run(folder / f'B1606_F15_KD33 z1 {e}-{s}.xls') for e, s in (('Pb', 56136), ('U', 56137))}
    projects = {e: read_trip(folder / f'KD33_z1_{e}{suffix}.trip') for e, suffix in (('Pb', ''), ('U', '_partial'))}
    pb, u = runs['Pb'], runs['U']
    params = as_acquired(pb)
    tau0 = params.daly_dead_time_ns
    acquired = analysis(pb, projects['Pb'])
    ua = analysis(u, projects['U'])
    decoded = decode_raw(raw_folder(Path(pb.raw.path)), replace(params, route='raw'))
    chain = worked_chain(pb, params, decoded)
    method = next(raw_folder(Path(pb.raw.path)).glob('*.ief')).read_text(errors='replace')
    integrations = [(int(total), int(step)) for total, step in
                    re.findall(r'^INTEGRATE,(\d+),(\d+)', method, re.MULTILINE)]
    masses = [float(m) for m in re.findall(r'^SET_MAGNET,([\d.]+)', method, re.MULTILINE)]
    sequences = decoded.intensities.shape[1]
    histories = len(chain['history'])
    setup, settings, _ = read_kd33_setup(sheet)
    def row(a):
        return fraction_row(Fraction('z1', pb=a, u=ua, timezone='America/Boise', **setup),
                            PINNED_EXPORT_TIME, allow_legacy_per_ratio=True)
    dcol = decoded.collectors.index('Multiplier')
    # Workbook acquired values are exactly the engine's cached acquired route;
    # raw values are intentionally kept separately for the evidence comparison.
    payload = {'tau0': tau0, 'block': pb.block, 'seconds': pb.time,
               'daly': {str(m): pb.column(f'{m} D') for m in (204, 205, 206, 207)},
               'baseline': decoded.baselines[:, dcol],
               'faraday206': pb.column('Pb206+At206 S2 int'), 'faraday208': pb.column('Pb208 S4 int'),
               'masks': {l: acquired.included_for(f'{l} D') for l in LABELS},
               'acquired_ratios': {l: pb.column(f'{l} D') for l in LABELS},
               'grid': [], 'raw': {}}
    # pb.time is seconds since acquisition start (checked against decoded t0).
    assert np.max(abs(pb.time-decoded.time)) < .01
    baseline_summary = summary(acquired)
    raw_runs = {}
    with tempfile.TemporaryDirectory(prefix=branding.APP_NAME + '-docs-') as tmp:
        tmp = Path(tmp)
        (tmp/'settings.json').write_text(json.dumps(settings, sort_keys=True))
        paths = []
        for tick in range(250, 501):
            tau = tick / 10
            reduced = reprocess(pb, replace(params, daly_dead_time_ns=tau))
            a = analysis(reduced, projects['Pb'])
            entry = {'tau': tau, 'ratios': summary(a)}
            payload['grid'].append(entry)
            p = tmp / f't{tick}.csv'; write_csv([row(a)], p); paths.append(p)
        for name, tau in (('raw36', tau0), ('raw40', 40.0)):
            reduced = reprocess(pb, replace(params, route='raw', daly_dead_time_ns=tau))
            a = analysis(reduced, projects['Pb'])
            raw_runs[name] = reduced
            payload['raw'][name] = {'tau': tau, 'ratios': summary(a)}
            p = tmp/f'{name}.csv'; write_csv([row(a)], p); paths.append(p)
        # Reuse the exact age worker; add a numerical-only view of its grain.
        fields = ['FPb', 'FPb_std', 'FU', 'FU_std', 'Pb205t', 'U235t', 'Pb_R65m', 'Pb_R76m', 'Pb_R46m', 'Pb_R85m', 'Pb_R65t', 'Pb_R45t', 'Pb_R75t', 'Pb_R85t', 'U_R35m', 'U_R85m', 'U_R35t', 'U_R85t', 'Pb206s', 'Pb207s', 'Pb204c', 'Pb206r', 'Pb207r', 'Pb208r', 'Pb206b', 'Pb207b', 'Pb208b', 'Pb204b', 'Pb206c', 'Pb207c', 'Pb208c', 'U238b', 'U238s', 'U235s', 'R68r', 'R75r', 'R76r', 't68', 't75', 't76', 'D_Th_U', 'R64b', 'R74b', 'R84b', 'R64c', 'R74c', 'R84c']
        injection = '\n    answer.setdefault("worked", {})[Path(path).stem] = {k: float(getattr(g,k)) for k in ' + repr(fields) + ' if getattr(g,k,None) is not None}\n'
        worker = AGE_WORKER.replace('g = result.grain\n', 'g = result.grain\n' + injection)
        env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        env['QT_QPA_PLATFORM'] = 'offscreen'
        completed = subprocess.run([str(Path(age_repo)/'.venv/bin/python'), '-c', worker,
                                    str(tmp/'settings.json'), *map(str, paths)], cwd=age_repo,
                                   env=env, capture_output=True, text=True, check=True, timeout=300)
        ages = json.loads(completed.stdout)
    for entry in payload['grid']:
        entry['dates'] = ages['runs'][f't{round(entry["tau"]*10)}']['dates']
    for name in payload['raw']:
        payload['raw'][name]['dates'] = ages['runs'][name]['dates']
    payload['constants'] = ages['constants']
    grid0, grid40 = payload['grid'][113], payload['grid'][150]
    assert grid0['tau'] == tau0
    grain = ages['worked']['t363']
    raw_grain = ages['worked']['raw36']
    rates = {str(m): float(pb.column(f'{m} D').mean()) for m in (204, 205, 206, 207)}
    delta = (40-tau0)*1e-9
    comparisons = []
    for (a, b), label in zip(PAIRS, LABELS):
        key = f'{label} D'; x = pb.column(key); mask = acquired.included_for(key)
        # Exact derivative of the gross-transform/net-subtract cycle ratio.
        # 208/205 carries D206 through inverse gain; Faradays cancel.
        da = 206 if a == 208 else a
        na, nb = pb.column(f'{da} D'), pb.column(f'{b} D')
        B = decoded.baselines[:, dcol]
        derivative = (na+B)**2/na - (nb+B)**2/nb
        first = float(np.mean((x*derivative)[mask]) / np.mean(x[mask]) * delta * 100)
        exact = (grid40['ratios'][label]['mean']/baseline_summary[label]['mean']-1)*100
        raw_exact = (payload['raw']['raw40']['ratios'][label]['mean']/payload['raw']['raw36']['ratios'][label]['mean']-1)*100
        simple = (rates[str(da)]-rates[str(b)])*delta*100
        comparisons.append({'ratio': label, 'exact_pct': exact, 'first_pct': first,
                            'simple_pct': simple, 'scan_pct': raw_exact, 'residual_ppm': (exact-first)*1e4})
    date_comparisons = []
    l8, l5 = ages['constants']['lambda_238'], ages['constants']['lambda_235']
    sensitivities = {'206/238': raw_grain['R68r']/(l8*(1+raw_grain['R68r']))/1e6,
                     '207/235': raw_grain['R75r']/(l5*(1+raw_grain['R75r']))/1e6}
    t = raw_grain['t76']*1e6
    sensitivities['207/206'] = 1/(l5/(-math.expm1(-l5*t))-l8/(-math.expm1(-l8*t)))/1e6
    # First-order measured-ratio perturbation: 68 follows 65; 75 follows
    # product 65*(1/67), as does the age engine, not an independent mean 75.
    bias = {'206/238': comparisons[2]['first_pct']/100,
            '207/235': (comparisons[2]['first_pct']-comparisons[1]['first_pct'])/100,
            '207/206': -comparisons[1]['first_pct']/100}
    for label in ('206/238', '207/235', '207/206'):
        shift = payload['raw']['raw40']['dates'][label][0]-payload['raw']['raw36']['dates'][label][0]
        predicted = sensitivities[label]*bias[label]
        date_comparisons.append({'ratio': label, 'base': payload['raw']['raw36']['dates'][label][0],
                                 'changed': payload['raw']['raw40']['dates'][label][0],
                                 'two_sigma': payload['raw']['raw40']['dates'][label][1],
                                 'shift': shift, 'first': predicted, 'residual': shift-predicted,
                                 'sensitivity': sensitivities[label], 'bias_pct': bias[label]*100})
    cycles = []
    for label in LABELS + ['206/208 F H1', '206/208 F H2', '206/208 F average', 'Faraday-Daly Gain']:
        key = f'{label} D' if label in LABELS else label
        cycles.append({'ratio': label, 'workbook': float(pb.column(key)[0]), 'reconstructed': float(raw_runs['raw36'].column(key)[0]),
                       'relative_error': float(raw_runs['raw36'].column(key)[0]/pb.column(key)[0]-1)})
    key = '206/207 D'
    st = acquired.stats(key)
    reject = legacy_two_sigma_rejections(pb.column(key))
    mask_reject = np.flatnonzero(~acquired.included_for(key))
    refs = read_sheet_references(sheet.parent)
    stats_rows = []
    for e, a in (('Pb', acquired), ('U', ua)):
        for r, entry in a.mapping.ratios.items():
            s = a.stats(entry.key)
            ref = refs['KD33', 'z1', entry.key]
            stats_rows.append({'ratio': r, 'mean': s.mean, 'se_pct': s.se_pct, 'n': s.n_used,
                               'sheet_mean': ref[1], 'sheet_se_pct': ref[2]})
    x, y, z = (float(u.column(str(m))[0]) for m in (265, 267, 270))
    oc = correct(x/y, z/y, as_acquired(u).oxide_r18)
    contract = row(acquired).values
    # Explicit allowlist; never serialize row provenance wholesale.
    contract_view = {k: contract[k] for k in ('Contract', 'Pb Mean Statistic', 'U Mean Statistic',
                      'Pb Cycle Selection', 'U Cycle Selection', 'U Oxide Formula', 'U Oxide 18O/16O',
                      'Pb Reduction Route', 'U Reduction Route', 'Pb Reduction Parameters SHA256', 'U Reduction Parameters SHA256')}
    correlations = [{'column': k, 'value': val} for k, val in contract.items() if k.startswith('rho ') and val is not None]
    err = float(np.max(abs(raw_runs['raw36'].values/pb.values-1)))
    assert err <= PB_WORKBOOK_RTOL
    values = {'overview': {'cycles': pb.n_cycles, 'blocks': len(np.unique(pb.block)), 'per_block': pb.metadata.cycles_per_block},
              'acquisition': {'sequences': sequences,
                      'scans': [total//step for total, step in integrations[2:2+sequences]],
                      'seconds_per_scan': integrations[0][1]//1000,
                      'baseline_scans': integrations[0][0]//integrations[0][1],
                      'precycles': histories-1, 'histories': histories,
                      'acquired_cycles_per_block': pb.metadata.cycles_per_block+histories-1, 'faraday': chain['faraday']},
              'scan': {'tau': tau0, 'rows': chain['scans'], 'mean': chain['scan_mean'],
                       'sigma': params.integration_rejection.sigma, 'max_percent': params.integration_rejection.max_percent,
                       'sd': chain['scan_sd'], 'arithmetic': chain['scan_arithmetic'], 'multiplier_gain': params.multiplier_gain},
              'cycle': chain, 'baseline': {'low_mass': masses[0], 'high_mass': masses[1]},
              'gain': {'d206': float(pb.column('206 D')[0]), 'f206': float(pb.column('Pb206+At206 S2 int')[0]),
                       'f208': float(pb.column('Pb208 S4 int')[0]), 'gain': float(pb.column('Faraday-Daly Gain')[0])},
              'ratios': {'cycles': cycles},
              'rejection': {'saved': len(mask_reject), 'single_pass': len(reject), 'same': bool(np.array_equal(mask_reject, reject)),
                            'different': len(set(mask_reject)^set(reject)), 'used': st.n_used},
              'stats': {'rows': stats_rows, 'worked': st.to_dict(),
                        'blocks': {c: acquired.block_weighted_mean(key, c).to_dict() for c in ('standard', 'tripoli')},
                        'rho': acquired.correlation('206/205 D', '206/207 D').to_dict()},
              'oxide': {'x': x, 'y': y, 'z': z, 'r18': as_acquired(u).oxide_r18,
                        'r265': x/y, 'r270': z/y, 'factor': 1-2*as_acquired(u).oxide_r18*x/y,
                        'r233_235': float(oc[0]), 'r238_235': float(oc[1]), 'r238_233': float(oc[2]),
                        'cached': float(u.column('238/235 oxide R18 0.00206')[0])},
              'fractionation': grain, 'spike': {'weight': setup['spike_weight_g'], 'pb_blank_pg': settings['lab_blanks']['Pb_blank_total'],
                                                'u_blank_pg': settings['lab_blanks']['U_blank_total']},
              'handoff': {'columns': contract_view, 'correlations': correlations},
              'depth': {'tau0': tau0, 'tau1': 40.0, 'delta_ns': 40-tau0, 'minimum': 25.0, 'maximum': 50.0,
                        'step': .1, 'grid_count': len(payload['grid']), 'rates': rates, 'ratios': comparisons,
                        'dates': date_comparisons, 'constants': ages['constants'], 'pb_bound': PB_WORKBOOK_RTOL,
                        'max_relative_error': err, 'age_shift_factor': abs(date_comparisons[2]['shift']/date_comparisons[0]['shift']),
                        'bias_factor': abs(bias['207/206']/bias['206/238']),
                        'sensitivity_factor': sensitivities['207/206']/sensitivities['206/238'],
                        'plot_taus': [20, tau0, 40, 60], 'plot_deltas': [1, 2, 40-tau0, 5]}}
    return clean(values), clean(payload)


def write_data(values, payload, output):
    output = Path(output)
    (output/'data').mkdir(parents=True, exist_ok=True)
    (output/'javascripts').mkdir(parents=True, exist_ok=True)
    (output/'data/values.json').write_text(json.dumps(values, indent=2, sort_keys=True, allow_nan=False)+'\n')
    # Fixed global name: deadtime.js and the docs test read window.FILAMENT_Z1,
    # so it must not follow a future app rename.
    (output/'javascripts/z1-data.js').write_text('window.FILAMENT_Z1 = '+json.dumps(payload, sort_keys=True, allow_nan=False, separators=(',', ':'))+';\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/site')
    args = parser.parse_args()
    values, payload = build_data()
    write_data(values, payload, args.output)
    print(f"Wrote {len(payload['block'])} Pb cycles, {len(payload['grid'])} dead-time steps and three dates per step; numerical allowlist only.")
    print(f"Maximum raw/workbook relative discrepancy: {values['depth']['max_relative_error']:.9g}")


if __name__ == '__main__':
    main()
