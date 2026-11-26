"""P3 deterministic diagnostics. Tripoli citations refer to Java 00dc941.

Array oracle is copied byte-for-byte and checksummed in MANIFEST.toml. Scalar
operator/block/matrix expectations below independently transcribe source formulas;
no Java runtime-generated answer is claimed. All other inputs are synthetic or
already committed Tripoli fixtures; no lab data are discovered at runtime.
"""
import copy
import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from reader_fixtures import SYNTHETIC_U, TIMSDP_FILES, TRIPOLI, read
from test_p2_exchange import synthetic

from rawtims.analysis import Analysis
from rawtims.block_diagnostics import (
    java_snapshot_block_diagnostic,
    member_block_indices,
    standard_block_diagnostic,
)
from rawtims.composition import (
    Composition,
    CompositionBook,
    Member,
    compose,
    concatenate,
)
from rawtims.contract import csv_text
from rawtims.covariance import (
    covariance_to_measured_correlation,
    measured_correlation_to_covariance,
    validate_covariance,
)
from rawtims.exports import clipboard_text, cycles_csv_text
from rawtims.expressions import (
    ExpressionError,
    ExpressionSpec,
    evaluate,
    parse,
    ratio_spec,
)
from rawtims.fractions import Fraction, fraction_row
from rawtims.session import (
    SessionError,
    SessionState,
    load_session,
    save_session,
    session_fingerprint,
)


def spec(text, key='derived:x', kind='other'):
    return ExpressionSpec(key, 'Synthetic expression', text, kind)


def test_java_stored_expression_array():
    """Tripoli/TripoliCore/src/test/java/org/cirdles/tripoli/expressions/ExpressionTreeTest.java:78-98,125-137.

    The Java test's intensity/ratio expression is evaluated against all 200
    committed expected cycles, including its negative 205Pb intensity.
    """
    r = read(TIMSDP_FILES['NBS981 210325b-392'])
    expression = '[204Pb] + [205Pb] * [206Pb] - [207Pb] * ([208Pb] + [204/206])'
    result = evaluate([spec(expression)], {k: r.column(k) for k in r.keys})[0]
    expected = np.array([float(v) for line in (TRIPOLI/'oracle/expressions/NBS981_210325b-392_ExpressionEval.txt').read_text().splitlines() for v in line.split(',') if v])
    np.testing.assert_array_equal(result.values, expected)
    assert not result.invalid.any()


@pytest.mark.parametrize('expression,expected', [('1+2*3-4/2',5), ('(1+2)*(3-4)/2',-1.5),
    ('2^3^2',512), ('-2^2',-4), ('2^-2',.25), ('log(100)',2), ('sqrt(9)',3), ('exp(1)',math.e),
    ('ln(exp(2))',2), ('+3',3), ('1e-3 + .5',.501)])
def test_java_operator_scalars(expression, expected):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/expressions/operations/{Add,Subtract,Multiply,Divide,Power,Log,Exp,Sqrt}.java:38-49;
    expressions/parsing/ShuntingYard.java:42-100 (right-associative power).
    ln is the explicitly requested inverse-exp extension, scalar checked here.
    """
    assert evaluate([spec(expression)], {'x': np.ones(3)})[0].values == pytest.approx([expected]*3)


@pytest.mark.parametrize('text', ['__import__("os")', 'x.y', 'x[0]', '[x][x]', '[x]//2', '[x]**2',
                                 'sin(1)', 'log 1', '1,2', '1;2', '(1', '1)', '', '1e999', '2(3)', '1 +',
                                 '(' * 60 + '1' + ')' * 60, '+'.join(['1']*300)])
def test_parser_rejects_unsafe_unsupported_or_unbounded_syntax(text):
    with pytest.raises(ExpressionError):
        parse(text)


def test_dependency_order_masks_missing_and_cycle_rejection():
    specs = [spec('[derived:b]+1','derived:a'), spec('[x #2]/[x]','derived:b')]
    columns = {'x': np.array([1.,0.,np.nan,4.]), 'x #2': np.array([2.,3.,4.,8.])}
    result = evaluate(specs,columns,masks={'x':np.array([True,True,True,False])})
    assert [d.spec.key for d in result] == ['derived:b','derived:a']
    np.testing.assert_equal(result[0].values, [2.,np.nan,np.nan,2.])
    np.testing.assert_equal(result[0].included,[True,False,False,False])
    assert result[0].issues
    again = evaluate(list(reversed(specs)),columns)
    np.testing.assert_equal(result[1].values,again[1].values)
    for bad in ([spec('[missing]')], [spec('[derived:x]')], [spec('[derived:y]'),spec('[derived:x]','derived:y')], [spec('1'),spec('2')]):
        with pytest.raises(ExpressionError):
            evaluate(bad,columns)
    with pytest.raises(ExpressionError):
        evaluate([spec('1')], {'derived:x':np.ones(2)})


@pytest.mark.parametrize('expression', ['log([x])','ln([x])','sqrt([x])','exp([x])','[x]^0','[x]/0'])
def test_domain_and_missing_operands_stay_invalid(expression):
    values = np.array([-1.,0.,1.,1000.,np.nan])
    result = evaluate([spec(expression)], {'x': values})[0]
    assert result.invalid[-1] and np.isnan(result.values[-1])
    assert not result.included[-1]
    if expression in ('log([x])','ln([x])'):
        assert result.invalid[:2].all()
    if expression == 'sqrt([x])':
        assert result.invalid[0]
    if expression == 'exp([x])':
        assert result.invalid[3]
    if expression == '[x]/0':
        assert result.invalid.all()


def test_ratio_builder_positive_domain_and_exact_source_keys():
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1204 (explicit species pair).
    Only existing columns are composed; raw species inference is outside P3.
    """
    s = ratio_spec('derived:ratio','Synthetic ratio','A #2','B')
    d = evaluate([s], {'A #2':np.array([4.,-1.,2.]),'B':np.array([2.,2.,0.])})[0]
    np.testing.assert_equal(d.values,[2.,np.nan,np.nan])
    np.testing.assert_equal(d.invalid,[False,True,True])


@pytest.mark.parametrize('stem',['GHR1 230921 F08b-216','WH205 z4 Pb-654'])
def test_committed_block_split_and_reassembly(stem):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:177-228,238-243.

    Generated metamorphic block split of the committed A/B fixture (no standalone
    concat oracle exists). Reassembly must preserve every cycle, block, elapsed
    time, invalid flag, shared/per-column rejection and member provenance.
    """
    a = Analysis(copy.deepcopy(read(TIMSDP_FILES[stem])))
    a.set_setting('synced',False)
    a.toggle_cycles([1,3], [a.keys[-1]],False)
    a.toggle_block(int(a.blocks[-1]),False)
    split = max(1,len(a.blocks)//2)
    members = (Member(a.run.run_id,tuple(int(b) for b in a.blocks[split:])), Member(a.run.run_id,tuple(int(b) for b in a.blocks[:split])))
    t = concatenate(members,{a.run.run_id:a})
    for attr, expected in [('values',a.values),('invalid',a.invalid),('included',a.effective),('cycle',a.run.cycle),('block',a.run.block),('time',a.run.time)]:
        np.testing.assert_array_equal(getattr(t,attr),expected)
    assert set(t.source_hashes) == {a.run.raw.sha256}
    assert set(t.run_ids) == {a.run.run_id}
    assert len(t.boundaries) == 1


def two_members():
    a = synthetic(values=((1.,),(3.,),(5.,),(7.,)))
    b = synthetic(values=((2.,),(4.,),(6.,),(8.,)))
    a.run.run_id, b.run.run_id = 'synthetic-a','synthetic-b'
    a.run.metadata.analysis_start = datetime(2026,11,25,10,tzinfo=UTC)
    b.run.metadata.analysis_start = a.run.metadata.analysis_start + timedelta(seconds=20)
    b.run.raw = replace(b.run.raw,sha256='1'*64)
    return a,b,{a.run.run_id:a,b.run.run_id:b}


def test_concat_time_order_member_identity_and_masks():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:198-199 retains members/borders;
    OGTripoli/source/forms/fmrMainTripoli.cs:2053 uses acquisition timestamps.
    """
    a,b,sources = two_members()
    b.toggle_cycles([1],b.keys,False)
    before = [cycles_csv_text(a),cycles_csv_text(b)]
    t = concatenate((Member(b.run.run_id),Member(a.run.run_id)),sources)
    assert t.run_ids == (a.run.run_id,)*4+(b.run.run_id,)*4
    np.testing.assert_equal(t.cycle,[1,2,3,4,1,2,3,4])
    assert t.block_keys[0] != t.block_keys[4]
    assert t.source_hashes == ('0'*64,)*4+('1'*64,)*4
    assert t.acquisition_times[4] == '2026-11-25T10:00:20+00:00'
    assert not t.included[5,0]
    assert [cycles_csv_text(a),cycles_csv_text(b)] == before
    assert member_block_indices(t.run_ids,t.block).tolist() == [1,1,2,2,3,3,4,4]


@pytest.mark.parametrize('change', ['method','unit','function','setting','missing-time','nonfinite-time','decreasing-time','overlap','zone','empty-method'])
def test_concat_refuses_ambiguous_or_mismatched_members(change):
    a,b,sources = two_members()
    if change == 'method': b.run.metadata.method = 'different'
    elif change == 'unit': b.functions = (replace(b.functions[0],unit='V'),)
    elif change == 'function': b.functions = (replace(b.functions[0],key='different'),)
    elif change == 'setting': b.set_setting('r18',.003)
    elif change == 'missing-time': b.run.metadata.analysis_start = None
    elif change == 'nonfinite-time': b.run.time[1] = np.nan
    elif change == 'decreasing-time': b.run.time[1] = -1
    elif change == 'overlap': b.run.metadata.analysis_start = a.run.metadata.analysis_start
    elif change == 'zone': b.run.metadata.analysis_start = b.run.metadata.analysis_start.replace(tzinfo=None)
    elif change == 'empty-method': a.run.metadata.method = b.run.metadata.method = None
    with pytest.raises(ValueError):
        concatenate((Member(a.run.run_id),Member(b.run.run_id)),sources)


def test_concat_duplicate_unknown_empty_selections_and_undated_shards():
    a = synthetic(values=((1.,),(2.,),(3.,),(4.,)))
    sources = {a.run.run_id:a}
    for members in [(),(Member('missing'),),(Member(a.run.run_id),Member(a.run.run_id)),(Member(a.run.run_id,(9,)),)]:
        with pytest.raises(ValueError): concatenate(members,sources)
    t = concatenate((Member(a.run.run_id,(2,)),Member(a.run.run_id,(1,))),sources)
    np.testing.assert_equal(t.cycle,a.run.cycle)


def test_book_validates_before_mutation_and_replays_undo_redo():
    a = synthetic()
    sources = {a.run.run_id:a}
    recipe = Composition('synthetic-view','Synthetic view',(Member(a.run.run_id),),(spec('[206/204 D]*2'),))
    book = CompositionBook()
    book.put(recipe,sources)
    previous = book.to_dict()
    with pytest.raises(ExpressionError):
        book.put(replace(recipe,expressions=(spec('[missing]'),)),sources)
    assert book.to_dict() == previous
    assert book.undo() and not book.objects
    loaded = CompositionBook.from_dict(json.loads(json.dumps(book.to_dict())))
    assert loaded.redo() and loaded.objects == (recipe,)
    np.testing.assert_equal(compose(loaded.objects[0],sources).derived[0].values,[2.,6.,10.])
    a.toggle_cycles([0],a.keys,False)
    assert not compose(loaded.objects[0],sources).derived[0].included[0]
    loaded.remove(recipe.key)
    assert not loaded.objects
    assert loaded.undo() and loaded.objects == (recipe,)
    loaded.put(replace(recipe,name='Synthetic renamed'),sources)
    assert not loaded.can_redo
    corrupt = loaded.to_dict()
    corrupt['events'][0]['before'] = recipe.to_dict()
    with pytest.raises(ValueError,match='replay'): CompositionBook.from_dict(corrupt)


def test_session_recipe_replay_redo_missing_source_and_export_invariance(tmp_path):
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1911 (expression undo);
    filament uses a separate strictly replayed history with original source hashes.
    """
    from rawtims.readers import open_run
    a = Analysis(open_run(SYNTHETIC_U))
    fraction = Fraction('Synthetic P3',u=a)
    state = SessionState(fractions=[fraction])
    stamp = datetime(2026,11,25,tzinfo=UTC)
    def outputs():
        return (csv_text([fraction_row(fraction,stamp)]), clipboard_text(fraction), cycles_csv_text(a))
    before = outputs()
    book = CompositionBook()
    recipe = Composition('synthetic-u','Synthetic U expression',(Member(a.run.run_id),),(spec(f'[{a.keys[0]}]/2'),))
    book.put(recipe,{a.run.run_id:a})
    book.put(replace(recipe,name='Synthetic renamed'),{a.run.run_id:a})
    book.undo()
    state.composition = book.to_dict()
    path = save_session(state,tmp_path/'synthetic.rawtims')
    restored, problems = load_session(path)
    assert not problems
    replayed = CompositionBook.from_dict(restored.composition)
    assert replayed.objects == (recipe,) and replayed.can_redo
    table = compose(replayed.objects[0],{a.run.run_id:a})
    assert table.derived[0].spec.key not in a.keys
    assert table.derived[0].spec.key not in str(fraction.mapping('U').function_keys)
    assert outputs() == before
    clean = session_fingerprint(state,path)
    replayed.redo()
    state.composition = replayed.to_dict()
    assert session_fingerprint(state,path) != clean
    replayed.undo()
    state.composition = replayed.to_dict()
    assert session_fingerprint(state,path) == clean
    doc = json.loads(path.read_text())
    doc['runs'][0]['raw']['sha256'] = 'f'*64
    path.write_text(json.dumps(doc))
    missing, problems = load_session(path)
    assert {p.kind for p in problems} == {'changed','composition'}
    assert missing.composition == restored.composition
    assert json.loads(save_session(missing,tmp_path/'synthetic-missing.rawtims').read_text())['composition'] == doc['composition']


def test_block_conventions_independent_scalar_and_omissions():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/AnalysisStatsRecord.java:89-117.
    Blocks: means 2,6; SD² 2,4; SE² 1,4/3. Standard: 26/7 ± sqrt(4/7), MSWD=48/7.
    Java: 10/3 ± sqrt(4/3), chi-square/(B−1)=20/3.
    """
    values, blocks = np.array([1.,3.,4.,6.,8.]), np.array([1,1,2,2,2])
    include = np.ones(5,dtype=bool)
    standard = standard_block_diagnostic(values,include,blocks)
    java = java_snapshot_block_diagnostic(values,include,blocks)
    assert (standard.result.mean,standard.result.sigma,standard.result.mswd) == pytest.approx((26/7,math.sqrt(4/7),48/7))
    assert (java.result.mean,java.result.sigma,java.result.mswd) == pytest.approx((10/3,math.sqrt(4/3),20/3))
    assert 'SE²' in standard.label and 'SD²' in java.label and 'chi-square' in java.dispersion_label
    for fn in (standard_block_diagnostic,java_snapshot_block_diagnostic):
        result = fn([1.,1.,2.],[True]*3,[1,1,2])
        assert result.omitted_blocks == (1,2) and result.result.n_blocks == 0
        assert math.isnan(result.result.mean) and 'fewer than two' in result.notice
        result = fn([1.,3.,9.],[True,True,False],[1,1,2])
        assert result.result.mean == 2 and math.isnan(result.result.mswd)
        geo = fn(np.exp(values/10),include,blocks,is_ratio=True,ratio_mode='geometric')
        assert geo.result.mean == pytest.approx(math.exp((26/7 if fn is standard_block_diagnostic else 10/3)/10))
        assert 'ln(ratio)' in geo.notice


@pytest.mark.parametrize('matrix,valid', [([[4.,1.],[1.,9.]],True),([[1.,1.],[1.,1.]],True),
    ([[0.,0.],[0.,0.]],True),([[1.,2.],[2.,1.]],False),([[1.,.1],[.2,1.]],False),
    ([[-1.,0.],[0.,1.]],False),([[1.,np.nan],[np.nan,1.]],False), ([[1.,0.]],False)])
def test_covariance_symmetry_psd_and_invalidities(matrix,valid):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/matrices/matrixModels/AbstractMatrixModel.java:118-123.
    That snapshot calls Cholesky (strict PD) with an inverted return flag; P3
    intentionally validates PSD, including singular matrices, independently.
    """
    assert validate_covariance(('a','b'),matrix).valid is valid


def test_measured_correlation_conversion_and_unknowns():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/matrices/matrixModels/CovarianceMatrixModel.java:217-245
    normalizes with D^-1 S D^-1. CorrelationMatrixModel.java:93-99 fills symmetric pairs.
    """
    covariance = measured_correlation_to_covariance(('a','b'),[2.,3.],[[1.,.5],[.5,1.]])
    np.testing.assert_equal(covariance,[[4.,3.],[3.,9.]])
    np.testing.assert_allclose(covariance_to_measured_correlation(('a','b'),covariance),[[1.,.5],[.5,1.]])
    for rho in ([[1.,np.nan],[np.nan,1.]], [[1.,1.1],[1.1,1.]], [[.5,0.],[0.,1.]]):
        with pytest.raises(ValueError): measured_correlation_to_covariance(('a','b'),[2.,3.],rho)
    with pytest.raises(ValueError):
        measured_correlation_to_covariance(('a','b','c'),[1.,1.,1.],[[1.,.9,.9],[.9,1.,-.9],[.9,-.9,1.]])
    with pytest.raises(ValueError): covariance_to_measured_correlation(('a','b'),[[0.,0.],[0.,1.]])
    assert not validate_covariance(('a','a'),np.eye(2)).valid
    assert not validate_covariance(('a','b'),np.array([[1.,2.],[2.,1.]])*1e-30).valid
    with pytest.raises(ValueError): measured_correlation_to_covariance(('a','b'),[-1.,1.],np.eye(2))
    with pytest.raises(ValueError): validate_covariance(('a','b'),np.eye(2),relative_tolerance=np.nan)


@pytest.mark.parametrize('document', [None,[],False,{'version':True}, {'version':2}, {'version':1,'events':[],'applied':True},
    {'version':1,'events':[],'applied':1}, {'version':1,'events':[{}],'applied':0}])
def test_malformed_history_is_rejected(document):
    with pytest.raises(ValueError): CompositionBook.from_dict(document)


def test_replay_rejects_dependency_cycle_even_in_redo_tail():
    document = {'version':1,'events':[{'key':'synthetic','before':None,'after': {
        'key':'synthetic','name':'Synthetic','members':[{'run_id':'synthetic','blocks':[]}],
        'expressions':[spec('[derived:x]').to_dict()]}}], 'applied':0}
    with pytest.raises(ExpressionError,match='cycle'):
        CompositionBook.from_dict(document)


def test_shape_invalid_finite_source_and_unknown_block_validation():
    result = evaluate([spec('[x]')],{'x':np.array([1.,2.])},invalid={'x':np.array([True,False])})[0]
    np.testing.assert_equal(result.values,[np.nan,2.])
    assert result.invalid.tolist() == [True,False]
    for columns,masks in [({'x':np.ones((2,2))},None),({'x':np.ones(2),'y':np.ones(3)},None),({'x':np.ones(2)},{'x':np.ones(3)})]:
        with pytest.raises(ExpressionError): evaluate([spec('1')],columns,masks=masks)
    with pytest.raises(ValueError): Member('synthetic',(True,))
    with pytest.raises(ValueError): Member('synthetic',(1,1))
    a,b,sources = two_members()
    b.run.time[:] = 1e100
    with pytest.raises(ValueError,match='date range'):
        concatenate((Member(a.run.run_id),Member(b.run.run_id)),sources)


def test_session_malformed_composition_is_explicit_error(tmp_path):
    from rawtims.readers import open_run
    a = Analysis(open_run(SYNTHETIC_U))
    path = save_session(SessionState(fractions=[Fraction('Synthetic',u=a)]),tmp_path/'synthetic.rawtims')
    document = json.loads(path.read_text())
    document['composition'] = []
    path.write_text(json.dumps(document))
    with pytest.raises(SessionError,match='composition'):
        load_session(path)


def test_split_acquisition_objects_reassemble_committed_fixture():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:177-228.
    Metamorphic split of committed fixture A into two new acquisition objects;
    original source hash, cycle IDs, masks and blocks survive reassembly.
    """
    original = Analysis(copy.deepcopy(read(TIMSDP_FILES['GHR1 230921 F08b-216'])))
    first_block = original.blocks[len(original.blocks)//2]
    selections = [np.flatnonzero(original.run.block < first_block), np.flatnonzero(original.run.block >= first_block)]
    pieces = []
    for n, rows in enumerate(selections):
        r = original.run
        split_run = replace(r, run_id=f'synthetic-split-{n}', cycle=r.cycle[rows].copy(),block=r.block[rows].copy(),
                            time=r.time[rows].copy(), values=r.values[rows].copy(),invalid=r.invalid[rows].copy())
        a = Analysis(split_run)
        a.toggle_cycles([0], a.keys, False)
        pieces.append(a)
    t = concatenate(tuple(Member(a.run.run_id) for a in reversed(pieces)),{a.run.run_id:a for a in pieces})
    for attribute in ('values','invalid','cycle','block','time'):
        np.testing.assert_equal(getattr(t,attribute),getattr(original.run,attribute))
    np.testing.assert_equal(t.included,np.concatenate([a.effective for a in pieces]))
    assert set(t.source_hashes) == {original.run.raw.sha256}
    assert t.boundaries == (len(selections[0]),)
