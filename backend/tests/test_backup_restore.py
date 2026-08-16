import io
import json
import sqlite3
import tempfile
import unittest

from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import faiss
import numpy as np

from app.backup.cli import main as backup_cli_main
from app.backup.schemas import BackupManifest
from app.backup.service import (
    BackupError,
    BackupService,
)


class BackupRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_root = self.root / "data"
        self.output_root = self.root / "backups"
        self.data_root.mkdir()
        self._create_authoritative_data()
        self.service = BackupService()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_authoritative_data(self) -> None:
        for index, name in enumerate(BackupService.SQLITE_FILES, start=1):
            path = self.data_root / name
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)"
                )
                conn.execute(
                    "INSERT INTO sample(value) VALUES (?)",
                    (f"value-{index}",),
                )
                conn.execute(f"PRAGMA user_version = {index}")

        vector_root = self.data_root / "vector_db"
        vector_root.mkdir()
        memory_index = faiss.IndexFlatIP(4)
        memory_index.add(
            np.array([[1.0, 0.0, 0.0, 0.0]], dtype="float32")
        )
        faiss.write_index(memory_index, str(vector_root / "memory.index"))
        (vector_root / "memory_ids.json").write_text(
            '{"0":"memory-1"}',
            encoding="utf-8",
        )
        knowledge_index = faiss.IndexFlatIP(4)
        knowledge_index.add(
            np.array([[0.0, 1.0, 0.0, 0.0]], dtype="float32")
        )
        faiss.write_index(
            knowledge_index,
            str(vector_root / "external_knowledge.index"),
        )
        (vector_root / "external_knowledge_ids.json").write_text(
            '{"0":"chunk-1"}',
            encoding="utf-8",
        )
        (self.data_root / "unrelated.log").write_text(
            "must not be backed up",
            encoding="utf-8",
        )

    def _backup(self) -> Path:
        return self.service.create(
            data_root=self.data_root,
            output_root=self.output_root,
            backup_id="backup-test",
            offline_confirmed=True,
        ).backup_dir

    def test_create_requires_explicit_offline_confirmation(self) -> None:
        with self.assertRaisesRegex(BackupError, "explicitly confirmed"):
            self.service.create(
                data_root=self.data_root,
                output_root=self.output_root,
                backup_id="not-confirmed",
            )

    def test_create_captures_authorities_and_manifest_only(self) -> None:
        backup_dir = self._backup()
        manifest = BackupManifest.model_validate_json(
            (backup_dir / "manifest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest.consistency_mode, "offline_required")
        self.assertEqual(len(manifest.files), 9)
        self.assertNotIn(str(self.data_root), manifest.model_dump_json())
        self.assertEqual(
            {item.relative_path for item in manifest.files},
            {
                *BackupService.SQLITE_FILES,
                *BackupService.FAISS_FILES,
            },
        )
        self.assertFalse(
            (backup_dir / "files" / "unrelated.log").exists()
        )
        sqlite_entries = [
            item for item in manifest.files if item.kind == "sqlite"
        ]
        self.assertEqual(
            [item.sqlite_user_version for item in sqlite_entries],
            [1, 2, 3, 4, 5],
        )
        index_entries = [
            item for item in manifest.files if item.kind == "faiss_index"
        ]
        self.assertEqual(
            [
                (item.faiss_dimension, item.faiss_count)
                for item in index_entries
            ],
            [(4, 1), (4, 1)],
        )
        self.assertTrue(self.service.verify(backup_dir).valid)

    def test_create_falls_back_when_directory_replace_is_unsupported(
        self,
    ) -> None:
        with patch(
            "app.backup.service.os.replace",
            side_effect=OSError("directory rename unsupported"),
        ):
            backup_dir = self._backup()

        self.assertTrue((backup_dir / "manifest.json").is_file())
        self.assertTrue(self.service.verify(backup_dir).valid)

    def test_verify_detects_changed_or_extra_files(self) -> None:
        backup_dir = self._backup()
        target = backup_dir / "files" / "vector_db" / "memory.index"
        target.write_bytes(b"tampered")

        with self.assertRaisesRegex(
            BackupError,
            "size mismatch|checksum",
        ):
            self.service.verify(backup_dir)

        source = self.data_root / "vector_db" / "memory.index"
        target.write_bytes(source.read_bytes())
        (backup_dir / "files" / "extra.txt").write_text(
            "extra",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(BackupError, "unmanifested"):
            self.service.verify(backup_dir)

    def test_restore_defaults_to_dry_run_then_restores_new_root(self) -> None:
        backup_dir = self._backup()
        restore_root = self.root / "restored"

        dry_run = self.service.restore(
            backup_dir=backup_dir,
            target_root=restore_root,
        )
        self.assertTrue(dry_run.dry_run)
        self.assertFalse(restore_root.exists())

        restored = self.service.restore(
            backup_dir=backup_dir,
            target_root=restore_root,
            execute=True,
        )
        self.assertFalse(restored.dry_run)
        self.assertEqual(restored.restored_files, 9)
        with sqlite3.connect(restore_root / "novels.db") as conn:
            value = conn.execute("SELECT value FROM sample").fetchone()[0]
        self.assertEqual(value, "value-1")
        self.assertEqual(
            faiss.read_index(
                str(restore_root / "vector_db" / "memory.index")
            ).ntotal,
            1,
        )

    def test_restore_refuses_existing_target(self) -> None:
        backup_dir = self._backup()
        restore_root = self.root / "existing"
        restore_root.mkdir()

        with self.assertRaisesRegex(BackupError, "must not exist"):
            self.service.restore(
                backup_dir=backup_dir,
                target_root=restore_root,
                execute=True,
            )

    def test_partial_faiss_pair_is_rejected(self) -> None:
        (
            self.data_root
            / "vector_db"
            / "external_knowledge_ids.json"
        ).unlink()
        with self.assertRaisesRegex(BackupError, "incomplete FAISS pair"):
            self.service.create(
                data_root=self.data_root,
                output_root=self.output_root,
                backup_id="partial-index",
                offline_confirmed=True,
            )

    def test_faiss_count_must_match_mapping(self) -> None:
        (self.data_root / "vector_db" / "memory_ids.json").write_text(
            "{}",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(BackupError, "count does not match"):
            self.service.create(
                data_root=self.data_root,
                output_root=self.output_root,
                backup_id="count-mismatch",
                offline_confirmed=True,
            )

    def test_manifest_path_traversal_is_rejected(self) -> None:
        backup_dir = self._backup()
        manifest_path = backup_dir / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["files"][0]["relative_path"] = "../outside.db"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(BackupError, "manifest"):
            self.service.verify(backup_dir)

    def test_manifest_cannot_omit_an_authoritative_database(self) -> None:
        backup_dir = self._backup()
        manifest_path = backup_dir / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["files"] = [
            item
            for item in payload["files"]
            if item["relative_path"] != "novels.db"
        ]
        (backup_dir / "files" / "novels.db").unlink()
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(BackupError, "SQLite authority"):
            self.service.verify(backup_dir)

    def test_missing_faiss_pair_is_marked_for_rebuild(self) -> None:
        vector_root = self.data_root / "vector_db"
        (vector_root / "external_knowledge.index").unlink()
        (vector_root / "external_knowledge_ids.json").unlink()

        result = self.service.create(
            data_root=self.data_root,
            output_root=self.output_root,
            backup_id="rebuild-index",
            offline_confirmed=True,
        )
        self.assertEqual(
            result.manifest.rebuild_required,
            ["external_knowledge_vector"],
        )
        self.assertEqual(result.verification.checked_files, 7)

    def test_cli_create_verify_and_restore_dry_run(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = backup_cli_main(
                [
                    "create",
                    "--data-root",
                    str(self.data_root),
                    "--output-root",
                    str(self.output_root),
                    "--backup-id",
                    "cli-backup",
                    "--confirm-offline",
                ]
            )
        self.assertEqual(exit_code, 0)
        created = json.loads(output.getvalue())
        self.assertEqual(created["operation"], "create")
        self.assertEqual(created["checked_files"], 9)

        backup_dir = self.output_root / "cli-backup"
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = backup_cli_main(["verify", str(backup_dir)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(output.getvalue())["valid"])

        restore_root = self.root / "cli-restore"
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = backup_cli_main(
                [
                    "restore",
                    str(backup_dir),
                    "--target-root",
                    str(restore_root),
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        self.assertFalse(restore_root.exists())


if __name__ == "__main__":
    unittest.main()
