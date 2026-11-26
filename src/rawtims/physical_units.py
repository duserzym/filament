"""Typed, opt-in physical intensity display; never modifies a Run or Analysis.

Java Tripoli 00dc941: TripoliCore/src/main/java/org/cirdles/tripoli/constants/
TripoliConstants.java:63-67,150-173 (cps <-> V/A); TripoliApp/src/main/java/org/
cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/
SpeciesIntensityAnalysisPlot.java:219-245 (gain display and unit selection).
Verified IsoprobeT raw values already include the selected gain. Do not apply
it twice. Retain that route's recorded vendor charge rather than replacing it
with Java's SI constant. No integrated-count conversion without dwell time.
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

JAVA_CHARGE_C = 1.602176634e-19
SCHEMA = "rawtims-intensity-display/1"


class IntensityUnit(StrEnum):
    COUNTS = "counts/s"
    VOLTS = "V"
    AMPS = "A"


@dataclass(frozen=True)
class DisplayCalibration:
    collector: str
    resistance_ohm: float
    recorded_gain: float
    gain_applied: bool
    charge_c: float
    parameters_sha256: str

    def __post_init__(self):
        if not self.collector or not self.parameters_sha256:
            raise ValueError(
                "Display calibration requires collector and parameter provenance"
            )
        if not all(
            np.isfinite(v) and v > 0
            for v in (self.resistance_ohm, self.recorded_gain, self.charge_c)
        ):
            raise ValueError(
                "Display resistance, gain and charge must be finite and positive"
            )


@dataclass(frozen=True)
class DisplayAvailability:
    source_unit: IntensityUnit | None
    calibration: DisplayCalibration | None
    reason: str

    @property
    def available(self):
        return self.calibration is not None


def display_availability(run, key) -> DisplayAvailability:
    """Only existing successfully decoded raw Faraday channels have verified units.

    No file reads, guesses from captions, acquisition rereads or parameter edits.
    The verified decoder mapping is used only to identify the display channel.
    """
    from rawtims.reduction_params import ReductionParameters
    from rawtims.reprocess import PB_INTENSITIES, U_INTENSITIES

    f = run.function(key)
    unavailable = lambda why: DisplayAvailability(None, None, why)
    if f.kind != "intensity":
        return unavailable("Physical conversion requires an intensity column.")
    params = run.reduction_parameters
    if (
        not isinstance(params, ReductionParameters)
        or params.route != "raw"
        or run.provenance.get("reduction_route") != "raw"
        or not run.provenance.get("raw_inputs")
        or run.provenance.get("reduction_parameters_sha256") != params.sha256
    ):
        return unavailable(
            "Verified raw-route units, collector mapping and resistor/gain provenance are unavailable for this run."
        )
    mapping = (
        PB_INTENSITIES
        if run.element == "Pb"
        else U_INTENSITIES
        if run.element == "U"
        else {}
    )
    if key not in mapping:
        return unavailable("This intensity has no verified raw collector mapping.")
    collector = mapping[key][1]
    if collector == "Multiplier":
        return unavailable(
            "Multiplier counts have no verified resistor-based V/A display calibration."
        )
    resistance, gain = (
        params.faraday_resistors_ohm.get(collector),
        params.faraday_gains.get(collector),
    )
    if resistance is None or gain is None:
        return unavailable(
            f"Verified resistor/gain metadata are missing for {collector}."
        )
    calibration = DisplayCalibration(
        collector,
        resistance,
        gain,
        params.apply_faraday_gains,
        params.electron_charge_c,
        params.sha256,
    )
    return DisplayAvailability(
        IntensityUnit.COUNTS if run.element == "Pb" else IntensityUnit.VOLTS,
        calibration,
        (
            "Display only; recorded gain was applied by the raw route."
            if params.apply_faraday_gains
            else "Display only; gain was explicitly disabled by the raw route."
        ),
    )


def convert_intensity(
    values,
    source: IntensityUnit,
    target: IntensityUnit,
    calibration: DisplayCalibration,
):
    """Return an independent array, preserving sign and missing values.

    Counts denotes count rate (cps), as in Java's physical conversion, not
    integrated counts. Gain is provenance only: it has already been applied
    (or explicitly disabled) by the existing raw route.
    """
    if not isinstance(calibration, DisplayCalibration):
        raise TypeError("Verified display calibration is required")
    source, target = IntensityUnit(source), IntensityUnit(target)
    a = np.array(values, dtype=float, copy=True)
    if source == target:
        return a
    amps_per_unit = {
        IntensityUnit.COUNTS: calibration.charge_c,
        IntensityUnit.VOLTS: 1 / calibration.resistance_ohm,
        IntensityUnit.AMPS: 1.0,
    }
    return a * (amps_per_unit[source] / amps_per_unit[target])


def display_intensity(run, key, target: IntensityUnit):
    status = display_availability(run, key)
    if not status.available:
        raise ValueError(status.reason)
    return convert_intensity(
        run.column(key), status.source_unit, target, status.calibration
    )
