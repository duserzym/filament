"""Synthetic saved-work streams only; no reference-app saved specimen exists.

These are parser-scaffold/source-shape oracles, not verified binary migration
of a complete acquisition. Pinned snapshots: OGTripoli d906f70, Tripoli 00dc941.
"""
import hashlib
import json
import struct

import numpy as np
import pytest
from test_trip_reader import cls, i, stream, string

from rawtims.readers import UnsupportedFile
from rawtims.readers.legacy_saved import (
    SESSION_CLASS,
    SESSION_UID,
    LegacyInspection,
    decode_java_session,
    graph_document,
    inspect_saved,
)


def utf(text):
    data = text.encode('utf-8')
    return struct.pack('>H',len(data))+data


def java_string(text):
    return b'\x74'+utf(text)


def java_session(*, name=SESSION_CLASS, uid=SESSION_UID, flags=2, tail=b'', fields=None):
    # Java serialization stream, SC_SERIALIZABLE class descriptor, no super.
    fields = fields or [('Z','mutable',None,b'\x01'),('L','sessionName','Ljava/lang/String;',java_string('SYNTHETIC session')),
                        ('L','sessionNotes','Ljava/lang/String;',java_string('SYNTHETIC note')),
                        ('L','mapOfAnalyses','Lorg/cirdles/tripoli/sessions/TripoliSessionAnalysisMap;',b'\x70')]
    descriptors = b''.join(kind.encode()+utf(field)+(java_string(signature) if signature else b'') for kind,field,signature,value in fields)
    return b'\xac\xed\x00\x05\x73\x72'+utf(name)+struct.pack('>qBH',uid,flags,len(fields))+descriptors+b'\x78\x70'+b''.join(value for _,_,_,value in fields)+tail


def test_java_scalar_session_source_shape_and_unknown_preservation(tmp_path):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/Session.java:38-61;
    utilities/stateUtilities/TripoliSerializer.java:40-46,64-78 under the same Java package.
    """
    data = java_session(fields=[('Z','mutable',None,b'\x01'),('I','futureField',None,struct.pack('>i',73)),
                                ('L','sessionName','Ljava/lang/String;',java_string('SYNTHETIC'))])
    path = tmp_path/'synthetic.tripoli'
    path.write_bytes(data)
    inspection = inspect_saved(path)
    assert inspection.raw['mutable'] is True
    assert inspection.raw['futureField'] == 73
    assert inspection.raw['sessionName'] == 'SYNTHETIC'
    document = json.loads(inspection.json_text())
    assert bytes.fromhex(document['source_hex']) == data
    assert document['source_sha256'] == hashlib.sha256(data).hexdigest()
    assert document['graph']['nodes'][0]['members']['futureField'] == 73


def test_java_all_truncations_refused():
    data = java_session()
    for n in range(len(data)):
        with pytest.raises(UnsupportedFile):
            decode_java_session(data[:n])


@pytest.mark.parametrize('data',[java_session(name='java.lang.Runtime'),java_session(uid=1),java_session(flags=3),
                                java_session(flags=4),java_session(tail=b'\x70'),b'\xac\xed\x00\x05\x79',
                                java_session(fields=[('L','bad','Ljava/lang/Object;',b'\x71\x00\x7e\xff\xff')]),
                                java_session(fields=[('Z','mutable',None,b'\x02')])])
def test_java_unknown_classes_custom_hooks_and_bad_values_refused(data):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/utilities/stateUtilities/TripoliSerializer.java:72-78.

    Reference uses ObjectInputStream; this importer explicitly refuses every
    custom/externalizable class or token instead of calling that runtime.
    """
    with pytest.raises(UnsupportedFile):
        decode_java_session(data)


def test_java_modified_utf8_and_shared_references():
    data = java_session(fields=[('L','sessionName','Ljava/lang/String;',b'\x74\x00\x08A\xc0\x80\xed\xa0\xbd\xed\xb8\x80')])
    # String payload is A + NUL + one surrogate pair: 9 bytes, not UTF-8's 6.
    data = data.replace(b'\x74\x00\x08A',b'\x74\x00\x09A')
    assert decode_java_session(data)['sessionName'] == 'A\0😀'
    # Handle 0=class descriptor, 1=field signature, 2=Session object.
    data = java_session(fields=[('L','self','Ljava/lang/Object;',b'\x71\x00\x7e\x00\x02')])
    root = decode_java_session(data)
    assert root['self'] is root
    assert graph_document(root)['nodes'][0]['members']['self'] == {'ref':0}


def test_java_descriptor_references_cannot_become_data_objects():
    data = java_session(fields=[('L','future','Ljava/lang/Object;',b'\x71\x00\x7e\x00\x00')])
    with pytest.raises(UnsupportedFile,match='descriptor'):
        decode_java_session(data)


@pytest.mark.parametrize('root_name',['Tripoli.TripoliHistoryFolderStandards','Tripoli.TripoliHistoryFolderGains'])
def test_history_source_members_are_inert_and_retained(tmp_path,root_name):
    """OGTripoli/source/TripoliHistoryFolderStandards.cs:124-143;
    OGTripoli/source/TripoliHistoryFolderGains.cs:122-141.
    Both serialize FolderInfo, AllRatioHistories and RejectLevelSigma after
    the work-product base. Paths and unknown fields remain plain data.
    """
    data = stream(cls(1,root_name,['FolderInfo','AllRatioHistories','RejectLevelSigma','Future'],[1,2,0,1],b'\x08',
                      string(2,'C:\\DO-NOT-OPEN')+b'\x0a'+i(10)+string(3,'SYNTHETIC unknown')))
    path = tmp_path/'synthetic.triphis'
    path.write_bytes(data)
    result = inspect_saved(path)
    assert result.raw['FolderInfo'] == 'C:\\DO-NOT-OPEN'
    assert result.raw['RejectLevelSigma'] == 10
    assert result.raw['Future'] == 'SYNTHETIC unknown'
    assert json.loads(result.json_text())['source_format'] == 'dotnet-history'
    assert list(tmp_path.iterdir()) == [path]


def test_history_unknown_root_and_java_wrong_extension_refused(tmp_path):
    path = tmp_path/'synthetic.triphis'
    path.write_bytes(stream(cls(1,'Unknown',[],[])))
    with pytest.raises(UnsupportedFile,match='root'):
        inspect_saved(path)
    path = tmp_path/'synthetic.trip'
    path.write_bytes(java_session())
    with pytest.raises(UnsupportedFile):
        inspect_saved(path)


def test_graph_cycles_arrays_unknowns_nan_and_decimal(tmp_path):
    from decimal import Decimal
    root = {'unknown':Decimal('0.00206'), 'arrays':[np.array([1,np.nan]),np.array([2,np.inf])], 'saved':{'x':'inert'}}
    root['self'] = root
    inspection = LegacyInspection(tmp_path/'synthetic.trip','synthetic',b'SYNTHETIC',root)
    document = json.loads(inspection.json_text())
    graph = document['graph']
    assert graph['nodes'][0]['members']['self'] == {'ref':0}
    assert graph['nodes'][0]['members']['unknown'] == {'decimal':'0.00206'}
    arrays = [n for n in graph['nodes'] if n['kind'] == 'array']
    assert len(arrays) == 2 and arrays[0]['values'] != arrays[1]['values']
    assert 'NaN' not in inspection.json_text()  # special floats are tagged data, valid JSON
