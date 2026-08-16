from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from .service import SchemaMigrationError, SchemaMigrationService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novelforge-schema",
        description="Inspect, upgrade, or verify NovelForge SQLite schemas.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status")
    status.add_argument("--data-root", type=Path, default=Path("/app/data"))

    upgrade = commands.add_parser("upgrade")
    upgrade.add_argument("--data-root", type=Path, default=Path("/app/data"))
    upgrade.add_argument("--backup-dir", type=Path, required=True)
    upgrade.add_argument(
        "--confirm-offline",
        action="store_true",
        required=True,
        help="Confirm Backend and Worker writers are stopped.",
    )

    verify = commands.add_parser("verify")
    verify.add_argument("--data-root", type=Path, default=Path("/app/data"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = SchemaMigrationService()
    try:
        if args.command == "status":
            result = service.status(data_root=args.data_root)
            payload = {
                "result": "ok",
                "operation": "status",
                **result.model_dump(),
            }
        elif args.command == "upgrade":
            result = service.upgrade(
                data_root=args.data_root,
                backup_dir=args.backup_dir,
                offline_confirmed=args.confirm_offline,
            )
            payload = {
                "result": "ok",
                "operation": "upgrade",
                **result.model_dump(),
            }
        else:
            result = service.verify(data_root=args.data_root)
            payload = {
                "result": "ok",
                "operation": "verify",
                **result.model_dump(),
            }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except SchemaMigrationError as exc:
        print(
            json.dumps(
                {"result": "error", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
