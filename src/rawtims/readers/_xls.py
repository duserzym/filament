"""Open legacy BIFF8 ``.xls`` workbooks with xlrd, without evaluating defined names.

Why this exists
---------------
xlrd 2.0.2 fails on every IonVantage workbook we have (all four vendored
fixtures): ``xlrd.open_workbook`` raises ``AssertionError`` from
``formula.evaluate_name_formula`` while it evaluates the workbook's defined
names (``Book.names_epilogue``), which happens during the global-records
pass, before any sheet is read. The name records IonVantage writes (macro and
print-area names) have formula stacks xlrd's evaluator does not understand.

The readers never use defined names; they read cell values only. So the fix
skips name-formula evaluation and nothing else:

* :class:`_NoNameFormulaBook` subclasses ``xlrd.book.Book`` and marks every
  name record as already evaluated (result ``None``) before running the stock
  ``names_epilogue``, which then builds its name maps without calling the
  evaluator. Every other parsing step is xlrd's own.
* The override is per instance. No xlrd module attribute is replaced, so there
  is no global monkeypatch to undo, other xlrd users in the process are
  unaffected, and concurrent opens in several threads are safe (each open has
  its own Book object).
* :func:`open_xls` repeats the few steps of ``xlrd.book.open_workbook_xls``
  (load, BIFF version check, parse globals, read sheets, release) with that
  Book class. xlrd is pinned to 2.0.2 in ``pyproject.toml`` because this uses
  those internal method names; ``tests/test_readers_ionvantage.py`` fails
  loudly if a different xlrd changes them.

Alternatives considered: ``python-calamine`` (Rust, reads these files in
other projects) would add a compiled dependency to freeze with PyInstaller on
macOS arm64 and Windows and was not available offline here; a global
monkeypatch of ``xlrd.formula.evaluate_name_formula`` would leak into other
code and is not thread-safe while active.
"""

from __future__ import annotations

import io

from xlrd import XLRDError
from xlrd.biffh import XL_WORKBOOK_GLOBALS
from xlrd.book import Book

OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SUPPORTED_BIFF = (80,)  # BIFF8, Excel 97-2003; IonVantage writes this


class _NoNameFormulaBook(Book):
    """An xlrd Book that keeps defined-name records but never evaluates their formulas."""

    def names_epilogue(self):
        for name in self.name_obj_list:
            name.evaluated = 1
            name.result = None
        super().names_epilogue()


def open_xls(path: str | None = None, *, file_contents: bytes | None = None, on_demand: bool = False) -> Book:
    """Open a BIFF8 workbook. With ``on_demand`` only the globals are parsed until a sheet is requested.

    The caller must call ``release_resources()`` on an on-demand book when done.
    """
    book = _NoNameFormulaBook()
    sink = io.StringIO()  # xlrd's warnings go here, not to stdout
    try:
        book.biff2_8_load(filename=path, file_contents=file_contents, logfile=sink, on_demand=on_demand)
        version = book.getbof(XL_WORKBOOK_GLOBALS)
        if version not in _SUPPORTED_BIFF:
            raise XLRDError(f"unsupported BIFF version {version} (only Excel 97-2003 BIFF8 workbooks are read)")
        book.biff_version = version
        book.parse_globals()
        book._sheet_list = [None for _ in book._sheet_names]
        if not on_demand:
            book.get_sheets()
        book.nsheets = len(book._sheet_list)
    except BaseException:
        book.release_resources()
        raise
    if not on_demand:
        book.release_resources()
    return book
