"""Read legacy Tripoli projects as data, without .NET deserialization.

The bounded MS-NRBF decoder implements typed classes, references, strings and
arrays (Microsoft MS-NRBF sections 2.1–2.5). Class names are inert dictionary
labels, never imports. Unknown/untyped/remoting records are rejected. Reference
edges are linked once after parsing, including forward references and cycles;
no recursive expansion or repeated parsing is performed.

Field meanings follow OGTripoli source/TripoliWorkProduct.cs (serialization),
RawRatio.cs (GetObjectData, CalcStats, DiscardRatio, CalculateBlockMeans), and
RunParameters.cs. This is an independent format/method implementation:

* project SourceFileInfo is a Windows FileInfo (OriginalPath/FullPath), not
  necessarily every concatenated source. Notations may name further sources.
  DateTime ticks and kind bits are preserved, with no invented timezone.
* project settings retain every serialized member except the ratio collection
  and source info: tracer, r18O_16O, ChauvenetsThreshold, natural 238/235,
  U sample components, correction flags, interference constants, alphaPb,
  timestamp, fraction identity and display state. Capability flags do not mean
  that a correction was actually applied.
* RawRatio.Ratios contains SIGNED doubles: positive means accepted, negative
  means rejected (magnitude is the measured value), zero means missing/bad.
  ActiveRatios/ActiveRatiosMap are display caches, not acceptance flags.
  Block rejection flips cycle signs; there is no independent persisted block
  mask in 4.10.0.3. ``block_flags`` is None when absent, never inferred as intent.
* AllMean/AllStdDev/AllStdErr/AllPctStdErr/AllCount/AllMissing and AllMin/AllMax
  are the ORIGINAL, unfiltered statistics captured by the Ratios setter.
  Accepted Mean/StdDev/StdErr/PctStdErr/LiveDataCount and BlockMeans are NOT
  serialized by RawRatio.GetObjectData in 4.10.0.3. We expose only statistics
  actually present; a parity harness must label reconstructed ones explicitly.
* CalcStats pools positive cycles, using arithmetic mean, sample SD (n-1),
  SE=SD/sqrt(n), percent SE=100*SE/mean. Its sum-of-squares subtraction loses
  precision on very stable beams. StatsDetailDisplay selects presentation
  (including 2 sigma); it does not change the stored 1-sigma errors.
* Alpha is per-cycle decimal fractionation; meanAlphaU is the saved mean alpha
  (also for Pb). oxidationCorrected/fractionationCorrected are per-function
  flags. CyclesPerBlock counts rows, including beam interpolation rows.
* forms/frmRatioGraph.cs implements 2-sigma as one pass on the currently
  positive points, with strict |x-mean| > 2 SD. Its Chauvenet action repeatedly
  removes the single most extreme point and recalculates while
  n*erfc(z/sqrt(2)) < threshold. SetOutliers prevents removing points when
  live count <= 2 + requested removal count. These differ from Java's one-pass
  Chauvenet/minimum-20 rule. Reading a project never re-runs either algorithm.

The plain ``raw`` graph preserves unknown members, undo snapshots, original
statistics and settings so readers do not silently discard numeric context.
"""
from __future__ import annotations

import re
import struct
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import numpy as np

from rawtims.readers import UnsupportedFile

MAX_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 1_000_000
MAX_SLOTS = 2_000_000
MAX_STRING = 1_000_000
MAX_DEPTH = 100
HEADER = b'\x00\x01\x00\x00\x00\xff\xff\xff\xff\x01\x00\x00\x00\x00\x00\x00\x00'


@dataclass(frozen=True)
class _Ref:
    oid: int


@dataclass(frozen=True)
class _Nulls:
    count: int


class _Decoder:
    def __init__(self, data: bytes):
        if len(data) > MAX_BYTES:
            raise UnsupportedFile('NRBF byte limit exceeded')
        self.data = data
        self.pos = self.records = self.slots = 0
        self.objects: dict[int, Any] = {}
        self.schemas: dict[int, tuple] = {}
        self.libraries: dict[int, str] = {}
        self.library_refs: set[int] = set()

    def fail(self, message):
        raise UnsupportedFile(f'NRBF at byte {self.pos}: {message}')

    def take(self, count):
        if count < 0 or count > len(self.data) - self.pos:
            self.fail('truncated input or invalid length')
        start = self.pos
        self.pos += count
        return self.data[start:self.pos]

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

    def byte(self):
        return self.unpack('B')

    def integer(self):
        return self.unpack('i')

    def length(self, limit=MAX_SLOTS):
        n = self.integer()
        if not 0 <= n <= limit:
            self.fail('length limit exceeded')
        return n

    def reserve(self, count):
        self.slots += count
        if self.slots > MAX_SLOTS:
            self.fail('total member/array slot limit exceeded')

    def string(self):
        n = 0
        for shift in range(0, 35, 7):
            b = self.byte()
            n |= (b & 127) << shift
            if not b & 128:
                if n > MAX_STRING:
                    self.fail('string length limit exceeded')
                return self.take(n).decode('utf-8')
        self.fail('invalid length-prefixed string')

    def put(self, oid, value):
        # Negative IDs occur for embedded .NET value types.
        if oid == 0 or oid in self.objects:
            self.fail('zero or duplicate object ID')
        self.objects[oid] = value
        return value

    def primitive(self, typ):
        formats = {1: '?', 2: 'B', 6: 'd', 7: 'h', 8: 'i', 9: 'q',
                   10: 'b', 11: 'f', 12: 'q', 14: 'H', 15: 'I', 16: 'Q'}
        if typ in formats:
            if typ == 1:
                b = self.byte()
                if b > 1:
                    self.fail('invalid Boolean')
                return bool(b)
            return self.unpack(formats[typ])
        if typ == 3:
            first = self.take(1)
            b = first[0]
            n = 1 if b < 128 else 2 if 194 <= b < 224 else 3 if 224 <= b < 240 else 0
            if not n:
                self.fail('invalid Char')
            return (first + self.take(n - 1)).decode('utf-8')
        if typ == 5:
            s = self.string()
            if len(s) > 64 or not re.fullmatch(r'-?\d+(?:\.\d+)?', s):
                self.fail('invalid Decimal')
            return Decimal(s)
        if typ == 13:
            bits = self.unpack('Q')
            ticks = bits & ((1 << 62) - 1)
            if ticks > 3155378975999999999:
                self.fail('invalid DateTime ticks')
            return {'ticks': ticks, 'kind': bits >> 62}
        self.fail(f'unsupported primitive type {typ}')

    def type_info(self, typ):
        if typ in (0, 7):
            p = self.byte()
            if p not in (1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16):
                self.fail('invalid primitive type')
            return p
        if typ == 3:
            return self.string()
        if typ == 4:
            name, library = self.string(), self.integer()
            self.library_refs.add(library)
            return (name, library)
        if typ in (1, 2, 5, 6):
            return None
        self.fail(f'unknown binary type {typ}')

    def values(self, n, typ, info, depth):
        self.reserve(n)
        if typ == 0:
            formats = {1: 'u1', 2: 'u1', 6: '<f8', 7: '<i2', 8: '<i4', 9: '<i8',
                       10: 'i1', 11: '<f4', 12: '<i8', 14: '<u2', 15: '<u4', 16: '<u8'}
            if info in formats:
                dtype = np.dtype(formats[info])
                a = np.frombuffer(self.take(n * dtype.itemsize), dtype=dtype).copy()
                if info == 1:
                    if (a > 1).any():
                        self.fail('invalid Boolean array')
                    return a.astype(bool)
                return a
            return [self.primitive(info) for _ in range(n)]
        result = []
        while len(result) < n:
            value = self.record(depth + 1)
            if isinstance(value, _Nulls):
                if not 0 < value.count <= n - len(result):
                    self.fail('null run exceeds array length')
                result.extend([None] * value.count)
            else:
                result.append(value)
        return result

    def record(self, depth=0):
        if depth > MAX_DEPTH:
            self.fail('nesting limit exceeded')
        self.records += 1
        if self.records > MAX_RECORDS:
            self.fail('record limit exceeded')
        tag = self.byte()
        if tag == 12:
            oid = self.integer()
            if oid <= 0 or oid in self.libraries:
                self.fail('invalid library ID')
            self.libraries[oid] = self.string()
            return self.record(depth + 1)
        if tag in (4, 5, 1):
            oid = self.integer()
            if tag == 1:
                sid = self.integer()
                if sid not in self.schemas:
                    self.fail('unknown class metadata ID')
                name, members, types, infos = self.schemas[sid]
            else:
                name = self.string()
                n = self.length(10000)
                self.reserve(n)
                members = [self.string() for _ in range(n)]
                if len(set(members)) != n or '__class__' in members:
                    self.fail('duplicate/reserved class member')
                types = [self.byte() for _ in range(n)]
                infos = [self.type_info(t) for t in types]
                if tag == 5:
                    self.library_refs.add(self.integer())  # identity is inert
                self.schemas[oid] = name, members, types, infos
            self.reserve(len(members))
            value = self.put(oid, {'__class__': name})
            for m, t, info in zip(members, types, infos):
                child = self.primitive(info) if t == 0 else self.record(depth + 1)
                if isinstance(child, _Nulls):
                    self.fail('null run outside array')
                value[m] = child
            return value
        if tag == 6:
            oid = self.integer()
            return self.put(oid, self.string())
        if tag == 8:
            return self.primitive(self.byte())
        if tag == 9:
            return _Ref(self.integer())
        if tag == 10:
            return None
        if tag in (13, 14):
            return _Nulls(self.byte() if tag == 13 else self.length())
        if tag in (7, 15, 16, 17):
            oid = self.integer()
            if tag == 7:
                shape_kind = self.byte()
                rank = self.length(32)
                if rank < 1 or shape_kind > 5 or (shape_kind in (0, 1, 3, 4) and rank != 1):
                    self.fail('invalid array rank/type')
                shape = [self.length() for _ in range(rank)]
                n = 1
                for size in shape:
                    n *= size
                    if n > MAX_SLOTS:
                        self.fail('array product limit exceeded')
                if shape_kind >= 3:
                    for _ in shape:
                        self.integer()  # lower bounds; values remain in storage order
                typ = self.byte()
                info = self.type_info(typ)
            else:
                n = self.length()
                typ = 0 if tag == 15 else 2 if tag == 16 else 1
                info = self.type_info(typ) if tag == 15 else None
            # Forward/self edges are linked only when the whole stream is read.
            return self.put(oid, self.values(n, typ, info, depth))
        self.fail(f'unsupported/unexpected record type {tag}')

    def decode(self):
        if self.byte() != 0:
            self.fail('missing stream header')
        root, header, major, minor = (self.integer() for _ in range(4))
        if root <= 0 or header != -1 or (major, minor) != (1, 0):
            self.fail('invalid stream header')
        while True:
            if self.pos >= len(self.data):
                self.fail('missing MessageEnd')
            if self.data[self.pos] == 11:
                self.pos += 1
                break
            value = self.record()
            if isinstance(value, (_Ref, _Nulls)) or value is None:
                self.fail('member record outside container')
        if self.pos != len(self.data) or root not in self.objects:
            self.fail('trailing bytes or missing root')
        if self.library_refs.difference(self.libraries):
            self.fail('class refers to an unknown library ID')
        # Iterate each container exactly once, independent of graph depth/sharing.
        for obj in self.objects.values():
            if isinstance(obj, (dict, list)):
                for k in (list(obj) if isinstance(obj, dict) else range(len(obj))):
                    ref = obj[k]
                    if isinstance(ref, _Ref):
                        if ref.oid not in self.objects:
                            self.fail(f'dangling reference {ref.oid}')
                        obj[k] = self.objects[ref.oid]
        return self.objects[root]


def decode_nrbf(data: bytes) -> Any:
    """Decode one bounded stream to plain dict/list/NumPy/stdlib scalar data.

    Shared references preserve identity; cyclic graphs remain cyclic. No class
    named by the input is instantiated. Unsupported records fail closed.
    """
    try:
        return _Decoder(data).decode()
    except (UnicodeError, struct.error, InvalidOperation, RecursionError) as error:
        raise UnsupportedFile(f'malformed NRBF: {error}') from error


def array_list(obj) -> list:
    """Unwrap a serialized ArrayList, respecting size rather than capacity."""
    if not isinstance(obj, dict):
        raise UnsupportedFile('expected serialized ArrayList')
    items = obj.get('_items', obj.get('ArrayList+_items'))
    n = obj.get('_size', obj.get('ArrayList+_size'))
    if not isinstance(items, list) or not isinstance(n, int) or not 0 <= n <= len(items):
        raise UnsupportedFile('invalid ArrayList size/items')
    return items[:n]


def _get(obj, key, default=None):
    return obj.get(key, obj.get('_' + key, default))


@dataclass(frozen=True)
class TripSource:
    name: str
    path: str
    dates: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class TripRatio:
    name: str
    values: np.ndarray
    accepted: np.ndarray
    cycles_per_block: int
    block_flags: np.ndarray | None
    statistics: dict[str, float]
    block_statistics: dict[str, Any]
    alpha: Any
    settings: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class TripSettings(Mapping[str, Any]):
    """Typed numeric controls plus lossless access to all serialized settings.

    Mapping keys retain the legacy member spelling without leading underscores.
    ``timestamp`` is the project save timestamp; it is not an acquisition date.
    """

    chauvenet_threshold: float
    r18: Decimal
    oxide_corrected: bool
    fractionation_corrected: bool
    bapo2_tl_corrected: bool
    use_tracer_correction: bool
    use_interference_correction: bool
    tracer: dict[str, Any] | None
    alpha_pb: Decimal
    natural_238_235: float | None
    timestamp: dict[str, int] | None
    raw: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.raw)

    def __len__(self) -> int:
        return len(self.raw)


@dataclass(frozen=True)
class TripProject:
    path: Path
    version: str | None
    sources: tuple[TripSource, ...]
    settings: TripSettings
    ratios: tuple[TripRatio, ...]
    raw: dict[str, Any]


def read_trip(path: str | Path) -> TripProject:
    """Read a legacy project, separately from raw-run opening/sniff dispatch."""
    path = Path(path)
    with path.open('rb') as handle:
        data = handle.read(MAX_BYTES + 1)
    decoder = _Decoder(data)
    try:
        root = decoder.decode()
        if not isinstance(root, dict) or root.get('__class__') != 'Tripoli.TripoliWorkProduct':
            raise UnsupportedFile('NRBF root is not a legacy Tripoli project')
        ratios = []
        stat_names = ('AllMin', 'AllMax', 'AllMean', 'AllStdDev', 'AllStdErr', 'AllPctStdErr',
                      'AllCount', 'AllMissing', 'Min', 'Max', 'Mean', 'StdDev', 'StdErr',
                      'PctStdErr', 'LiveDataCount')
        for obj in array_list(root):
            if not isinstance(obj, dict) or obj.get('__class__') != 'Tripoli.RawRatio':
                raise UnsupportedFile('project contains a non-RawRatio member')
            values = np.asarray(_get(obj, 'Ratios'), dtype=float)
            if values.ndim != 1 or not np.isfinite(values).all():
                raise UnsupportedFile('invalid RawRatio values')
            cpb = _get(obj, 'CyclesPerBlock', 0)
            if not isinstance(cpb, int) or cpb < 0:
                raise UnsupportedFile('invalid CyclesPerBlock')
            name = _get(obj, 'Name')
            if not isinstance(name, str):
                raise UnsupportedFile('invalid RawRatio name')
            stats = {k: float(_get(obj, k)) for k in stat_names if _get(obj, k) is not None}
            flags = _get(obj, 'BlockFlags')
            ratios.append(TripRatio(name, values, values > 0, cpb,
                                    None if flags is None else np.asarray(flags, dtype=bool),
                                    stats, {k: v for k, v in obj.items() if 'Block' in k and k != 'CyclesPerBlock'},
                                    _get(obj, 'Alpha'),
                                    {k: v for k, v in obj.items() if k not in ('Ratios', 'Alpha', 'UndoHistory', 'ActiveRatios', 'ActiveRatiosMap') and k not in stats}, obj))
        source = _get(root, 'SourceFileInfo')
        sources = []
        if isinstance(source, dict):
            full = source.get('FullPath', source.get('OriginalPath', ''))
            if not isinstance(full, str):
                raise UnsupportedFile('invalid source FileInfo path')
            sources.append(TripSource(full.replace('\\', '/').rsplit('/', 1)[-1], full,
                                      {k: v for k, v in source.items() if isinstance(v, dict) and 'ticks' in v}, source))
        version = next((re.search(r'Version=([^,]+)', s).group(1) for s in decoder.libraries.values()
                        if s.startswith('Tripoli,') and 'Version=' in s), None)
        settings = {k.lstrip('_'): v for k, v in root.items()
                    if k not in ('__class__', '_SourceFileInfo', 'SourceFileInfo', 'ArrayList+_items', 'ArrayList+_size', 'ArrayList+_version')}
        typed = TripSettings(float(settings.get('ChauvenetsThreshold', 0.5)),
                             Decimal(settings.get('r18O_16O', '0.0020')),
                             bool(settings.get('AmOxideCorrected', False)),
                             bool(settings.get('AmFractionationCorrected', False)),
                             bool(settings.get('AmBaPO2andTIInterferenceCorrected', False)),
                             bool(settings.get('UseTracerCorrection', False)),
                             bool(settings.get('UseInterferenceCorrection', False)),
                             settings.get('CurrentTracer'), Decimal(settings.get('alphaPb', '0')),
                             settings.get('r238_235g'), settings.get('timeStamp'), settings)
        return TripProject(path, version, tuple(sources), typed, tuple(ratios), root)
    except (TypeError, ValueError, UnicodeError, struct.error, InvalidOperation, RecursionError) as error:
        if isinstance(error, UnsupportedFile):
            raise
        raise UnsupportedFile(f'{path.name}: malformed Tripoli project ({error})') from error
