"""
Phase 31 STEP 8 — Promptfoo regression CI gate.

Parses a Promptfoo results artifact (the exported CSV *or* the JSON written to
`reports/promptfoo_latest.json`) and exits non-zero when the pass rate falls below
a threshold (default 95%), so a PR that regresses answer quality fails the build.

Usage
-----
    # gate the exported CSV
    python -m app.evaluation.promptfoo_regression_suite --csv eval-...-results.csv

    # gate the structured-runner JSON
    python -m app.evaluation.promptfoo_regression_suite --json reports/promptfoo_latest.json

    # custom threshold
    python -m app.evaluation.promptfoo_regression_suite --csv results.csv --min-pass-rate 0.95

Exit codes: 0 = pass-rate >= threshold; 1 = below threshold; 2 = could not parse input.

The CSV reader understands the Promptfoo export layout used by this project, where
each provider column contributes a `Pass`/`Fail` cell. ERROR rows (e.g. the
"Context is required" harness misconfiguration) are counted as failures by default;
pass `--ignore-harness-errors` to exclude pure-harness errors from the denominator
when you want the *answer-quality* rate rather than the raw run rate.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MIN_PASS_RATE = 0.95
_HARNESS_ERROR_MARKERS = (
    "Context is required for context-based assertions",
    "Invariant failed",
)


@dataclass
class GateResult:
    total: int = 0
    passed: int = 0
    failed: int = 0
    harness_errors: int = 0
    failures: list[dict] = field(default_factory=list)

    @property
    def evaluated(self) -> int:
        return self.total

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0


def _is_harness_error(text: str) -> bool:
    return any(m in (text or "") for m in _HARNESS_ERROR_MARKERS)


def parse_csv(path: Path, ignore_harness_errors: bool = False) -> GateResult:
    """Count Pass/Fail across every provider column in a Promptfoo CSV export."""
    res = GateResult()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            return res
        # Each provider column emits an output cell followed by a "Pass" verdict cell.
        pass_cols = [i for i, h in enumerate(header) if h.strip().lower() == "pass"]
        if not pass_cols:
            return res
        query_col = 0
        for row in reader:
            if not row:
                continue
            query = row[query_col] if len(row) > query_col else ""
            for pc in pass_cols:
                if pc >= len(row):
                    continue
                verdict = (row[pc] or "").strip().lower()
                # the model output sits in the cell immediately before the verdict
                output_cell = row[pc - 1] if pc - 1 >= 0 else ""
                if verdict not in {"pass", "fail"}:
                    continue
                is_err = _is_harness_error(output_cell)
                if verdict == "pass":
                    res.total += 1
                    res.passed += 1
                else:
                    if is_err:
                        res.harness_errors += 1
                        if ignore_harness_errors:
                            continue
                    res.total += 1
                    res.failed += 1
                    res.failures.append({"query": query, "output": output_cell[:160]})
    return res


def parse_json(path: Path, ignore_harness_errors: bool = False) -> GateResult:
    """Count Pass/Fail from a Promptfoo eval JSON, OR the deterministic runner's
    summary JSON (``{total_tests, total_passed, overall_pass_rate}``)."""
    res = GateResult()
    data = json.loads(path.read_text(encoding="utf-8"))

    # Deterministic-runner summary format (app.evaluation.promptfoo_runner).
    if "total_tests" in data and "total_passed" in data:
        res.total = int(data.get("total_tests") or 0)
        res.passed = int(data.get("total_passed") or 0)
        res.failed = res.total - res.passed
        return res

    results = (data.get("results") or {}).get("results")
    if results is None:
        results = data.get("results") if isinstance(data.get("results"), list) else []
    for r in results or []:
        success = r.get("success")
        err = r.get("error") or ""
        is_err = _is_harness_error(err)
        if success:
            res.total += 1
            res.passed += 1
        else:
            if is_err:
                res.harness_errors += 1
                if ignore_harness_errors:
                    continue
            res.total += 1
            res.failed += 1
            prompt = (r.get("prompt") or {}).get("raw") or r.get("vars", {})
            res.failures.append({"query": str(prompt)[:120], "output": (r.get("response") or {}).get("output", "")[:160] if isinstance(r.get("response"), dict) else ""})
    return res


def run_gate(
    csv_path: str | None = None,
    json_path: str | None = None,
    min_pass_rate: float = DEFAULT_MIN_PASS_RATE,
    ignore_harness_errors: bool = False,
) -> tuple[GateResult, bool]:
    if csv_path:
        res = parse_csv(Path(csv_path), ignore_harness_errors)
    elif json_path:
        res = parse_json(Path(json_path), ignore_harness_errors)
    else:
        raise ValueError("Provide --csv or --json")
    ok = res.total > 0 and res.pass_rate >= min_pass_rate
    return res, ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Promptfoo regression CI gate (Phase 31 STEP 8).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="Promptfoo results CSV export")
    src.add_argument("--json", help="Promptfoo eval JSON (reports/promptfoo_latest.json)")
    ap.add_argument("--min-pass-rate", type=float, default=DEFAULT_MIN_PASS_RATE)
    ap.add_argument("--ignore-harness-errors", action="store_true",
                    help="Exclude pure-harness ERROR rows (e.g. 'Context is required') from the denominator")
    ap.add_argument("--max-failures-shown", type=int, default=15)
    args = ap.parse_args(argv)

    try:
        res, ok = run_gate(args.csv, args.json, args.min_pass_rate, args.ignore_harness_errors)
    except Exception as exc:
        print(f"[GATE] could not parse input: {exc}", file=sys.stderr)
        return 2

    if res.total == 0:
        print("[GATE] no Pass/Fail verdicts found in input", file=sys.stderr)
        return 2

    print("=" * 64)
    print("PROMPTFOO REGRESSION GATE")
    print("=" * 64)
    print(f"  evaluated      : {res.total}")
    print(f"  passed         : {res.passed}")
    print(f"  failed         : {res.failed}")
    print(f"  harness errors : {res.harness_errors}"
          + ("  (excluded)" if args.ignore_harness_errors else "  (counted as fail)"))
    print(f"  pass rate      : {res.pass_rate:.1%}")
    print(f"  threshold      : {args.min_pass_rate:.1%}")
    print("-" * 64)
    if not ok and res.failures:
        print("Sample failures:")
        for f in res.failures[: args.max_failures_shown]:
            print(f"  - {f['query'][:80]!r}: {f['output'][:90]}")
        print("-" * 64)
    print(f"RESULT: {'PASS' if ok else 'FAIL'} "
          f"({res.pass_rate:.1%} {'>=' if ok else '<'} {args.min_pass_rate:.1%})")
    print("=" * 64)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
