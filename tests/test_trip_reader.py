"""Synthetic NRBF only: no private instrument data in fixtures."""
import struct
from decimal import Decimal

import numpy as np
import pytest

from rawtims.readers import UnsupportedFile, open_paths, sniff
from rawtims.readers.trip import HEADER, decode_nrbf, read_trip


def i(n):
    return struct.pack('<i', n)


def s(text):
    data = text.encode()
    n, prefix = len(data), bytearray()
    while n >= 128:
        prefix.append((n & 127) | 128)
        n >>= 7
    return bytes(prefix + bytes([n])) + data


def string(oid, text):
    return b'\x06' + i(oid) + s(text)


def cls(oid, name, members, types, info=b'', values=b''):
    return b'\x04' + i(oid) + s(name) + i(len(members)) + b''.join(map(s, members)) + bytes(types) + info + values


def stream(body):
    return HEADER + body + b'\x0b'


def test_forward_shared_and_cyclic_references():
    data = stream(cls(1, 'Inert', ['self', 'a', 'b'], [2, 2, 2],
                      values=b'\x09' + i(1) + b'\x09' + i(2) + b'\x09' + i(2)) + string(2, 'hello'))
    x = decode_nrbf(data)
    assert x['self'] is x
    assert x['a'] is x['b']
    assert x['a'] == 'hello'


def test_nested_class_and_reused_metadata():
    child = cls(2, 'Child', ['n'], [0], b'\x08', i(42))
    data = stream(cls(1, 'Root', ['a', 'b'], [2, 2], values=child + b'\x01' + i(3) + i(2) + i(73)))
    x = decode_nrbf(data)
    assert x['a'] == {'__class__': 'Child', 'n': 42}
    assert x['b']['n'] == 73


@pytest.mark.parametrize('tag,fmt,values', [(6, 'd', [1.25, 2.5]), (8, 'i', [-5, 7]), (1, 'B', [0, 1])])
def test_primitive_array(tag, fmt, values):
    data = stream(b'\x0f' + i(1) + i(2) + bytes([tag]) + struct.pack('<2' + fmt, *values))
    np.testing.assert_array_equal(decode_nrbf(data), values)


def test_binary_rectangular_array_and_null_runs():
    data = stream(b'\x07' + i(1) + b'\x02' + i(2) + i(2) + i(2) + b'\x00\x08' + struct.pack('<4i', 1, 2, 3, 4))
    np.testing.assert_array_equal(decode_nrbf(data), [1, 2, 3, 4])
    data = stream(b'\x10' + i(1) + i(5) + b'\x0d\x02' + string(2, 'x') + b'\x0e' + i(2))
    assert decode_nrbf(data) == [None, None, 'x', None, None]


def test_decimal_datetime_unicode():
    x = decode_nrbf(stream(cls(1, 'Values', ['d', 't', 's'], [0, 0, 1], b'\x05\x0d',
                                s('0.00206') + struct.pack('<Q', 100 | (1 << 62)) + string(2, 'αβ'))))
    assert x['d'] == Decimal('0.00206')
    assert x['t'] == {'ticks': 100, 'kind': 1}
    assert x['s'] == 'αβ'


def test_every_truncation_is_clear_error():
    data = stream(cls(1, 'Root', ['a'], [2], values=string(2, 'nested')))
    for n in range(len(data)):
        with pytest.raises(UnsupportedFile):
            decode_nrbf(data[:n])


@pytest.mark.parametrize('body', [
    b'\x0f' + i(1) + i(-1) + b'\x06',
    b'\x0f' + i(1) + i(2_000_001) + b'\x06',
    b'\x10' + i(1) + i(1) + b'\x0d\x02',
    cls(1, 'X', ['a'], [2], values=b'\x09' + i(999)),
    cls(1, 'X', ['a'], [2], values=string(1, 'duplicate')),
    b'\x06' + i(1) + b'\xff\xff\xff\xff\xff',
    b'\x15',  # remoting is never executed
    cls(1, 'X', ['a'], [0], b'\x01', b'\x03'),
])
def test_bad_lengths_references_and_records(body):
    with pytest.raises(UnsupportedFile):
        decode_nrbf(stream(body))


def test_caps_total_slots_records_bytes_and_depth(monkeypatch):
    from rawtims.readers import trip
    data = stream(cls(1, 'X', ['a'], [2], values=string(2, 'ok')))
    for cap, value in [('MAX_BYTES', 10), ('MAX_RECORDS', 1), ('MAX_SLOTS', 1), ('MAX_DEPTH', 0)]:
        with monkeypatch.context() as m:
            m.setattr(trip, cap, value)
            with pytest.raises(UnsupportedFile):
                decode_nrbf(data)


def test_project_sniff_is_not_run_and_wrong_root_rejected(tmp_path):
    path = tmp_path / 'project.unknown'
    path.write_bytes(stream(cls(1, 'Tripoli.TripoliWorkProduct', [], [])))
    assert 'legacy Tripoli project' in sniff(path).reason
    runs, skipped = open_paths([path])
    assert not runs and 'legacy Tripoli project' in skipped[0][1]
    with pytest.raises(UnsupportedFile, match='ArrayList'):
        read_trip(path)
    path.write_bytes(stream(cls(1, 'Other', [], [])))
    with pytest.raises(UnsupportedFile, match='root'):
        read_trip(path)


def test_trailing_bytes_are_rejected():
    with pytest.raises(UnsupportedFile, match='trailing'):
        decode_nrbf(stream(string(1, 'ok')) + b'\x00')


def test_typed_project_retains_signed_values_original_stats_and_settings(tmp_path):
    # Entirely invented small project, including ArrayList capacity padding.
    values = b'\x0f' + i(4) + i(3) + b'\x06' + struct.pack('<3d', 1.0, -2.0, 0.0)
    ratio = cls(3, 'Tripoli.RawRatio', ['Name', 'Ratios', 'CyclesPerBlock', 'AllMean'],
                [1, 2, 0, 0], b'\x08\x06', string(5, '206/205 D') + values + i(3) + struct.pack('<d', 1.5))
    items = b'\x10' + i(2) + i(2) + ratio + b'\x0a'
    source = cls(6, 'System.IO.FileInfo', ['FullPath'], [1], values=string(7, 'C:\\synthetic.xls'))
    root = cls(1, 'Tripoli.TripoliWorkProduct',
               ['ArrayList+_items', 'ArrayList+_size', '_r18O_16O', '_ChauvenetsThreshold', '_SourceFileInfo'],
               [2, 0, 0, 0, 2], b'\x08\x05\x06', items + i(1) + s('0.00206') + struct.pack('<d', 0.5) + source)
    path = tmp_path / 'synthetic.trip'
    path.write_bytes(stream(root))
    p = read_trip(path)
    assert p.sources[0].name == 'synthetic.xls'
    assert p.sources[0].dates == {}  # absent dates are not invented
    assert p.settings.r18 == Decimal('0.00206')
    assert p.settings.chauvenet_threshold == 0.5
    r, = p.ratios
    np.testing.assert_array_equal(r.values, [1, -2, 0])
    np.testing.assert_array_equal(r.accepted, [True, False, False])
    assert r.block_flags is None
    assert r.statistics == {'AllMean': 1.5}
    assert 'Mean' not in r.statistics and r.block_statistics == {}


def test_unknown_library_and_nested_array_references():
    bad = b'\x05' + i(1) + s('Inert') + i(0) + i(88)
    with pytest.raises(UnsupportedFile, match='library'):
        decode_nrbf(stream(bad))
    valid = b'\x0c' + i(88) + s('Only an inert label') + bad
    assert decode_nrbf(stream(valid)) == {'__class__': 'Inert'}
    nested = b'\x10' + i(1) + i(2) + b'\x10' + i(2) + i(1) + b'\x09' + i(1) + b'\x09' + i(2)
    x = decode_nrbf(stream(nested))
    assert x[0] is x[1] and x[0][0] is x
