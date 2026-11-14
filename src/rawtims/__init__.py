"""Raw ID-TIMS data review engine (Qt-free).

The engine reads IsotopX IsoprobeT run files, keeps the cycle rejection
history, computes statistics and corrections, and writes the
``idtims-fractions/1`` contract. It imports no Qt, HTTP or database code.

Import names from their defining submodule (``from rawtims.branding import
APP_NAME``). The package deliberately has no lazy ``__getattr__``.
"""

from __future__ import annotations

from rawtims._version import package_version

__version__ = package_version()
