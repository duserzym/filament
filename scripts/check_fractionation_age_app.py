"""Read-only synthetic P7 cross-check using the age app's existing environment.

No installation, lab-data access, file mutation, or network. Run from this
checkout's Python; stdout is a JSON audit record. The child disables bytecode.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import numpy as np

from rawtims.fractionation_preview import UComponents, preview_pb, preview_u
from rawtims.tracers import Estimate as E
from rawtims.tracers import Tracer

CHILD = r"""
import hashlib, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
from IDTIMS_UPbRPy import utils
alpha, sigma = utils.calc_FPb_2535(.303, .0006, .3, .0003)
aw = utils.calc_U_blank_AW(AWU238=238, U238_rel=137.88/138.88,
                         AWU235=235, U235_rel=1/138.88)
print(json.dumps({
    "pb_alpha": alpha, "pb_alpha_sigma": sigma,
    "pb206_ratio_no_stripping": utils.calc_Pb206s(10, alpha, 1, 0, 0),
    "u_alpha": utils.calc_FU(.6, 70, 1.2, .01, common_U238_U235=137.88),
    "u_blank_238_moles": utils.calc_U238b(.1, 0, aw, U238_rel=137.88/138.88)["U238b"],
    "source": str(Path(utils.__file__)),
    "source_sha256": hashlib.sha256(Path(utils.__file__).read_bytes()).hexdigest(),
}))
"""


def check(root):
    child = subprocess.run(
        [str(root / ".venv/bin/python"), "-B", "-c", CHILD, str(root)],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
    )
    age = json.loads(child.stdout)
    tracer = Tracer(
        "SYNTHETIC",
        1,
        "mixed 202-205-233-235",
        "SYNTHETIC",
        "2026-11-26",
        (
            ("r202_205t", E(0.3, 0.0003)),
            ("r233_235t", E(1.2)),
            ("r238_235t", E(0.01)),
            ("concU235t", E(1e-9)),
        ),
        "",
        "synthetic",
    )
    pb = preview_pb({"202Pb/205Pb": E(0.303, 0.0006), "206Pb/205Pb": E(10)}, tracer)
    measured = {"233U/235U": E(0.6), "238U/235U": E(70)}
    zero = UComponents(E(0), E(137.88), E(137.88), E(0.01), E(235), E(238))
    nonzero = UComponents(E(0.1), E(137.88), E(137.88), E(0.01), E(235), E(238))
    u_zero = preview_u(measured, tracer, zero)
    u_blank = preview_u(measured, tracer, nonzero)
    checks = {
        "pb_alpha": bool(
            np.isclose(pb["values"][0], age["pb_alpha"], rtol=1e-13, atol=0)
        ),
        "pb_alpha_sigma": bool(
            np.isclose(pb["sigma"][0], age["pb_alpha_sigma"], rtol=1e-13, atol=0)
        ),
        "pb_multiplier": bool(
            np.isclose(
                pb["values"][2], age["pb206_ratio_no_stripping"], rtol=1e-13, atol=0
            )
        ),
        "u_zero_blank": bool(
            np.isclose(u_zero["values"][0], age["u_alpha"], rtol=1e-13, atol=0)
        ),
    }
    assert all(checks.values()), checks
    return {
        "inputs": "Synthetic .303±.0006 / .3±.0003 Pb control; 206/205=10; U measured .6,70; tracer 1.2,.01,1e-9 mol/g; tracer .01g; blank 0 or .1pg; rb=rs=137.88; molar masses 235,238",
        "age_app": age,
        "checks": checks,
        "preview": {"pb": pb, "u_zero_blank": u_zero, "u_nonzero_blank": u_blank},
        "conventions": [
            "Same Pb alpha and independent alpha uncertainty; age calc_Pb206s includes tracer/blank subtraction, disabled here with zero amounts for multiplier comparison.",
            "U alpha agrees at zero blank. C# includes blank components in alpha; age calc_FU has no blank argument. Neither convention replaces the other.",
            "C# blank isotope moles divide separate mass fractions by each isotope molar mass. Age calc_U_blank_AW/calc_U238b use abundance-weighted atomic weight.",
            "Preview uncertainty is first-order J S Jᵀ over explicit primitives; age app also infers measured/tracer covariance from 238/233. GUI independence is an explicit assumption, not full age-engine uncertainty parity.",
            "Mean-level previews differ from C# per-cycle corrected means when alpha varies across cycles; no calibrated real chain validated here.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--age-root", type=Path, default=Path(os.environ.get("IDTIMS_UPBRPY_ROOT", "../IDTIMS_UPbRPy")).expanduser()
    )
    args = parser.parse_args()
    print(json.dumps(check(args.age_root), indent=2, allow_nan=False))
