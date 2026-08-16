from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from .service import BackupError, BackupService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novelforge-backup",
        description=(
            "Create, verify, or restore an offline NovelForge data snapshot."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--data-root", type=Path, default=Path("/app/data"))
    create.add_argument(
        "--output-root",
        type=Path,
        default=Path("/app/backups"),
    )
    create.add_argument("--backup-id")
    create.add_argument(
        "--confirm-offline",
        action="store_true",
        required=True,
        help="Confirm Backend and Worker writers are stopped.",
    )

    verify = commands.add_parser("verify")
    verify.add_argument("backup_dir", type=Path)

    restore = commands.add_parser("restore")
    restore.add_argument("backup_dir", type=Path)
    restore.add_argument("--target-root", type=Path, required=True)
    restore.add_argument(
        "--execute",
        action="store_true",
        help="Write the verified snapshot to a new target directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = BackupService()
    try:
        if args.command == "create":
            result = service.create(
                data_root=args.data_root,
                output_root=args.output_root,
                backup_id=args.backup_id,
                offline_confirmed=args.confirm_offline,
            )
            payload = {
                "result": "ok",
                "operation": "create",
                "backup_id": result.manifest.backup_id,
                "backup_dir": str(result.backup_dir),
                "checked_files": result.verification.checked_files,
                "rebuild_required": result.manifest.rebuild_required,
                "consistency_mode": result.manifest.consistency_mode,
            }
        elif args.command == "verify":
            verified = service.verify(args.backup_dir)
            payload = {
                "result": "ok",
                "operation": "verify",
                **verified.model_dump(),
            }
        else:
            restored = service.restore(
                backup_dir=args.backup_dir,
                target_root=args.target_root,
                execute=args.execute,
            )
            payload = {
                "result": "ok",
                "operation": "restore",
                **restored.model_dump(),
            }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except BackupError as exc:
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
