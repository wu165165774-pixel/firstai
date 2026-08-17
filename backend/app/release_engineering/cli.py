from __future__ import annotations

import argparse
import json

from app.release_engineering.service import (
    ReleaseEngineeringService,
    ReleaseValidationError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NovelForge release tooling")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--repo-root", default=".")
    validate.add_argument("--expected-version")
    validate.add_argument("--tag")
    package = subparsers.add_parser("package")
    package.add_argument("--repo-root", default=".")
    package.add_argument("--output-dir", required=True)
    package.add_argument("--expected-version")
    package.add_argument("--tag")
    package.add_argument("--commit")
    verify = subparsers.add_parser("verify")
    verify.add_argument("archive")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "verify":
            result = ReleaseEngineeringService.verify(args.archive)
        else:
            service = ReleaseEngineeringService(args.repo_root)
            if args.operation == "validate":
                result = service.validate(
                    expected_version=args.expected_version,
                    tag=args.tag,
                )
            else:
                result = service.package(
                    args.output_dir,
                    expected_version=args.expected_version,
                    tag=args.tag,
                    commit=args.commit,
                )
    except ReleaseValidationError as exc:
        print(json.dumps({"result": "error", "error": str(exc)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
