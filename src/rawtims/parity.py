"""Read-only legacy project/workbook/clipboard parity audit.

All private values remain in memory. Reports contain only summary statistics,
counts and maximum differences, never cycles or masks. Audit views retain legacy
zero padding and per-ratio masks using the public session replay API. They are
not new raw acquisitions and are never exported as reduction inputs.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path

import numpy as np

from rawtims.analysis import Analysis, AnalysisSettings, replay
from rawtims.branding import APP_NAME
from rawtims.model import Run
from rawtims.oxide import correct
from rawtims.readers import UnsupportedFile, open_run
from rawtims.readers._xls import open_xls
from rawtims.readers.functions import build_functions
from rawtims.readers.trip import MAX_BYTES, TripProject, read_trip
from rawtims.stats import describe

DEFAULT_DRIVE = Path('~/My Drive/Research/Lab_visits/2026_Boise/Example_Isoprobe_data')
DEFAULT_SHEETS = Path('~/My Drive/Grenville_TIMS/Egypt')
MEAN_RTOL = 2e-12
CYCLE_RTOL = 2e-13
# Named evidence exceptions are content pinned. A new project cannot inherit one
# just because its filename happens to match a known acquisition.
KNOWN_EXCEPTIONS: dict[str, str] = {
    'e7b7be22deb8c5e3e56a20f62a2c245a2a14151ab084e25c13e7ad69e781b3b4':
        'earlier KG5 z4 Pb acquisition; the sheet matches the 57-cycle rerun',
    '1b3a20ed4cb1423ba53ef00dab9b0f1971506721860cbf0d1b83e3a930b2aaac':
        'earlier KG5 z7 Pb acquisition; the sheet matches the 150-cycle rerun',
    '9532cb892fb73f4bc8d43c172b4ad077fa4bbb989a4fb3c931eb8364839e0ae3':
        'source workbook absent: B1609_F12_GA9683326 z3 Pb-56377.xls',
}


def drive_path() -> Path:
    return Path(os.environ.get(APP_NAME.upper() + '_BOISE_EXAMPLES', DEFAULT_DRIVE))


def sheets_path() -> Path:
    return Path(os.environ.get(APP_NAME.upper() + '_BSU_SHEETS', DEFAULT_SHEETS))


@dataclass(frozen=True)
class Check:
    quantity: str
    reference: float
    actual: float
    tolerance: float
    cause: str = ''
    exception: str = ''

    @property
    def difference(self):
        return self.actual - self.reference

    @property
    def relative(self):
        return abs(self.difference / self.reference) if self.reference else (0.0 if self.actual == 0 else math.inf)

    @property
    def passed(self):
        return (math.isnan(self.reference) and math.isnan(self.actual)) or abs(self.difference) <= self.tolerance


@dataclass
class ProjectResult:
    project: TripProject
    digest: str
    label: str
    sources: list[str]
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    analysis: Analysis | None = field(default=None, repr=False)
    sheet_matches: int = 0
    parse_seconds: float = 0.0

    @property
    def failures(self):
        return [c for c in self.checks if not c.passed and not c.exception]

    @property
    def accounted(self):
        return not self.failures and all(issue == KNOWN_EXCEPTIONS.get(self.digest) for issue in self.issues)

    @property
    def status(self):
        if not self.accounted:
            return 'FAIL'
        if self.issues:
            return 'UNAVAILABLE (documented source)'
        if any(c.exception for c in self.checks):
            return 'PASS project; alternate sheet acquisition'
        return 'PASS'


@dataclass
class ParityResult:
    projects: list[ProjectResult]
    seconds: float
    workbook_count: int
    sheet_count: int
    facts: list[str]

    @property
    def passed(self):
        return all(p.accounted for p in self.projects)


def distinct_projects(folder: Path) -> list[tuple[Path, str]]:
    """Content deduplication, preferring top-level files over nested copies."""
    seen = set()
    result = []
    for path in sorted(folder.rglob('*.trip'), key=lambda p: (len(p.parts), str(p))):
        with path.open('rb') as handle:
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise UnsupportedFile(f'{path.name}: NRBF byte limit exceeded')
        digest = sha256(data).hexdigest()
        if digest not in seen:
            seen.add(digest)
            result.append((path, digest))
    return result


def legacy_statistics(signed) -> dict[str, float]:
    """Independent reference for RawRatio.CalcStats, including its rounding.

    Scalar accumulation deliberately models the legacy numerical algorithm;
    the production engine keeps its more stable centered variance.
    """
    values = [float(x) for x in signed if x > 0]
    n = len(values)
    total = sum(values)
    squares = sum(x * x for x in values)
    mean = total / n if n else 0.0
    variance = (squares - total * total / n) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(variance) if variance >= 0 else math.nan
    se = sd / math.sqrt(n) if n else 0.0
    return {'mean': mean, 'sd': sd, 'se': se, 'se_pct': 100 * se / mean if mean else 0.0,
            'n_used': n, 'n_rejected': int(np.count_nonzero(np.asarray(signed) < 0)),
            'n_missing': len(signed) - int(np.count_nonzero(signed)), 'n_total': len(signed),
            'min': min([1e7, *values]), 'max': max([0.0, *values])}


def numeric_tolerance(reference: float, metric: str, values, *, clipboard=False) -> float:
    """Absolute bound for double round-off plus legacy variance cancellation.

    gamma_n bounds each naive sum. A factor 8 covers the two sums, squaring,
    subtraction and propagation into SD/SE. This scales with n and beam CV,
    rather than relaxing all statistics to a data-fitted relative threshold.
    Clipboard adds half a unit in the eighth significant digit (C# E7).
    """
    if metric.startswith('n_') or metric in ('AllCount', 'AllMissing'):
        return 0.0
    tol = MEAN_RTOL * abs(reference)
    v = np.asarray(values)
    v = np.abs(v[v != 0])
    if metric in ('sd', 'se', 'se_pct', 'AllStdDev', 'AllStdErr', 'AllPctStdErr') and len(v) > 1:
        mean = float(v.mean())
        variance = float(v.var(ddof=1))
        gamma = len(v) * np.finfo(float).eps / (1 - len(v) * np.finfo(float).eps)
        if variance > 0:
            tol += abs(reference) * 8 * gamma * (float(np.mean(v * v)) + mean * mean) / variance
    if clipboard and reference:
        tol += 0.5 * 10 ** (math.floor(math.log10(abs(reference))) - 7)
    return tol


def _add(result, quantity, reference, actual, metric, values, *, clipboard=False, exception=''):
    tol = numeric_tolerance(reference, metric, values, clipboard=clipboard)
    diff = abs(actual - reference)
    cause = ''
    if diff > MEAN_RTOL * abs(reference):
        cause = ('statistic definition: E7 clipboard rounding and legacy cancellation' if clipboard else
                 'statistic definition: naive legacy sum-of-squares cancellation')
    if exception and diff > tol:
        cause = ('Tripoli is the odd one out: KG5/z7 labels conflict with the GA9683326 source; workbook absent'
                 if exception.startswith('source workbook absent') else
                 'Tripoli settings: different acquisition from the pasted sheet (matched rerun verified separately)')
    result.checks.append(Check(quantity, float(reference), float(actual), tol, cause, exception if diff > tol else ''))


def _view(run: Run, project: TripProject) -> Run:
    """An in-memory audit view, independently built from workbook columns.

    Legacy substitutes corrected inputs in place, inserts one derived ratio,
    and pads incomplete U blocks with zeros. Reproduce that layout explicitly;
    never extend the raw reader's rows or recompute its pass-through columns.
    """
    n = len(project.ratios[0].values)
    if run.n_cycles > n:
        raise ValueError('project is shorter than its source: alignment requires investigation')
    corrected = {}
    if project.settings.get('AmOxideCorrected'):
        c233, c238, c238_233 = correct(run.column('265/267'), run.column('270/267'), float(project.settings['r18O_16O']))
        corrected = {'238/235 OxideCor:(270/267)': c238, '233/235 OxideCor:(265/267)': c233,
                     '238/233 OxideCor:(238/235\\233/235)': c238_233}
    columns = []
    for ratio in project.ratios:
        if ratio.settings.get('fractionationCorrected'):
            raise ValueError('fractionation-corrected project requires an explicit comparison implementation')
        if len(ratio.values) != n:
            raise ValueError('project ratios have unequal lengths')
        if ratio.name in run.keys:
            col = run.column(ratio.name)
        elif ratio.name in corrected:
            col = corrected[ratio.name]
        else:
            raise ValueError(f'no workbook/oxide input for {ratio.name}')
        columns.append(np.pad(col, (0, n - len(col))))
    values = np.column_stack(columns)
    functions = build_functions([r.name for r in project.ratios])
    cpbs = {r.cycles_per_block for r in project.ratios}
    if len(cpbs) != 1 or not next(iter(cpbs)):
        raise ValueError('ambiguous project block layout')
    cpb = next(iter(cpbs))
    if cpb != run.metadata.cycles_per_block:
        raise ValueError('project and workbook block sizes differ')
    cycle = np.arange(1, n + 1)
    return replace(run, functions=functions, values=values, invalid=~np.isfinite(values) | (values <= 0),
                   cycle=cycle, block=(cycle - 1) // cpb + 1,
                   time=np.pad(run.time, (0, n - run.n_cycles), constant_values=np.nan))


def replay_project(run: Run, project: TripProject, *, workbook: bool = False) -> Analysis:
    """Restore exact legacy per-ratio masks via public, strict history replay.

    Like old sessions, these masks deliberately remain per ratio. Do not call
    shared-mask editing commands here: doing so would change the reference.
    """
    base = AnalysisSettings()
    history = []
    for name, value in [('r18', float(project.settings['r18O_16O'])),
                        ('chauvenet_probability', float(project.settings['ChauvenetsThreshold']))]:
        history.append({'op': 'set_setting', 'name': name, 'old': getattr(base, name), 'new': value})
    pairs = ([(r, r.name) for r in project.ratios if r.name in run.keys] if workbook else
             list(zip(project.ratios, run.keys, strict=True)))
    if workbook:
        for r in project.ratios:
            if r.name not in run.keys:
                if r.settings.get("active", False) or "OxideCor:" not in r.name:
                    raise ValueError(f"project function absent from workbook: {r.name}")
                continue  # inactive legacy oxide comparison columns are not acquisition functions
            values = np.abs(r.values)
            if len(values) < run.n_cycles or np.any(values[run.n_cycles:] != 0):
                raise ValueError("project/workbook row correspondence differs")
            if not np.allclose(values[:run.n_cycles], run.column(r.name), rtol=CYCLE_RTOL, atol=0):
                raise ValueError(f"project/source values differ: {r.name}; locate the exact source acquisition")
    label = f"Imported from Tripoli project {project.path.name}"
    for op in history:
        op["label"] = label
    for r, key in pairs:
        rows = np.flatnonzero(r.values[:run.n_cycles] < 0).tolist()
        if rows:
            history.append({'op': 'toggle_cycles', 'cycles': rows, 'keys': [key], 'include': False,
                            'changed': [[row, key] for row in rows], 'label': label})
        if r.block_flags is not None:
            raise ValueError('independent block flags need format-specific interpretation')
    analysis = replay(run, history, strict=True)
    if workbook:
        analysis.remember_legacy_masks()
    return analysis


def read_sheet_references(folder: Path) -> dict[tuple[str, str, str], tuple[str, float, float]]:
    """Locate fraction/header labels and keep only the pasted means/errors."""
    refs = {}
    for sample in ('KD33', 'KG5'):
        path = folder / f'{sample}_ BSULab_UPbR24XML.xls'
        if not path.is_file():
            continue
        book = open_xls(file_contents=path.read_bytes(), on_demand=True)
        try:
            sheet = book.sheet_by_name('Raw Data Input')
            row_id = next(row for row in range(sheet.nrows) if str(sheet.cell_value(row, 0)).startswith('Fraction ID'))
            for col in range(4, sheet.ncols):
                frac = sheet.cell_value(row_id, col)
                if frac not in {f'z{n}' for n in range(1, 8)}:
                    continue
                for row in range(row_id + 1, min(48, sheet.nrows - 2)):
                    header = sheet.cell_value(row, col)
                    if isinstance(header, str) and '  (Mean, %StdErr)' in header:
                        name = header.split('  (Mean, %StdErr)')[0]
                        mean, se = sheet.cell_value(row + 1, col), sheet.cell_value(row + 2, col)
                        if isinstance(mean, (float, int)) and isinstance(se, (float, int)):
                            refs[sample, frac, name] = (path.name, float(mean), float(se))
        finally:
            book.release_resources()
    return refs


def _compare_sheet(result, refs):
    project = result.project
    sample, frac = project.settings['sampleName'], project.settings['fractionName']
    elem = project.settings['ratioType']
    for (s, f, name), (filename, mean, se) in refs.items():
        if (s, f) != (sample, frac) or (name.startswith(('238/', '233/'))) != (elem == 'U'):
            continue
        candidates = [r for r in project.ratios if r.name == name]
        exact = bool(candidates)
        if not candidates:
            # The earlier Pb acquisition uses different method/function names.
            # Compare the same masses and explicitly record that acquisition.
            mass_pair = name.split()[0]
            candidates = [r for r in project.ratios if r.name == mass_pair + ' D']
        if not candidates:
            result.issues.append(f'sheet function not found: {name}')
            continue
        ratio = candidates[0]
        idx = next(i for i, r in enumerate(project.ratios) if r is ratio)
        if result.analysis is not None:
            stat = result.analysis.stats(result.analysis.keys[idx])
        else:
            stat = describe(np.abs(ratio.values), ratio.accepted)
        exception = KNOWN_EXCEPTIONS.get(result.digest, '')
        _add(result, f'sheet {name} mean', mean, stat.mean, 'mean', ratio.values[ratio.accepted], clipboard=True, exception=exception)
        _add(result, f'sheet {name} 1σ %SE', se, stat.se_pct, 'se_pct', ratio.values[ratio.accepted], clipboard=True, exception=exception)
        if exact and all(c.passed for c in result.checks[-2:]):
            result.sheet_matches += 1


def compare_project(project, digest, folder, runs, refs, parse_seconds=0.0):
    result = ProjectResult(project, digest, str(project.path.relative_to(folder)),
                           [s.name for s in project.sources], parse_seconds=parse_seconds)
    if len(project.sources) != 1:
        result.issues.append('project does not identify exactly one source; investigate concatenation')
        return result
    source = project.sources[0].name
    run = runs.get(source)
    if run is None:
        result.issues.append('source workbook absent: ' + source)
        result.notes.append('SourceFileInfo names this acquisition; no concatenated source list is serialized. Project labels alone do not establish sample identity.')
        result.notes.append('Internal checks below use the saved project magnitudes directly; there is no workbook-backed Analysis for this project. They do not establish reader parity.')
    else:
        try:
            view = _view(run, project)
            result.analysis = replay_project(view, project)
            padded = view.n_cycles - run.n_cycles
            if padded:
                result.notes.append(f'Legacy pads the last block with {padded} zero/missing cycles; the raw workbook has {run.n_cycles} measured cycles. Audit view preserves these zeros for total/missing counts.')
            for i, ratio in enumerate(project.ratios):
                values = view.values[:, i]
                ref = np.abs(ratio.values)
                delta = float(np.max(np.abs(values - ref)))
                scale = float(np.max(ref))
                result.checks.append(Check(f'{ratio.name}: cycle max absolute difference', 0.0, delta, CYCLE_RTOL * scale,
                                           'oxide correction (decimal versus float64)' if 'OxideCor:' in ratio.name else 'reader bug' if delta else ''))
                if not np.array_equal(result.analysis.included_for(view.keys[i]), ratio.accepted):
                    result.issues.append('mask interpretation differs: ' + ratio.name)
        except (ValueError, KeyError) as error:
            result.issues.append(str(error))
    for i, ratio in enumerate(project.ratios):
        if result.analysis is None:
            values = np.abs(ratio.values)
        else:
            values = result.analysis.column(result.analysis.keys[i])
        original = describe(values, values > 0)
        pairs = {'AllMean': original.mean, 'AllStdDev': original.sd, 'AllStdErr': original.se,
                 'AllPctStdErr': original.se_pct, 'AllCount': original.n_used,
                 'AllMissing': len(values) - original.n_used,
                 'AllMin': float(min([1e7, *values[values > 0]])), 'AllMax': float(max([0.0, *values]))}
        for metric, ref in ratio.statistics.items():
            if metric in pairs:
                _add(result, f'{ratio.name}: stored {metric}', ref, pairs[metric], metric, values)
        ref_stats = legacy_statistics(ratio.values)
        if result.analysis is None:
            stat = describe(values, ratio.accepted)
        else:
            stat = result.analysis.stats(result.analysis.keys[i])
        actual = {'mean': stat.mean, 'sd': stat.sd, 'se': stat.se, 'se_pct': stat.se_pct,
                  'n_used': stat.n_used, 'n_total': stat.n_total,
                  'n_missing': int(np.count_nonzero(values == 0)),
                  'n_rejected': stat.n_total - stat.n_used - int(np.count_nonzero(values == 0))}
        for metric, got in actual.items():
            _add(result, f'{ratio.name}: reconstructed accepted {metric}', ref_stats[metric], got,
                 metric, ratio.values[ratio.accepted])
        if ratio.settings.get('StatsDetailDisplay') == 3:
            _add(result, f'{ratio.name}: reconstructed accepted 2σ SD (plot band)', 2 * ref_stats['sd'],
                 2 * stat.sd, 'sd', ratio.values[ratio.accepted])
    if run is not None and run.element == 'U':
        # Independent check of the already corrected workbook functions, using a
        # second ratio path because the column named 270/267 contains intensity.
        c233, c238, c238_233 = correct(run.column('265/267'), run.column('270/265') * run.column('265/267'), 0.00206)
        for name, expected in zip(('233/235 oxide R18 0.00206', '238/235 oxide R18 0.00206', '238/233 oxide'), (c233, c238, c238_233)):
            delta = float(np.max(np.abs(run.column(name) - expected)))
            result.checks.append(Check(f'{name}: independent oxide cycle max absolute difference', 0.0, delta,
                                       CYCLE_RTOL * float(np.max(expected)), 'oxide correction: independent 270/265 path'))
        if not np.array_equal(run.column('270/267'), run.column('270')):
            result.issues.append('270/267 intensity alias observation changed')
        result.notes.append('Workbook 270/267 exactly equals the 270 intensity. Named 0.00206 functions agree with the legacy/ET_Redux formula using 270/265 × 265/267; Tripoli also corrected the mislabeled 270/267 at 0.0020 in inactive OxideCor functions. Active clipboard functions are the workbook 0.00206 columns.')
    _compare_sheet(result, refs)
    return result


def workbook_facts(paths):
    """Summarize tuning/baseline metadata, without per-cycle output."""
    dead_times, gains, baseline = set(), set(), set()
    for path in paths:
        book = open_xls(file_contents=path.read_bytes(), on_demand=True)
        try:
            tune = book.sheet_by_name('TUNING')
            labels = {str(tune.cell_value(r, 0)).strip(): r for r in range(min(15, tune.nrows))}
            collector = labels.get('Collector:')
            if collector is not None:
                for col in range(1, tune.ncols):
                    if tune.cell_value(collector, col) == 'Multiplier':
                        dead_times.add(tune.cell_value(labels['DT (ns):'], col))
                        gains.add(tune.cell_value(labels['Gain:'], col))
            from rawtims.readers.ionvantage import read_ctrl
            ctrl = read_ctrl(book.sheet_by_name('CTRL'))
            baseline.add(tuple(ctrl.get(k) for k in ('Apply Baselines', 'Correct for STDBL', 'Correct for BLKBL')))
        finally:
            book.release_resources()
    return [f'TUNING Multiplier (Daly) dead time: {sorted(dead_times)} ns; recorded Multiplier gain: {sorted(gains)}.',
            f'CTRL (Apply Baselines, Correct for STDBL, Correct for BLKBL): {sorted(baseline)}. CYCLE values are already processed; no extra dead-time/baseline/gain correction was applied by this audit.']


def run_parity(folder: Path | None = None, sheets: Path | None = None) -> ParityResult:
    start = time.perf_counter()
    folder, sheets = Path(folder or drive_path()), Path(sheets or sheets_path())
    paths = sorted(folder.glob('*.xls'))
    runs = {p.name: open_run(p) for p in paths}
    refs = read_sheet_references(sheets)
    projects = []
    for path, digest in distinct_projects(folder):
        t = time.perf_counter()
        project = read_trip(path)
        parsed = time.perf_counter() - t
        projects.append(compare_project(project, digest, folder, runs, refs, parsed))
    facts = workbook_facts(paths)
    return ParityResult(projects, time.perf_counter() - start, len(runs), len(refs), facts)


def _number(value):
    return f'{value:.12g}'


def _escape(text):
    return str(text).replace('|', '&#124;').replace('<', '&lt;').replace('>', '&gt;')


def render_report(audit: ParityResult) -> str:
    lines = ['# Legacy Tripoli parity on the real BSU data', '',
             (f'Generated by `scripts/tripoli_parity.py`: {len(audit.projects)} distinct content hashes, '
             f'{audit.workbook_count} top-level workbooks, {audit.sheet_count} pasted ratio references. '
             f'Elapsed {audit.seconds:.3f} s; slowest project parse {max(p.parse_seconds for p in audit.projects):.4f} s.'), '',
             '## Method and limits', '',
             ('Drive inputs were opened read-only. No raw files, cycle values or masks are embedded in this report or repository. '
             'Projects are deduplicated by SHA-256 (equivalent distinct set to SHA-1 here); top-level copies take precedence. '
             'SourceFileInfo, never the project filename, chooses the workbook. No project in this set serializes a combined-run source list. '
             'The unrelated source in KG5_z7_Pb.trip is unavailable, so its raw-reader parity cannot be claimed.'), '',
             ('The safe MS-NRBF parser only constructs inert data. It follows [Microsoft MS-NRBF](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-nrbf/5acd9dc4-1439-433a-8d53-eb2922a142d8). '
             'Field/statistical interpretations were checked against OGTripoli source/RawRatio.cs (GetObjectData, Ratios setter, CalcStats, SetBlockOutliers), TripoliWorkProduct.cs, RunParameters.cs and forms/frmRatioGraph.cs. '
             'These are independent implementations of the format and numerical methods.'), '',
             ('The actual streams are Tripoli 4.10.0.3. Positive signed Ratios are accepted; negative values are hand/rule discards, zero means missing. '
             'ActiveRatiosMap is a display cache. No AcceptedFlags or independent block flags are stored: block rejection changes signs too. '
             'Audit views add only verified zero padding to incomplete U blocks, and independently compute the in-place legacy oxide functions from workbook inputs. '
             'The public Analysis/replay API restores settings and individual ratio rejections as strict, undoable session history; no shared-mask union or new automatic rule is applied.'), '',
             ('**Stored statistics are All* original/unfiltered statistics. Accepted statistics and block means are not serialized.** '
             '“Reconstructed accepted” rows compare Analysis against an independent scalar implementation of legacy CalcStats on the signed project data. '
             'They are algorithm checks, not independent stored results. The BSU pasted means/1σ %SE provide the independent accepted-statistic reference. '
             'StatsDetailDisplay=3 plots the mean ±2 SD band, alongside ±1 SD and ±1 SE. Reconstructed 2σ SD bands are explicitly labeled; this setting does not double clipboard %SE. No stored per-block statistics exist to validate in these files.'), '',
             '## Tolerances', '',
             ('Raw cycle comparisons use maximum absolute difference ≤ 2e-13 × maximum magnitude; ordinary source columns match exactly, while Decimal oxide arithmetic can round differently from float64. '
             'Means use 2e-12 relative tolerance, counts are exact. SD/SE/%SE additionally allow the standard naive-summation error bound: '
             '8 γ_n (mean(x²)+mean(x)²)/sample_variance relative, with γ_n=n ε/(1−n ε), ε=float64 epsilon. '
             'This accounts for cancellation in legacy (Σx²−(Σx)²/n)/(n−1); the engine retains stable centered variance. '
             'The bound depends on n and coefficient of variation, not a fitted global cutoff. '
             'Clipboard comparisons add half a unit in the eighth significant digit, because C# E7 has eight significant digits. '
             'Numerical round-off within these bounds is classified as statistic definition/clipboard precision; it is not an engine defect.'), '',
             '## Findings for Phase 2', '']
    lines += ['- ' + fact for fact in audit.facts]
    lines += ['- All 14 U projects record r18=0.0020, AmOxideCorrected=true, and separate inactive OxideCor functions. All retain the active workbook 0.00206 functions used in the pasted sheets. The active functions must continue to pass through without a second correction.',
              '- All projects record Chauvenet threshold 0.5. Of 145 active functions, 144 have HandleOutliersFlag=1 (2σ); KG5 z7 U 238/233 oxide has Manual=0. Masks differ per ratio. A final mask does not establish the order of hand edits or the number of rule passes. Legacy 2σ is one pass on currently accepted positive values; legacy Chauvenet repeatedly rejects the worst point and recomputes (unlike Java one-pass/minimum-20 Chauvenet). This audit replays selections, not rejection algorithms.',
              '- No project records applied fractionation or BaPO2/Tl correction; tracer/interference-use flags are false and alphaPb is zero. Capability flags can be true without an applied correction.',
              '- Every U workbook has 270/267 equal to 270 intensity. Independent checks establish that the named 0.00206 columns use the correct physical ratio path through 270/265. The inactive legacy OxideCor functions reproduce correction of the mislabeled intensity at 0.0020; those are not the pasted ratios. This is an upstream workbook/input issue, not evidence to change the engine oxide formula.',
              '- The two distinct nested Pb projects are reruns: KG5 z4 (57 cycles) and KG5 z7 (150 cycles). Their pasted means/errors match. The earlier top-level projects use 19 and 38 cycles respectively; their sheet discrepancies reflect different acquisitions, not a failed raw reader.',
              '- KG5_z7_Pb.trip stores B1609_F12_GA9683326 z3 Pb-56377.xls as its only source (228 cycles, 32 functions), despite KG5/z7 labels. That workbook is absent. There is no evidence in its serialized source information for a concatenation of the two KG5 runs. Its internal statistics can be checked, but its workbook parity and identity remain unresolved.', '',
              '## Summary', '',
              '| Project | Source workbook | Checks | Status | Worst finite relative difference |',
              '|---|---|---:|---|---:|']
    for p in audit.projects:
        worst = max((c.relative for c in p.checks if math.isfinite(c.relative)), default=0)
        lines.append(f'| {_escape(p.label)} | {_escape(", ".join(p.sources))} | {len(p.checks)} | {p.status} | {worst:.6g} |')
    matched = sum(p.sheet_matches for p in audit.projects)
    lines += ['', (f'{sum(not p.issues and not p.failures for p in audit.projects)}/{len(audit.projects)} projects have workbook-backed parity; '
              f'{sum(bool(p.issues) for p in audit.projects)} has an unavailable source. '
              f'{matched} exact-name pasted ratio pairs match (mean and error); alternate acquisitions are shown explicitly below. '
              'A documented exception is not a numerical pass or a substitute for a missing input.'), '', '## Per-project checks', '']
    for p in audit.projects:
        lines += [f'<details><summary>{_escape(p.label)} — {p.status}</summary>', '',
                  f'Content SHA-256: `{p.digest}`. Source: `{_escape(", ".join(p.sources))}`.', '']
        lines += ['- ' + note for note in p.notes]
        lines += ['- **Unresolved:** ' + issue for issue in p.issues]
        lines += ['', '| Quantity | Tripoli / sheet | ' + APP_NAME + ' | Difference | Relative difference | Pass | Cause |',
                  '|---|---:|---:|---:|---:|---|---|']
        for c in p.checks:
            relative = '— (zero reference)' if not math.isfinite(c.relative) else f'{c.relative:.6g}'
            passed = 'yes' if c.passed else 'EXCEPTION' if c.exception else '**FAIL**'
            lines.append(f'| {_escape(c.quantity)} | {_number(c.reference)} | {_number(c.actual)} | {_number(c.difference)} | {relative} | {passed} | {_escape(c.cause)} |')
        lines += ['', '</details>', '']
    return '\n'.join(lines)
