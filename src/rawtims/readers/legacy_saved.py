"""Bounded inert saved-work inspection; no Java/.NET runtime or filesystem replay.

Java support is deliberately a scaffold for Session scalar fields, nulls,
strings and primitive arrays. Non-null analysis maps/custom serialized classes
require specimens and are refused. The source bytes are always retained.
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np

from rawtims.readers import UnsupportedFile
from rawtims.readers.trip import MAX_BYTES, decode_nrbf

SESSION_CLASS = 'org.cirdles.tripoli.sessions.Session'
SESSION_UID = 6597752272434171800


@dataclass
class _JavaDescriptor:
    name: str
    uid: int
    fields: tuple = ()


class _JavaData:
    def __init__(self, data):
        self.data, self.pos, self.handles = data, 0, []

    def take(self, n):
        if n < 0 or n > len(self.data)-self.pos:
            raise UnsupportedFile('Truncated Java serialization stream')
        start = self.pos
        self.pos += n
        return self.data[start:self.pos]

    def number(self, fmt):
        return struct.unpack('>'+fmt, self.take(struct.calcsize('>'+fmt)))[0]

    def utf(self, n=None):
        n = self.number('H') if n is None else n
        if not 0 <= n <= 1_000_000:
            raise UnsupportedFile('Java string length limit exceeded')
        # Java modified UTF-8 uses C0 80 for NUL and encodes surrogate pairs
        # as two code units. Reject other overlong sequences via UTF-8 decode.
        raw = self.take(n)
        if b'\0' in raw or any(b >= 0xf0 for b in raw):
            raise UnsupportedFile('Invalid Java modified UTF-8')
        raw = raw.replace(b'\xc0\x80', b'\0')
        text = raw.decode('utf-8', errors='surrogatepass')
        return text.encode('utf-16-be', errors='surrogatepass').decode('utf-16-be')

    def handle(self, value):
        if len(self.handles) >= 100_000:
            raise UnsupportedFile('Java handle limit exceeded')
        self.handles.append(value)
        return value

    def content(self, depth=0, *, descriptor=False):
        if depth > 64:
            raise UnsupportedFile('Java nesting limit exceeded')
        tag = self.number('B')
        if tag == 0x70:
            return None
        if tag == 0x71:
            index = self.number('I')-0x7e0000
            if not 0 <= index < len(self.handles):
                raise UnsupportedFile('Unknown Java reference')
            value = self.handles[index]
            if isinstance(value,_JavaDescriptor) and not descriptor:
                raise UnsupportedFile('Java class descriptor used as a data value')
            return value
        if tag in (0x74, 0x7c):
            return self.handle(self.utf(self.number('q') if tag == 0x7c else None))
        if tag == 0x72:
            if not descriptor:
                raise UnsupportedFile('Java class descriptor used as a data value')
            name, uid = self.utf(), self.number('q')
            if not ((name == SESSION_CLASS and uid == SESSION_UID) or name in ('[D','[I','[J','[Z','[B','[F','[S','[C')):
                raise UnsupportedFile(f'Java class/version requires a saved specimen: {name} ({uid})')
            schema = self.handle(_JavaDescriptor(name,uid))
            if self.number('B') != 2:
                raise UnsupportedFile('Custom/externalizable Java data is not supported')
            count = self.number('H')
            if count > 1000:
                raise UnsupportedFile('Java field limit exceeded')
            fields = []
            for _ in range(count):
                kind, field = chr(self.number('B')), self.utf()
                signature = self.content(depth+1) if kind in '[L' else None
                if kind not in 'BCDFIJSZ[L' or (kind in '[L' and not isinstance(signature,str)):
                    raise UnsupportedFile('Unknown Java field signature')
                if field in [f[1] for f in fields]:
                    raise UnsupportedFile('Duplicate Java field')
                fields.append((kind,field,signature))
            if self.number('B') != 0x78 or self.content(depth+1,descriptor=True) is not None:
                raise UnsupportedFile('Java class annotations/inheritance require a specimen')
            schema.fields = tuple(fields)
            return schema
        if tag in (0x73,0x75):
            schema = self.content(depth+1,descriptor=True)
            if not isinstance(schema,_JavaDescriptor):
                raise UnsupportedFile('Invalid Java class descriptor')
            name = schema.name
            if tag == 0x75:
                if name not in ('[D','[I','[J','[Z','[B','[F','[S','[C') or schema.fields:
                    raise UnsupportedFile('Unsupported Java array')
                array = self.handle([])
                count = self.number('i')
                if not 0 <= count <= 1_000_000:
                    raise UnsupportedFile('Java array length limit exceeded')
                array.extend(self.primitive(name[1]) for _ in range(count))
                return array
            if name != SESSION_CLASS:
                raise UnsupportedFile('Java root object must be Session')
            obj = self.handle({'__class__':name, '__uid__':schema.uid})
            for kind, field, _ in schema.fields:
                if field.startswith('__'):
                    raise UnsupportedFile('Reserved Java field name')
                obj[field] = self.content(depth+1) if kind in '[L' else self.primitive(kind)
            return obj
        raise UnsupportedFile(f'Unsupported Java serialization token 0x{tag:02x}')

    def primitive(self, kind):
        formats = {'B':'b','C':'H','D':'d','F':'f','I':'i','J':'q','S':'h','Z':'B'}
        value = self.number(formats[kind])
        if kind == 'Z':
            if value not in (0,1):
                raise UnsupportedFile('Invalid Java boolean')
            return bool(value)
        return chr(value) if kind == 'C' else value


def decode_java_session(data):
    """TripoliSerializer.java:64-78; Session.java:38-61 (00dc941).

    No ObjectInputStream, reflection, class loading, constructor, hooks or
    external paths are invoked. Unknown serialVersionUIDs are refused.
    """
    if len(data) > MAX_BYTES:
        raise UnsupportedFile('Java byte limit exceeded')
    parser = _JavaData(data)
    try:
        if parser.take(4) != b'\xac\xed\x00\x05':
            raise UnsupportedFile('Not a Java serialization stream')
        root = parser.content()
        if not isinstance(root,dict) or root.get('__class__') != SESSION_CLASS or parser.pos != len(data):
            raise UnsupportedFile('Java Session root missing or trailing data')
        return root
    except (UnicodeError, struct.error, RecursionError) as error:
        raise UnsupportedFile(f'Malformed Java stream: {error}') from error


def graph_document(root):
    """JSON-safe graph with explicit references; unknown members remain data."""
    nodes, seen = [], {}
    def encode(value):
        if isinstance(value, (dict,list,np.ndarray)):
            identity = id(value)
            if identity not in seen:
                index = len(nodes)
                seen[identity] = (index,value)  # retain temporary array lists against Python id reuse
                node = {'id':index}
                nodes.append(node)
                if isinstance(value, dict):
                    node.update(kind='object', members={k:encode(v) for k,v in value.items()})
                elif isinstance(value, np.ndarray):
                    node.update(kind='array', dtype=str(value.dtype), shape=list(value.shape), values=encode(value.tolist()))
                else:
                    node.update(kind='list', values=[encode(v) for v in value])
            return {'ref':seen[identity][0]}
        if isinstance(value,Decimal):
            return {'decimal':str(value)}
        if isinstance(value,float) and not np.isfinite(value):
            return {'float':str(value)}
        return value
    try:
        reference = encode(root)
    except RecursionError as error:
        raise UnsupportedFile('Saved-work graph depth limit exceeded') from error
    return {'root':reference,'nodes':nodes}


@dataclass(frozen=True)
class LegacyInspection:
    path: Path
    format: str
    source: bytes
    raw: object

    def document(self):
        return {'format':'rawtims inert legacy inspection', 'format_version':1, 'source_name':self.path.name,
                'source_format':self.format,'source_sha256':hashlib.sha256(self.source).hexdigest(),
                'source_hex':self.source.hex(), 'graph':graph_document(self.raw)}

    def json_text(self):
        return json.dumps(self.document(),ensure_ascii=True,allow_nan=False,indent=2)+'\n'


def inspect_saved(path):
    path = Path(path)
    with path.open('rb') as handle:
        data = handle.read(MAX_BYTES+1)
    if len(data) > MAX_BYTES:
        raise UnsupportedFile('Saved-work byte limit exceeded')
    if path.suffix.lower() == '.tripoli':
        root, fmt = decode_java_session(data), 'java-session-scaffold'
    elif path.suffix.lower() == '.triphis':
        root, fmt = decode_nrbf(data), 'dotnet-history'
        if not isinstance(root,dict) or root.get('__class__') not in ('Tripoli.TripoliHistoryFolderStandards','Tripoli.TripoliHistoryFolderGains'):
            raise UnsupportedFile('Not a known Tripoli history root')
    elif path.suffix.lower() == '.trip':
        root, fmt = decode_nrbf(data), 'dotnet-project'
        if not isinstance(root,dict) or root.get('__class__') != 'Tripoli.TripoliWorkProduct':
            raise UnsupportedFile('Not a known Tripoli project root')
    else:
        raise UnsupportedFile('Choose .trip, .triphis or Java .tripoli saved work')
    return LegacyInspection(path,fmt,data,root)
