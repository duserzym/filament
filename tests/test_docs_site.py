"""Public walkthrough: offline privacy/math checks and read-only engine parity."""
from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT/'docs/site'


def read_payload(path=SITE/'javascripts/z1-data.js'):
    text = path.read_text()
    prefix = 'window.WALKTHROUGH_Z1 = '
    assert text.startswith(prefix) and text.endswith(';\n')
    return json.loads(text[len(prefix):-2])


def load_generator():
    spec = importlib.util.spec_from_file_location('docs_site_data', ROOT/'scripts/docs_site_data.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_numerical_references_resolve():
    values = json.loads((SITE/'data/values.json').read_text())
    # Validate every root-v access, including for-loop collections and bracket
    # keys. Also catches undefined references inside HTML attributes.
    pattern = re.compile(r'\bv((?:\.[A-Za-z_]\w*|\[\d+\]|\[\'[^\']+\'\]|\["[^"]+"\])+)')
    count = 0
    for page in SITE.glob('*.md'):
        for match in pattern.finditer(page.read_text()):
            value = values
            pieces = re.findall(r'\.([A-Za-z_]\w*)|\[(\d+)\]|\[\'([^\']+)\'\]|\["([^"]+)"\]', match.group(1))
            for name, index, single, double in pieces:
                if name in ('items', 'keys', 'values') and isinstance(value, dict):
                    continue
                key = int(index) if index else name or single or double
                try:
                    value = value[key]
                except (KeyError, IndexError, TypeError) as exc:
                    pytest.fail(f'{page.name}: unresolved {match.group(0)}: {exc}')
            count += 1
    assert count > 100


def test_public_payload_has_no_source_metadata():
    # Treat forbidden identifiers case-insensitively, and reject calendar times.
    forbidden = re.compile(r'KD33|\.xls|\.raw|Drive|/Users/|B160|'
                           r'\b(?:19|20)\d{2}-\d{2}-\d{2}|'
                           r'\b\d{4}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b|'
                           r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b', re.IGNORECASE)
    paths = [SITE/'data/values.json', SITE/'javascripts/z1-data.js', *SITE.glob('*.md')]
    for path in paths:
        match = forbidden.search(path.read_text())
        assert match is None, f'{path.name}: forbidden metadata {match.group()!r}'
    # Public payloads are explicit numerical allowlists, never generic metadata
    # dictionaries or whole fraction rows. Forbid identity-bearing key names too.
    for obj in (json.loads(paths[0].read_text()), read_payload()):
        def walk(x):
            if isinstance(x, dict):
                for k, val in x.items():
                    assert not re.search(r'operator|analyst|serial|filename|file_path|timestamp|sample_id', k, re.IGNORECASE)
                    walk(val)
            elif isinstance(x, list):
                for val in x:
                    walk(val)
            elif isinstance(x, float):
                assert math.isfinite(x)
            elif isinstance(x, str):
                # Unknown text (including an operator name) cannot slip through
                # just because it was not known when this test was written.
                enums = {'Faraday-Daly Gain', 'arithmetic', 'idtims-fractions/1',
                         'instrument', 'per_ratio', 'standard', 'tripoli', 'workbook'}
                isotope = r'\d{3}(?:Pb|U)?/\d{3}(?:Pb|U)?'
                assert (x in enums or re.fullmatch(r'[0-9a-f]{64}', x)
                        or re.fullmatch(isotope + r'(?: F (?:H1|H2|average))?', x)
                        or re.fullmatch('rho ' + isotope + r'\|' + isotope, x)), x
        walk(obj)


def test_payload_shapes_and_grid():
    d = read_payload()
    assert len(d['block']) == 228
    assert len(d['grid']) == 251
    assert [e['tau'] for e in d['grid']] == [n/10 for n in range(250,501)]
    assert len(d['seconds']) == len(d['baseline']) == len(d['faraday206']) == len(d['faraday208']) == 228
    assert all(a < b for a,b in zip(d['seconds'],d['seconds'][1:]))
    for group in ('daly','masks','acquired_ratios'):
        assert all(len(a)==228 for a in d[group].values())
    assert set(d['daly']) == {'204','205','206','207'}
    assert all(isinstance(x,bool) for a in d['masks'].values() for x in a)
    assert all(set(e['dates'])=={'206/238','207/235','207/206'} for e in d['grid'])


def test_browser_functions_against_engine_grid():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is unavailable')
    # VM interprets the actual distributed static JS, including its window
    # assignment. Tests do not translate the browser maths back into Python.
    code = r'''
const assert=require('assert'),fs=require('fs'),vm=require('vm');
const math=require(process.argv[1]);
const context={window:{}};vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
const data=context.window.WALKTHROUGH_Z1;
for(const tau of [30,36.3,40,45]) {
  const actual=math.evaluate(data,tau), expected=math.gridEntry(data,tau);
  for(const name of math.labels) for(const field of ['mean','se_pct']) {
    const a=actual.ratios[name][field],b=expected.ratios[name][field];
    assert(Math.abs(a-b)<=Math.abs(b)*1e-12,`${tau} ${name} ${field}: ${a} != ${b}`);
  }
  for(const name of ['206/207','206/205']) {
    const changes=math.cycleChanges(data,tau,name),[a,b]=name.split('/');
    assert.strictEqual(changes.percent.length,data.block.length);
    changes.difference.forEach((x,i)=>{
      assert.strictEqual(x,(data.daly[a][i]+data.baseline[i])-(data.daly[b][i]+data.baseline[i]));
      assert.strictEqual(changes.first[i],100*x*(tau-data.tau0)*1e-9);
      const expected=(actual.cycles.ratios[name][i]/data.acquired_ratios[name][i]-1)*100;
      assert.strictEqual(changes.percent[i],expected);
      if(tau===data.tau0) assert.strictEqual(changes.percent[i],0);
    });
  }
}
assert.deepStrictEqual(math.breakBlocks([1,2,10,11],[4,5,6,7],[1,1,2,2]),
  {x:[1,2,null,10,11],y:[4,5,null,6,7]});
assert.deepStrictEqual(math.breakBlocks([],[],[]),{x:[],y:[]});
const trace=math.breakBlocks(data.seconds,data.acquired_ratios['206/207'],data.block);
assert.strictEqual(trace.x.filter(x=>x===null).length,11);
assert.strictEqual(trace.y.filter(x=>x===null).length,11);
assert.deepStrictEqual(trace.x.filter(x=>x!==null),Array.from(data.seconds));
assert.deepStrictEqual(trace.y.filter(x=>x!==null),Array.from(data.acquired_ratios['206/207']));
assert.throws(()=>math.cycleChanges(data,40,'208/205'),RangeError);
assert.throws(()=>math.correctObserved(1e9,40),RangeError);
assert.throws(()=>math.gridEntry(data,36.35),RangeError);
assert.strictEqual(math.ratioBias(200000,200000,3.7).exact,0);
assert.strictEqual(math.ratioBias(200000,200000,3.7).first,0);
assert.strictEqual(math.changeNet(200000,2,0),200000);
'''
    subprocess.run([node,'-e',code,str(SITE/'javascripts/deadtime.js'),str(SITE/'javascripts/z1-data.js')],
                   text=True, capture_output=True, check=True)


def test_reader_summaries_and_scientific_notation():
    spec=importlib.util.spec_from_file_location('docs_macros',ROOT/'docs/macros.py')
    macros=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(macros)
    assert macros.sci(2.924431286e-6)=='2.9×10⁻⁶'
    assert macros.sci(-4.20224866e-9)=='-4.2×10⁻⁹'
    assert macros.sci(461899.3)=='4.6×10⁵'
    assert macros.sci(0)=='0'
    for page in SITE.glob('*.md'):
        text=page.read_text()
        assert '!!! abstract "In short"' in text, page.name
        assert 'Yiming,' not in text
    depth=(SITE/'dead-time.md').read_text()
    assert depth.index('!!! abstract "The short answer"')<depth.index('!!! abstract "In short"')
    assert '<svg class="pulse-timeline"' in depth
    assert 'https://' not in depth
    assert depth.index('id="ratio-results"')<depth.index('id="change-plot"')<depth.index('id="cycle-plot"')


def compare_tree(actual, expected, path='', *, exact=False):
    assert type(actual) is type(expected), path
    if isinstance(actual, dict):
        assert actual.keys()==expected.keys(), path
        for key in actual:
            compare_tree(actual[key],expected[key],f'{path}.{key}',exact=exact)
    elif isinstance(actual, list):
        assert len(actual)==len(expected), path
        for i,(a,b) in enumerate(zip(actual,expected)):
            compare_tree(a,b,f'{path}[{i}]',exact=exact)
    elif isinstance(actual,float) and not exact:
        assert actual==pytest.approx(expected,rel=1e-12,abs=0), path
    else:
        assert actual==expected, path


@pytest.mark.slow
def test_read_only_engine_regeneration_and_worked_chains(tmp_path):
    from dataclasses import replace

    import numpy as np

    from rawtims.parity import _view, drive_path, replay_project
    from rawtims.readers import open_run
    from rawtims.readers.ionvantage_raw import dead_time, decode_raw, raw_folder
    from rawtims.readers.trip import read_trip
    from rawtims.reduction_params import as_acquired
    from rawtims.reprocess import reprocess
    folder = drive_path()
    gen = load_generator()
    if not folder.exists() or not (gen.AGE_REPO/'.venv/bin/python').exists():
        pytest.skip('Read-only acquisitions or age-engine interpreter are unavailable')
    expected_v=json.loads((SITE/'data/values.json').read_text())
    expected_d=read_payload()
    fresh_v,fresh_d=gen.build_data()
    compare_tree(fresh_v,expected_v)
    compare_tree(fresh_d,expected_d)
    gen.write_data(fresh_v,fresh_d,tmp_path)
    # Whole output equality is stronger than the derived-maths tolerance above.
    assert (tmp_path/'data/values.json').read_bytes()==(SITE/'data/values.json').read_bytes()
    assert (tmp_path/'javascripts/z1-data.js').read_bytes()==(SITE/'javascripts/z1-data.js').read_bytes()
    r=open_run(folder/'B1606_F15_KD33 z1 Pb-56136.xls')
    p=as_acquired(r)
    decoded=decode_raw(raw_folder(Path(r.raw.path)),replace(p,route='raw'))
    d=decoded.collectors.index('Multiplier')
    c=fresh_v['cycle']
    assert c['net']==c['decoded']==decoded.intensities[0,2,d]
    assert c['gross']-c['baseline']==c['decoded']
    assert np.array_equal(np.asarray(fresh_d['baseline']),decoded.baselines[:,d])
    assert np.array_equal(np.asarray(fresh_d['seconds']),r.time)
    for mass in (204,205,206,207):
        assert np.array_equal(fresh_d['daly'][str(mass)],r.column(f'{mass} D'))
    assert np.array_equal(fresh_d['faraday206'],r.column('Pb206+At206 S2 int'))
    assert np.array_equal(fresh_d['faraday208'],r.column('Pb208 S4 int'))
    for scan in fresh_v['scan']['rows']:
        assert scan['corrected']==dead_time(scan['observed'],p.daly_dead_time_ns).item()*p.multiplier_gain
    f=fresh_v['acquisition']['faraday']
    assert (f['code']-f['zero'])*f['v_per_code']*f['gain']==f['volts']
    assert f['volts']/(f['resistor']*f['charge'])==f['cps']
    raw=reprocess(r,replace(p,route='raw'))
    assert float(np.max(np.abs(raw.values/r.values-1)))<=fresh_v['depth']['pb_bound']
    project=read_trip(folder/'KD33_z1_Pb.trip')
    a=replay_project(_view(r,project),project)
    for label in gen.LABELS:
        stat=a.stats(f'{label} D')
        expected=fresh_d['grid'][113]['ratios'][label]
        assert stat.mean==expected['mean']
        assert stat.se_pct==expected['se_pct']
        assert np.array_equal(a.included_for(f'{label} D'),fresh_d['masks'][label])
    from rawtims.parity import numeric_tolerance
    u=open_run(folder/'B1606_F15_KD33 z1 U-56137.xls')
    up=read_trip(folder/'KD33_z1_U_partial.trip')
    ua=replay_project(_view(u,up),up)
    for row in fresh_v['stats']['rows']:
        selected=a if row['ratio'].endswith('Pb') else ua
        label=selected.mapping.ratios[row['ratio']].key
        active=selected.column(label)[selected.column(label)>0]
        stat=selected.stats(label)
        assert stat.mean==row['mean']
        assert stat.se_pct==row['se_pct']
        assert abs(row['mean']-row['sheet_mean'])<=numeric_tolerance(row['sheet_mean'],'mean',active,clipboard=True)
        assert abs(row['se_pct']-row['sheet_se_pct'])<=numeric_tolerance(row['sheet_se_pct'],'se_pct',active,clipboard=True)
    # Compare numerical outputs only. No output contains identifying metadata,
    # including any analyst/operator values present in the original header.
    public=(tmp_path/'data/values.json').read_text()+(tmp_path/'javascripts/z1-data.js').read_text()
    for key,value in r.metadata.extra.items():
        if re.search('analyst|operator',key,re.IGNORECASE) and isinstance(value,str) and value.strip():
            assert value.casefold() not in public.casefold()
