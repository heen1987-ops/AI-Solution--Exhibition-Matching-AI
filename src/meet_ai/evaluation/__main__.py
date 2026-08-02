from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .engine import (
    EVALUATOR_VERSION,
    GoldenSetValidationError,
    evaluate_golden_set,
    load_golden_set,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate a versioned golden set with the published matching policies."
    )
    parser.add_argument("golden_set", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-regression",
        action="store_true",
        help="Return exit code 0 even when quality thresholds fail.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = evaluate_golden_set(load_golden_set(args.golden_set))
    except GoldenSetValidationError as exc:
        output = (
            json.dumps(
                {
                    "evaluator_version": EVALUATOR_VERSION,
                    "status": "ERROR",
                    "error_code": "GOLDEN_SET_INVALID",
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        if args.output is None:
            print(output, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        return 2

    output = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(output, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return 0 if report.status == "PASS" or args.allow_regression else 1


if __name__ == "__main__":
    raise SystemExit(main())
