"""P2 exchange oracles; source references use Tripoli 00dc941 / OGTripoli d906f70.

The complete cycle-byte oracle was already committed. Synthetic XML/OG byte
expectations below are independent transcriptions of the pinned serializers,
not snapshots obtained by running Java/.NET (neither runtime is installed).
"""
import xml.etree.ElementTree as ET
from datetime import date

import numpy as np
import pytest
from oracle_reports import read_short_report
from reader_fixtures import ORACLE_CYCLES, TIMSDP_FILES, TRIPOLI, read

from rawtims.analysis import Analysis, AnalysisSettings
from rawtims.exports import cycles_csv_text
from rawtims.fractions import Fraction
from rawtims.model import RawFile, Run, RunMetadata
from rawtims.readers import UnsupportedFile
from rawtims.readers.functions import build_functions
from rawtims.readers.og_text import parse_og_text
from rawtims.tripoli_exchange import (
    et_redux_xml,
    java_cycles_tsv,
    java_double,
    og_text,
    write_exchange,
)


def synthetic(names=('206/204 D',), values=((1.,),(3.,),(5.,)), *, element='Pb', complete=True):
    functions = build_functions(list(names))
    values = np.array(values,dtype=float)
    n = len(values)
    run = Run('synthetic-p2',RawFile('SYNTHETIC','SYNTHETIC',0,'0'*64,'synthetic'),element,
              RunMetadata(sample_id='SYNTHETIC sample',method='SYNTHETIC method',cycles_per_block=2,complete=complete),
              functions,np.arange(1,n+1),np.arange(n)//2+1,np.arange(n,dtype=float),values,
              ~np.isfinite(values) | (values <= 0))
    return Analysis(run)


@pytest.mark.parametrize('stem', ['GHR1 230921 F08b-216','WH205 z4 Pb-654'])
def test_committed_java_cycle_bytes(stem):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:703-782.

    Oracles: TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/
    cycleReports/IsotopxPhoenixTIMS/{KU_IGL/IsolinxVersion2,Purdue}/Oracle-*.tsv.
    Both input and full-byte answers are committed, untouched Tripoli fixtures.
    """
    a = Analysis(read(TIMSDP_FILES[stem]))
    expected = next(ORACLE_CYCLES.rglob('Oracle-'+stem+'-report.tsv')).read_bytes()
    assert java_cycles_tsv(a).encode() == expected


def test_java_rejection_padding_and_native_invariance():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:703-733."""
    a = synthetic()
    a.toggle_cycles([1],a.keys,False)
    before = cycles_csv_text(a), a.settings, a.history
    text = java_cycles_tsv(a)
    assert text.splitlines()[-2] == '2                \t1.0              \t&3.0&'
    assert text.splitlines()[-1] == '3                \t2.0              \t5.0'
    assert (cycles_csv_text(a),a.settings,a.history) == before


@pytest.mark.parametrize('value,expected',[(.001,'0.001'),(.0001,'1.0E-4'),(1e7,'1.0E7'),(9999999.,'9999999.0'),
                                          (-0.,'-0.0'),(1.2345678901234567e-10,'1.2345678901234568E-10'),(5e-324,'4.9E-324'),
                                          (float('nan'),'NaN'),(float('inf'),'Infinity')])
def test_java_number_conventions(value,expected):
    """Analysis.java:711-714 delegates to Double.toString; decimal/exponent thresholds are Java conventions."""
    assert java_double(value) == expected


def test_java_missing_source_behavior_without_native_change():
    a = synthetic(values=((1.,),(np.nan,)))
    before = cycles_csv_text(a)
    assert java_cycles_tsv(a).splitlines()[-1].endswith('&NaN&')
    assert cycles_csv_text(a) == before


def test_og_source_bytes_and_signed_import():
    """OGTripoli/source/TripoliWorkProduct.cs:2901-3051 and RawRatio.cs:804-875.

    Windows CRLF / en-US date and E9 are explicitly pinned. This synthetic
    partial final block also exercises Java OgTripoliImporter.java:176-183's
    final-block case, retaining its masks rather than losing that final block.
    """
    a = synthetic()
    a.toggle_cycles([1],a.keys,False)
    expected = (
        'Tripoli tab-delimited output of processed data for:\r\nSYNTHETIC.trip\r\nproduced on: 11/25/2026\r\n\r\n'
        'Each column header shows ratio name, Tripolized mean, Tripolized stdErr, Fractionation Corrected flag.\r\n'
        'Data is presented by blocks that are separated by blank lines. \r\n'
        'Any discarded value is shown as a negative number. \r\n'
        'Any missing value is represented by a blank entry. \r\n\r\n'
        '206/204 D       \t\r\n                \t\r\n                \t\r\n'
        '3.000000000E+000\t\r\n6.666666667E+001\t\r\nnot frac corr   \t\r\n\r\n'
        '1.000000000E+000\t\r\n-3.000000000E+000\t\r\n\r\n5.000000000E+000\t\r\n')
    text = og_text(a,source_name='SYNTHETIC.trip',produced_on=date(2026,11,25))
    assert text.encode() == expected.encode()
    parsed = parse_og_text(text.encode())
    assert parsed.names == ('206/204 D',)
    np.testing.assert_equal(parsed.values[:,0],[1,3,5])
    np.testing.assert_equal(parsed.included[:,0],[True,False,True])
    np.testing.assert_equal(parsed.block,[1,1,2])
    assert parsed.statistics[-1] == ('not frac corr',)


def test_og_missing_duplicate_metadata_and_corrected_flags():
    """OGTripoli/source/TripoliWorkProduct.cs:2920-3008; all header metadata survives inspection."""
    a = synthetic(names=('206/204 D','206/204 D'),values=((1,2),(0,np.nan),(3,4)))
    text = og_text(a,produced_on=date(2026,1,2))
    parsed = parse_og_text(text.encode())
    assert parsed.names == ('206/204 D','206/204 D')
    assert not parsed.included[1].any()
    assert np.isnan(parsed.values[1]).all()
    corrected = text.replace('not frac corr','frac corr    ')
    assert parse_og_text(corrected.encode()).statistics[-1] == ('frac corr','frac corr')


@pytest.mark.parametrize('change',[lambda s:s.replace('Tripoli tab','Unknown tab'),lambda s:s.replace('not frac corr','unknown flag '),
                                   lambda s:s+'1\t2\t\r\n',lambda s:s.replace('1.000000000E+000','Infinity')])
def test_og_unknown_refused(change):
    text = og_text(synthetic(),produced_on=date(2026,1,2))
    with pytest.raises(UnsupportedFile):
        parse_og_text(change(text).encode())


def test_og_refuses_unrepresentable_negative_or_blocks():
    for a in (synthetic(values=((-1.,),(2.,))),synthetic()):
        if a.values[0,0] > 0:
            a.run.block = np.array([7,7,8])
        with pytest.raises(ValueError):
            og_text(a,produced_on=date(2026,1,2))


def test_xml_source_schema_bytes():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/
    utilities/xml/ETReduxFractionXMLConverter.java:47-99;
    utilities/xml/MeasuredRatioModelXMLConverter.java:63-88;
    sessions/analysis/outputs/etRedux/ETReduxFraction.java:69-93,220-223;
    DataDictionary.java:34-39. Independent synthetic full-byte expectation.
    """
    a = synthetic(('238/235 oxide R18 0.00206','233/235 oxide R18 0.00206','238/233 oxide'),
                  ((100,2,50),(100,2,50),(100,2,50)),element='U')
    f = Fraction('SYNTHETIC-z1',u=a,sample='SYNTHETIC sample & lab')
    expected = '<UPbReduxFraction>\n  <sampleName>SYNTHETIC sample &amp; lab</sampleName>\n  <fractionID>SYNTHETIC-z1</fractionID>\n  <ratioType>U</ratioType>\n  <pedigree>None</pedigree>\n  <measuredRatios>\n'
    # Source dictionary order is pinned independently of the implementation.
    for name,value,oxide in [('238_236','0.0','false'),('233_236','0.0','false'),('238_235','100.0','true'),
                             ('233_235','2.0','true'),('238_233','50.0','true')]:
        expected += f'    <MeasuredUserFunctionModel>\n      <name>{name}</name>\n      <value>{value}</value>\n      <uncertaintyType>PCT</uncertaintyType>\n      <oneSigma>0.0</oneSigma>\n      <fracCorr>false</fracCorr>\n      <oxideCorr>{oxide}</oxideCorr>\n    </MeasuredUserFunctionModel>\n'
    expected += '  </measuredRatios>\n  <meanAlphaU>0.0</meanAlphaU>\n  <meanAlphaPb>0.0</meanAlphaPb>\n  <r18O16O>0.00206</r18O16O>\n  <labUBlankMass>0.0</labUBlankMass>\n  <r238235b>0.0</r238235b>\n  <r238235s>0.0</r238235s>\n  <tracerMass>0.0</tracerMass>\n</UPbReduxFraction>\n'
    before = cycles_csv_text(a),a.settings,a.history
    assert et_redux_xml(f,'U').encode() == expected.encode()
    assert (cycles_csv_text(a),a.settings,a.history) == before


def test_xml_committed_geometric_statistics_oracle():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/outputs/etRedux/MeasuredUserFunction.java:64-116; committed A short report."""
    stem = 'GHR1 230921 F08b-216'
    a = Analysis(read(TIMSDP_FILES[stem]),AnalysisSettings(stat_mode='geometric'))
    f = Fraction('SYNTHETIC-oracle',pb=a,sample='SYNTHETIC')
    report = {name:(mean,se) for name,mean,se in read_short_report(TRIPOLI/'oracle/shortReports/KU_IGL/IsolinxVersion2'/('Oracle-'+stem+'.txt'))}
    root = ET.fromstring(et_redux_xml(f,'Pb'))
    for entry in root.find('measuredRatios'):
        name = entry.findtext('name').replace('_','/')
        if name not in report:
            assert entry.findtext('value') == '0.0'
            continue
        mean,se = report[name]
        assert float(entry.findtext('value')) == pytest.approx(mean,rel=1e-9)
        assert float(entry.findtext('oneSigma')) == pytest.approx(se,rel=1e-9)
        assert entry.findtext('fracCorr') == 'false'


@pytest.mark.parametrize('complete,aborted,end',[(None,False,None),(False,False,None),(True,True,None),(False,True,'AnalysisCompleted')])
def test_xml_only_completed(complete,aborted,end):
    a = synthetic(complete=complete)
    a.run.metadata.aborted = aborted
    a.run.metadata.extra['end_status'] = end
    with pytest.raises(ValueError,match='completed'):
        et_redux_xml(Fraction('SYNTHETIC',pb=a,sample='SYNTHETIC'),'Pb')


def test_exclusive_exchange_creation_and_explicit_replace(tmp_path):
    """P2 explicit-file overwrite requirement; Java XMLSerializerInterface.java:74 instead replaces unconditionally."""
    path = tmp_path/'synthetic.xml'
    write_exchange(path,'one\r\n')
    with pytest.raises(FileExistsError):
        write_exchange(path,'two')
    assert path.read_bytes() == b'one\r\n'
    write_exchange(path,'two',overwrite=True)
    assert path.read_bytes() == b'two'
    assert list(tmp_path.iterdir()) == [path]


def test_xml_unknown_instrument_oxygen_ratio_refused():
    """ETReduxFraction.java:69-72 requires the r18 parameter; unknown acquisition r18 must not be guessed."""
    a = synthetic(('238/235 oxide','233/235 oxide','238/233 oxide'),((100,2,50),(101,2,50)),element='U')
    with pytest.raises(ValueError,match='known r18'):
        et_redux_xml(Fraction('SYNTHETIC',u=a,sample='SYNTHETIC'),'U')


def test_og_correction_label_source_rows():
    """OGTripoli/source/TripoliWorkProduct.cs:2920-2977, literal name splitting and third-row padding."""
    a = synthetic(('206/204 D\r\n  corrected with tracer',))
    rows = og_text(a,produced_on=date(2026,11,25)).splitlines()
    assert rows[9:12] == ['206/204 D       \t',' corrected      \t','with tracer      \t']
    parsed = parse_og_text(og_text(a,produced_on=date(2026,11,25)).encode())
    assert parsed.statistics[:2] == (('corrected',),('with tracer',))
