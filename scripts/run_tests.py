#!/usr/bin/env python3
"""Select affected tests and schedule isolated pytest processes without xdist.

Adapted from UPbRPy commit f8c561f, scripts/run_tests.py, on 2026-11-14.
Changes: source folders are src/ (packages rawtims, rawtims_gui) and scripts/;
module names drop the src/ prefix; environment variables use the RAWTIMS_
prefix; the cache folder name comes from rawtims.branding; PYTHONPATH is
removed from the test environment so packages on the user's path (for example
UPbRPy's GUI) cannot leak into the tests; files expected to take under 5 s are
never sharded; a module-level change selects every test that executed the
module (Studio's runner skips modules without functions, such as branding),
and a whole-file change also selects the file's static importers.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from rawtims.branding import CACHE_DIR_NAME

ROOT = Path(__file__).resolve().parents[1]
DURATIONS = ROOT / "tests/durations.json"
LAST_FULL = Path(tempfile.gettempdir()) / (f"{CACHE_DIR_NAME}-last-full-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12] + ".json")
DURATION_LINE = re.compile(r"^\s*([\d.]+)s\s+(?:setup|call|teardown)\s+(tests/[^:]+)::")


@dataclass(frozen=True)
class Chunk:
    paths: tuple[str, ...]
    seconds: float
    exclude_slow: bool = False
    shard_index: int = 0
    shard_count: int = 1
    isolated: bool = False

    def flags(self) -> list[str]:
        flags = ["-m", "not slow"] if self.exclude_slow else []
        if self.shard_count > 1:
            flags += ["--shard-index", str(self.shard_index), "--shard-count", str(self.shard_count)]
        return flags


def test_files(root: Path = ROOT) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in (root / "tests").rglob("test_*.py"))


def module_name(rel: Path) -> str:
    """Dotted import name of a repository path; src/ is a layout folder, not a package."""
    parts = rel.with_suffix("").parts
    return ".".join(parts[1:] if parts[0] == "src" else parts)


def import_graph(root: Path = ROOT, changed: list[str] | tuple[str, ...] = ()) -> dict[str, set[str]]:
    """Resolve local imports, including package initializers and test helpers."""
    paths = sorted(p for folder in ("tests", "src", "scripts") for p in (root / folder).rglob("*.py"))
    modules = {}
    # Retain import targets deleted in this diff so their importers still run.
    candidates = [*paths, *(root / p for p in changed if p.endswith(".py") and p.split("/")[0] in {"tests", "src", "scripts"})]
    for path in candidates:
        rel = path.relative_to(root)
        name = module_name(rel)
        if name.endswith(".__init__"):
            name = name.removesuffix(".__init__")
        modules[name] = rel.as_posix()
        if rel.parts[0] == "tests":
            modules.setdefault(path.stem, rel.as_posix())
    graph = {}
    for path in paths:
        rel = path.relative_to(root)
        own = module_name(rel)
        package = own.rsplit(".", 1)[0] if path.name != "__init__.py" else own.removesuffix(".__init__")
        deps = set()
        # Syntax errors should fail selection visibly, never silently omit tests.
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(rel))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")[:len(package.split(".")) - node.level + 1]
                    prefix = ".".join(base + ([node.module] if node.module else []))
                else:
                    prefix = node.module or ""
                names = [prefix, *(f"{prefix}.{alias.name}" for alias in node.names)]
            for name in names:
                parts = name.split(".")
                for end in range(1, len(parts) + 1):
                    target = modules.get(".".join(parts[:end]))
                    if target:
                        deps.add(target)
        # Importing a module also executes its package initializers.
        for end in range(1, len(rel.parts)):
            init = Path(*rel.parts[:end], "__init__.py").as_posix()
            if (root / init).is_file():
                deps.add(init)
        graph[rel.as_posix()] = deps
    return graph


def static_select_tests(changed: list[str], root: Path = ROOT) -> dict[str, str]:
    files = test_files(root)
    changed = sorted(set(changed))
    broad = next((p for p in changed if p in {"tests/conftest.py", "pyproject.toml", "scripts/run_tests.py"}), None)
    if broad:
        return dict.fromkeys(files, broad)
    graph = import_graph(root, changed)
    selected = {}
    for test in files:
        closure, pending = set(), [test]
        while pending:
            module = pending.pop()
            if module not in closure:
                closure.add(module)
                pending.extend(graph.get(module, ()))
        source = (root / test).read_text(encoding="utf-8-sig")
        for change in changed:
            fixture = change.startswith("tests/fixtures/") and Path(change).parent.name in source
            docs = change.startswith("docs/data-model/") and "docs/" in source
            if change in closure or fixture or docs:
                selected[test] = change
                break
    return selected



SOURCE_DIRS = {"src", "scripts"}


def map_path(root: Path = ROOT) -> Path:
    """Return the checkout-specific runtime map outside the repository."""
    cache = Path.home() / "Library/Caches" if sys.platform == "darwin" else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    return cache / CACHE_DIR_NAME / "test-map" / (key + ".json")


def load_test_map(root: Path = ROOT) -> dict | None:
    """Accept a recent map whose recorded HEAD is an ancestor of HEAD."""
    try:
        data = json.loads(map_path(root).read_text())
        if time.time() - data["timestamp"] > 14 * 86400:
            return None
        if subprocess.run(["git", "merge-base", "--is-ancestor", data["commit"], "HEAD"], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            return None
        if not isinstance(data["tests"], dict):
            return None
        return data["tests"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def line_qualnames(source: str, ranges: list[tuple[int, int]]) -> list[tuple[str, bool]]:
    """Map inclusive line ranges to innermost (code qualname, is_class) pairs.

    Decorators belong to the enclosing scope; function nesting includes <locals>
    just as code.co_qualname does. Gaps and module statements map to <module>.
    """
    tree = ast.parse(source)
    scopes = []

    def visit(node, prefix="", function=False, depth=0):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + (".<locals>." if function else ".") + child.name if prefix else child.name
                start = child.lineno
                is_class = isinstance(child, ast.ClassDef)
                scopes.append((start, child.end_lineno, depth, name, is_class))
                visit(child, name, not is_class, depth + 1)
            else:
                visit(child, prefix, function, depth)

    visit(tree)
    found = []
    for start, end in ranges:
        # Scope boundaries suffice even for a whole-file replacement.
        points = {start}
        for lo, hi, *_ in scopes:
            if start <= lo <= end:
                points.add(lo)
            if start <= hi + 1 <= end:
                points.add(hi + 1)
        for line in sorted(points):
            enclosing = [scope for scope in scopes if scope[0] <= line <= scope[1]]
            hit = max(enclosing, key=lambda scope: scope[2]) if enclosing else None
            pair = (hit[3], hit[4]) if hit else ("<module>", False)
            if pair not in found:
                found.append(pair)
    return found


def split_change(change: str) -> tuple[str, str | None]:
    path, sep, target = change.partition(":")
    return path, target if sep else None


def changed_qualnames(path: str, target: str | None, root: Path, ref: str, synthetic: bool) -> list[tuple[str, bool]]:
    """Resolve explicit targets or both sides of a zero-context Git diff."""
    current = (root / path).read_text(encoding="utf-8-sig") if (root / path).exists() else ""
    if target is not None:
        if target.isdigit():
            return line_qualnames(current, [(int(target), int(target))])
        classes = {name for name, cls in line_qualnames(current, [(1, len(current.splitlines()))]) if cls}
        return [(target, target in classes)]
    if synthetic:
        return line_qualnames(current, [(1, max(1, len(current.splitlines())))])
    diff = subprocess.check_output(["git", "diff", "--no-ext-diff", "--no-renames", "-U0", ref, "--", path], cwd=root, text=True)
    old_ranges, new_ranges = [], []
    for old, old_count, new, new_count in re.findall(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", diff, re.MULTILINE):
        for ranges, start, count in ((old_ranges, old, old_count), (new_ranges, new, new_count)):
            count = int(count) if count else 1
            if count:
                ranges.append((int(start), int(start) + count - 1))
    if not diff:  # Untracked file.
        return line_qualnames(current, [(1, max(1, len(current.splitlines())))])
    result = line_qualnames(current, new_ranges)
    if old_ranges:
        old = subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=root).decode("utf-8-sig")
        result.extend(pair for pair in line_qualnames(old, old_ranges) if pair not in result)
    return result


def select_tests(changed: list[str], root: Path = ROOT, ref: str = "HEAD", *, synthetic: bool = False) -> dict[str, str]:
    """Select file-level tests from executed functions and opened data files."""
    files = test_files(root)
    changes = sorted(set(changed))
    paths = [split_change(change)[0] for change in changes]
    broad = next((p for p in paths if p in {"tests/conftest.py", "pyproject.toml", "scripts/run_tests.py"} or Path(p).name == "conftest.py"), None)
    if broad:
        return dict.fromkeys(files, broad)
    mapping = load_test_map(root)
    if mapping is None:
        print("Runtime test map unavailable or expired; using static imports. A FULL run will refresh the map.")
        return static_select_tests(paths, root)
    selected = {}
    for change in changes:
        path, target = split_change(change)
        if path in files:
            selected.setdefault(path, path)
        source = path.endswith(".py") and path.split("/")[0] in SOURCE_DIRS
        recorded = any(p == path for entry in mapping.values() for p, _ in entry["functions"])
        if source and not recorded:
            for test in static_select_tests([path], root):
                selected.setdefault(test, path + " (static fallback)")
            continue
        names = changed_qualnames(path, target, root, ref, synthetic) if source else []
        if source and target is None:
            # A module runs once per process, so the runtime map credits only the
            # first test file that imported it; add its static importers too.
            for test in static_select_tests([path], root):
                selected.setdefault(test, path + " (static import)")
        for test in files:
            entry = mapping.get(test, {})
            for name, is_class in names:
                if any(p == path and ((name == "<module>") or q == name or (is_class and q.startswith(name + "."))) for p, q in entry.get("functions", ())):
                    selected.setdefault(test, path + ":" + name)
                    break
            if path in entry.get("files", ()) and not source:
                selected.setdefault(test, path)
    return {test: selected[test] for test in files if test in selected}


def merge_test_maps(folder: Path, commit: str, root: Path = ROOT) -> None:
    """Union completed worker records and atomically replace the cached map."""
    merged = {}
    for report in sorted(folder.glob("*.json")):
        for test, entry in json.loads(report.read_text()).items():
            dest = merged.setdefault(test, {"functions": set(), "files": set()})
            dest["functions"].update(tuple(pair) for pair in entry["functions"])
            dest["files"].update(entry["files"])
    tests = {test: {key: sorted(values) for key, values in entry.items()} for test, entry in merged.items()}
    path = map_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"commit": commit, "timestamp": time.time(), "tests": tests}, separators=(",", ":")) + "\n")
    temporary.replace(path)
    print(f"Runtime test map refreshed: {path} ({len(tests)} test files)")

def make_plan(files: list[str], weights: dict[str, float], workers: int, exclude_slow: set[str]) -> list[Chunk]:
    # Never shard a file expected to take under 5 s: each shard is a new process.
    threshold = max(sum(weights.get(p, 1.0) for p in files) / workers / 2, 5.0)
    chunks = []
    small = defaultdict(list)
    isolated = []
    for path in files:
        weight = weights.get(path, 1.0)
        exclude = path in exclude_slow
        source = ROOT / path
        needs_quiet = source.is_file() and any(
            isinstance(node, ast.Attribute) and node.attr == "isolated"
            and isinstance(node.value, ast.Attribute) and node.value.attr == "mark"
            and isinstance(node.value.value, ast.Name) and node.value.value.id == "pytest"
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig")))
        )
        if needs_quiet:
            isolated.append(Chunk((path,), weight, exclude, isolated=True))
        elif weight > threshold:
            count = math.ceil(weight / threshold)
            chunks.extend(Chunk((path,), weight / count, exclude, index, count) for index in range(count))
        else:
            small[exclude].append((path, weight))
    for exclude, entries in small.items():
        # Pack small files to about 25 s, without mixing slow-marker policies.
        paths, seconds = [], 0.0
        for path, weight in sorted(entries, key=lambda entry: (-entry[1], entry[0])):
            if paths and seconds + weight > 30:
                chunks.append(Chunk(tuple(paths), seconds, exclude))
                paths, seconds = [], 0.0
            paths.append(path)
            seconds += weight
            if seconds >= 20:
                chunks.append(Chunk(tuple(paths), seconds, exclude))
                paths, seconds = [], 0.0
        if paths:
            chunks.append(Chunk(tuple(paths), seconds, exclude))
    return sorted(chunks, key=lambda chunk: -chunk.seconds) + sorted(isolated, key=lambda chunk: -chunk.seconds)


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.setdefault("RAWTIMS_BLOCK_IMPORTS", "requests,keyring")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def pytest_command(paths: tuple[str, ...] | list[str]) -> list[str]:
    return [sys.executable, "-m", "pytest", *paths, "-q", "-p", "no:cacheprovider"]


def junit_results(path: Path) -> tuple[Counter, list[tuple[str, str]]]:
    counts, failures = Counter(), []
    tree = ET.parse(path)
    for case in tree.iter("testcase"):
        error, failure, skipped = case.find("error"), case.find("failure"), case.find("skipped")
        status = "errors" if error is not None else "failed" if failure is not None else "skipped" if skipped is not None else "passed"
        counts[status] += 1
        if status in {"errors", "failed"}:
            classname = case.get("classname", "")
            candidates = [p for p in test_files() if classname == p[:-3].replace("/", ".") or classname.startswith(p[:-3].replace("/", ".") + ".")]
            if candidates:
                filename = max(candidates, key=len)
                classes = classname[len(filename[:-3].replace("/", ".")):].strip(".")
                nodeid = filename + ("::" + classes.replace(".", "::") if classes else "")
            else:
                nodeid = classname.replace(".", "/") + ".py"
            nodeid += "::" + case.get("name", "")
            detail = error if error is not None else failure
            output = "\n".join(filter(None, [detail.text, case.findtext("system-out"), case.findtext("system-err")]))
            failures.append((nodeid, "\n".join(output.splitlines()[-25:])))
    return counts, failures


def run_plan(plan: list[Chunk], workers: int, tier: str) -> int:
    start = time.monotonic()
    folder = Path(tempfile.mkdtemp(prefix=f"{CACHE_DIR_NAME}-{tier}-"))
    env = environment()
    map_folder = folder / "test-map"
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() if tier == "full" else ""
    if tier == "full":
        map_folder.mkdir()
    expected = Counter()
    # A single unsharded collection per marker policy guards file and shard coverage.
    for exclude in sorted({chunk.exclude_slow for chunk in plan}):
        paths = sorted({path for chunk in plan if chunk.exclude_slow == exclude for path in chunk.paths})
        report = folder / f"collect-{exclude}.json"
        collect_env = {**env, "RAWTIMS_TEST_COLLECTION": str(report)}
        result = subprocess.run(pytest_command(paths) + (["-m", "not slow"] if exclude else []) + ["--collect-only"], cwd=ROOT, env=collect_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (folder / f"collect-{exclude}.log").write_text(result.stdout)
        if result.returncode not in (0, 5) or not report.exists():
            print(result.stdout[-8000:])
            print(f"Collection failed. Logs: {folder}")
            return 1
        expected.update(json.loads(report.read_text()))
    print(f"Collected {sum(expected.values())} tests; {len(plan)} chunks, {workers} workers.", flush=True)

    def run(index: int, chunk: Chunk):
        before = time.monotonic()
        log = folder / f"chunk-{index}.log"
        report = folder / f"chunk-{index}.json"
        xml = folder / f"chunk-{index}.xml"
        with log.open("w") as output:
            result = subprocess.run(pytest_command(chunk.paths) + chunk.flags() + [f"--junitxml={xml}", "-o", "junit_logging=all", "-o", "junit_log_passing_tests=false"], cwd=ROOT, env={**env, "RAWTIMS_TEST_COLLECTION": str(report), **({"RAWTIMS_TEST_MAP_DIR": str(map_folder)} if tier == "full" else {})}, stdout=output, stderr=subprocess.STDOUT)
        return index, result.returncode, time.monotonic() - before, log, report, xml

    totals, actual, failed, finished = Counter(), Counter(), False, 0
    reports_complete = True
    completed = True
    failure_details = []

    def record(result):
        nonlocal failed, finished, reports_complete, completed
        index, code, elapsed, log, report, xml = result
        finished += 1
        completed &= code in (0, 1, 5)
        if report.exists():
            actual.update(json.loads(report.read_text()))
        else:
            failed = True
            reports_complete = False
        try:
            counts, failures = junit_results(xml)
        except (OSError, ET.ParseError) as error:
            counts, failures = Counter(), []
            print(f"chunk-{index}: missing/invalid JUnit report: {error}")
            failed = True
            reports_complete = False
        totals.update(counts)
        # pytest returns 5 when an individual shard has no selected tests.
        bad = code not in (0, 5) or counts["failed"] or counts["errors"]
        failed |= bool(bad)
        print(f"[{finished}/{len(plan)}] chunk-{index}: {'FAIL' if bad else 'OK'} {elapsed:.1f} s ({', '.join(f'{key}={value}' for key, value in counts.items()) or 'empty shard'})", flush=True)
        failure_details.extend(failures)
        if bad and not failures:
            failure_details.append((f"chunk-{index}", "\n".join(log.read_text(errors="replace").splitlines()[-35:])))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, index, chunk) for index, chunk in enumerate(plan) if not chunk.isolated]
        for future in as_completed(futures):
            record(future.result())
    # Wall-clock UI latency checks need an idle machine, with assertions intact.
    for index, chunk in enumerate(plan):
        if chunk.isolated:
            print(f"Quiet phase: {' '.join(chunk.paths)}", flush=True)
            record(run(index, chunk))
    if actual != expected:
        failed = True
        print(f"Collection mismatch: expected {sum(expected.values())}, got {sum(actual.values())}.")
        print(f"Missing: {list((expected - actual).elements())[:20]}; extra: {list((actual - expected).elements())[:20]}")
    failed |= bool(totals["failed"] or totals["errors"])
    print("Totals: " + ", ".join(f"{name}={totals[name]}" for name in ("passed", "failed", "skipped", "errors")))
    for nodeid, output in failure_details:
        print(f"\n{nodeid}\n{output}\n")
    print(f"Wall time: {time.monotonic() - start:.1f} s. Logs and JUnit XML: {folder}", flush=True)
    if tier == "full" and completed and reports_complete and actual == expected:
        records = list(map_folder.glob("*.json"))
        if len(records) == len(plan):
            merge_test_maps(map_folder, commit)
        else:
            print("Runtime map not refreshed: missing worker records.")
        stats = [json.loads(p.read_text()) for p in map_folder.glob("*.stats")]
        overhead = sum(s["callback_seconds"] for s in stats)
        wall = sum(s["session_seconds"] for s in stats)
        print(f"Recording callbacks: {overhead:.3f} s / {wall:.1f} process s ({100 * overhead / wall if wall else 0:.2f}%). Includes audit and restart work; excludes interpreter dispatch.")
    if tier == "full":
        LAST_FULL.write_text(json.dumps({"folder": str(folder), "complete": reports_complete and actual == expected}) + "\n")
    return int(failed)


def update_durations(source: Path | None) -> None:
    weights = dict.fromkeys(test_files(), 1.0)
    measured = defaultdict(float)
    if source is not None:
        for line in source.read_text().splitlines():
            match = DURATION_LINE.match(line)
            if match:
                measured[match[2]] += float(match[1])
        if not measured:
            raise ValueError(f"No pytest duration rows found in {source}")
    else:
        last = json.loads(LAST_FULL.read_text())
        if not last["complete"]:
            raise ValueError("Last full run has incomplete reports; durations were not updated")
        for xml in sorted(Path(last["folder"]).glob("chunk-*.xml")):
            for case in ET.parse(xml).iter("testcase"):
                classname = case.get("classname", "")
                matches = [path for path in weights if classname == path[:-3].replace("/", ".") or classname.startswith(path[:-3].replace("/", ".") + ".")]
                if matches:
                    measured[max(matches, key=len)] += float(case.get("time", "0"))
        if not measured:
            raise ValueError("No test durations in last full run")
    weights.update({path: round(max(seconds, 0.01), 2) for path, seconds in measured.items() if path in weights})
    DURATIONS.write_text(json.dumps(weights, indent=2, sort_keys=True) + "\n")
    print(f"Updated {DURATIONS.relative_to(ROOT)} ({len(weights)} files).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tier", choices=("quick", "full"), nargs="?")
    parser.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 1) - 4)))
    parser.add_argument("--since", default="HEAD", help="git diff base for QUICK (default: HEAD)")
    parser.add_argument("--changed", nargs="+", metavar="FILE[:LINE|QUALNAME]", help="replace git discovery with synthetic changed files or targets")
    parser.add_argument("--list", action="store_true", help="print selection and chunks without running pytest")
    parser.add_argument("--update-durations", nargs="?", const="", metavar="FILE", help="rewrite weights from pytest duration text, or last full JUnit XML when FILE is omitted")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.update_durations is not None:
        update_durations(Path(args.update_durations) if args.update_durations else None)
        return 0
    if args.tier is None:
        parser.error("choose quick or full, or --update-durations")
    changed = []
    if args.tier == "quick":
        if args.changed is not None:
            changed = [Path(os.path.relpath(Path(split_change(p)[0]).resolve(), ROOT)).as_posix() + (":" + split_change(p)[1] if split_change(p)[1] is not None else "") for p in args.changed]
        else:
            for command in (["git", "diff", "--no-renames", "--name-only", "-z", args.since, "--"], ["git", "ls-files", "--others", "--exclude-standard", "-z"]):
                changed.extend(filter(None, subprocess.check_output(command, cwd=ROOT).decode().split("\0")))
        selected = select_tests(changed, ref=args.since, synthetic=args.changed is not None)
    else:
        selected = dict.fromkeys(test_files(), "FULL")
    for path, reason in selected.items():
        print(f"{path} <- {reason}")
    print(f"Selected {len(selected)} test files.", flush=True)
    if not selected:
        print("No affected tests.")
        return 0
    weights = json.loads(DURATIONS.read_text()) if DURATIONS.exists() else {}
    excluded = set(selected).difference(split_change(p)[0] for p in changed) if args.tier == "quick" else set()
    plan = make_plan(list(selected), weights, args.workers, excluded)
    if args.list:
        for index, chunk in enumerate(plan):
            print(f"chunk-{index}: {chunk.seconds:.1f} s expected: {' '.join(chunk.paths)} {' '.join(chunk.flags())}{' [quiet phase]' if chunk.isolated else ''}")
        print(f"{len(plan)} chunks on {args.workers} workers; {sum(c.seconds for c in plan):.1f} s expected test time.")
        return 0
    return run_plan(plan, args.workers, args.tier)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"run_tests.py: {error}", file=sys.stderr)
        raise SystemExit(1)
