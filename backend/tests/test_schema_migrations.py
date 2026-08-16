import io
import json
import os
import sqlite3
import tempfile
import unittest

from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import faiss
import numpy as np

from app.backup.service import BackupService
from app.knowledge.storage import SQLiteExternalKnowledgeStorage
from app.manuscripts.storage import ManuscriptStorage
from app.memory.storage.sqlite import SQLiteMemoryStorage
from app.novels.storage import NovelProjectStorage
from app.orchestrator.storage import NovelOrchestrationStorage
from app.schema_migrations.cli import main as schema_cli_main
from app.schema_migrations.contracts import AUTHORITIES_BY_KEY
from app.schema_migrations.service import (
    SchemaMigrationError,
    SchemaMigrationService,
)
from app.temporal_graph.storage import TemporalGraphStorage
from app.workflows.async_queue import WorkflowAsyncQueue


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_root = self.root / "data"
        self.backup_root = self.root / "backups"
        self.data_root.mkdir()
        self._initialize_legacy_schema()
        self._initialize_vectors()
        self.backup_dir = BackupService().create(
            data_root=self.data_root,
            output_root=self.backup_root,
            backup_id="migration-backup",
            offline_confirmed=True,
        ).backup_dir
        self.service = SchemaMigrationService()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _initialize_legacy_schema(self) -> None:
        novels = self.data_root / "novels.db"
        workflow = self.data_root / "workflow_runs.db"
        NovelProjectStorage(str(novels))
        ManuscriptStorage(str(novels))
        WorkflowAsyncQueue(str(workflow))
        NovelOrchestrationStorage(str(workflow))
        SQLiteMemoryStorage(str(self.data_root / "memory.db"))
        SQLiteExternalKnowledgeStorage(
            str(self.data_root / "external_knowledge.db")
        )
        TemporalGraphStorage(str(self.data_root / "temporal_graph.db"))

    def _initialize_vectors(self) -> None:
        vector_root = self.data_root / "vector_db"
        vector_root.mkdir()
        for name in ("memory", "external_knowledge"):
            index = faiss.IndexFlatIP(4)
            index.add(
                np.array([[1.0, 0.0, 0.0, 0.0]], dtype="float32")
            )
            faiss.write_index(index, str(vector_root / f"{name}.index"))
            (vector_root / f"{name}_ids.json").write_text(
                json.dumps({"0": f"{name}-item"}),
                encoding="utf-8",
            )

    def _runtime_environment(self) -> dict[str, str]:
        return {
            "NOVELFORGE_NOVEL_DB_PATH": str(self.data_root / "novels.db"),
            "NOVELFORGE_WORKFLOW_DB_PATH": str(
                self.data_root / "workflow_runs.db"
            ),
            "MEMORY_DB_PATH": str(self.data_root / "memory.db"),
            "EXTERNAL_KNOWLEDGE_DB_PATH": str(
                self.data_root / "external_knowledge.db"
            ),
            "NOVELFORGE_TEMPORAL_GRAPH_DB_PATH": str(
                self.data_root / "temporal_graph.db"
            ),
        }

    def test_status_is_read_only_and_reports_legacy_ready(self) -> None:
        result = self.service.status(data_root=self.data_root)

        self.assertFalse(result.ready)
        self.assertEqual(
            {item.state for item in result.authorities},
            {"upgrade_required"},
        )
        for authority in AUTHORITIES_BY_KEY.values():
            with sqlite3.connect(self.data_root / authority.filename) as conn:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    0,
                )
                ledger = conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name = ?",
                    (self.service.LEDGER_TABLE,),
                ).fetchone()
                self.assertIsNone(ledger)

    def test_upgrade_requires_offline_confirmation_and_valid_backup(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            SchemaMigrationError,
            "explicitly confirmed",
        ):
            self.service.upgrade(
                data_root=self.data_root,
                backup_dir=self.backup_dir,
            )

        with self.assertRaisesRegex(SchemaMigrationError, "valid.*backup"):
            self.service.upgrade(
                data_root=self.data_root,
                backup_dir=self.root / "missing-backup",
                offline_confirmed=True,
            )

    def test_upgrade_is_versioned_verified_and_idempotent(self) -> None:
        first = self.service.upgrade(
            data_root=self.data_root,
            backup_dir=self.backup_dir,
            offline_confirmed=True,
        )

        self.assertEqual(first.backup_id, "migration-backup")
        self.assertEqual(set(first.upgraded), set(AUTHORITIES_BY_KEY))
        self.assertEqual(first.already_current, [])
        self.assertTrue(
            all(item.state == "current" for item in first.authorities)
        )
        for authority in AUTHORITIES_BY_KEY.values():
            with sqlite3.connect(self.data_root / authority.filename) as conn:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    1,
                )
                row = conn.execute(
                    f"SELECT authority, version, application_version "
                    f"FROM {self.service.LEDGER_TABLE}"
                ).fetchone()
                self.assertEqual(row[0], authority.key)
                self.assertEqual(row[1], 1)
                self.assertTrue(str(row[2]).startswith("0.15.0-alpha."))

        second = self.service.upgrade(
            data_root=self.data_root,
            backup_dir=self.backup_dir,
            offline_confirmed=True,
        )
        self.assertEqual(second.upgraded, [])
        self.assertEqual(
            set(second.already_current),
            set(AUTHORITIES_BY_KEY),
        )

    def test_upgrade_bootstraps_historical_memory_columns(self) -> None:
        memory_path = self.data_root / "memory.db"
        memory_path.unlink()
        with sqlite3.connect(memory_path) as conn:
            conn.execute(
                """
                CREATE TABLE memories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    metadata TEXT
                )
                """
            )

        refreshed_backup = BackupService().create(
            data_root=self.data_root,
            output_root=self.backup_root,
            backup_id="legacy-memory-backup",
            offline_confirmed=True,
        ).backup_dir
        result = self.service.upgrade(
            data_root=self.data_root,
            backup_dir=refreshed_backup,
            offline_confirmed=True,
        )

        self.assertIn("memory", result.upgraded)
        with sqlite3.connect(memory_path) as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(memories)")
            }
        self.assertTrue(
            {"memory_tier", "session_id", "expires_at", "revision"}
            <= columns
        )

    def test_upgrade_repairs_missing_declared_index(self) -> None:
        knowledge_path = self.data_root / "external_knowledge.db"
        with sqlite3.connect(knowledge_path) as conn:
            conn.execute("DROP INDEX idx_external_sources_scope")

        result = self.service.upgrade(
            data_root=self.data_root,
            backup_dir=self.backup_dir,
            offline_confirmed=True,
        )

        self.assertIn("external_knowledge", result.upgraded)
        with sqlite3.connect(knowledge_path) as conn:
            index = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name='idx_external_sources_scope'"
            ).fetchone()
        self.assertIsNotNone(index)

    def test_migration_step_failure_rolls_back_version_and_ledger(self) -> None:
        authority = AUTHORITIES_BY_KEY["memory"]
        path = self.data_root / authority.filename

        with patch.object(
            self.service,
            "_apply_version_1",
            side_effect=RuntimeError("simulated migration failure"),
        ):
            with self.assertRaisesRegex(
                SchemaMigrationError,
                "Schema migration failed",
            ):
                self.service._upgrade_authority(authority, path)

        with sqlite3.connect(path) as conn:
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                0,
            )
            ledger = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name = ?",
                (self.service.LEDGER_TABLE,),
            ).fetchone()
        self.assertIsNone(ledger)

    def test_incomplete_contract_is_not_stamped_as_current(self) -> None:
        novels_path = self.data_root / "novels.db"
        with sqlite3.connect(novels_path) as conn:
            conn.execute("ALTER TABLE novel_projects DROP COLUMN genre")

        with self.assertRaisesRegex(
            SchemaMigrationError,
            "missing_column:novel_projects.genre",
        ):
            self.service.upgrade(
                data_root=self.data_root,
                backup_dir=self.backup_dir,
                offline_confirmed=True,
            )

        for authority in AUTHORITIES_BY_KEY.values():
            with sqlite3.connect(self.data_root / authority.filename) as conn:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    0,
                )

    def test_tampered_ledger_and_newer_database_are_rejected(self) -> None:
        self.service.upgrade(
            data_root=self.data_root,
            backup_dir=self.backup_dir,
            offline_confirmed=True,
        )
        memory_path = self.data_root / "memory.db"
        with sqlite3.connect(memory_path) as conn:
            conn.execute(
                f"UPDATE {self.service.LEDGER_TABLE} SET checksum = 'bad'"
            )
        with self.assertRaisesRegex(
            SchemaMigrationError,
            "verification failed",
        ):
            self.service.verify(data_root=self.data_root)

        with sqlite3.connect(memory_path) as conn:
            conn.execute("PRAGMA user_version = 2")
        with patch.dict(os.environ, self._runtime_environment(), clear=False):
            with self.assertRaisesRegex(
                SchemaMigrationError,
                "newer",
            ):
                self.service.assert_no_newer_versions()
            with self.assertRaisesRegex(
                SchemaMigrationError,
                "incompatible",
            ):
                self.service.assert_runtime_compatible()

    def test_runtime_accepts_legacy_and_current_contracts(self) -> None:
        with patch.dict(os.environ, self._runtime_environment(), clear=False):
            self.service.assert_runtime_compatible()
            self.service.upgrade(
                data_root=self.data_root,
                backup_dir=self.backup_dir,
                offline_confirmed=True,
            )
            self.service.assert_runtime_compatible()

    def test_cli_status_upgrade_and_verify(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = schema_cli_main(
                ["status", "--data-root", str(self.data_root)]
            )
        self.assertEqual(exit_code, 0)
        self.assertFalse(json.loads(output.getvalue())["ready"])

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = schema_cli_main(
                [
                    "upgrade",
                    "--data-root",
                    str(self.data_root),
                    "--backup-dir",
                    str(self.backup_dir),
                    "--confirm-offline",
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["target_version"], 1)

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = schema_cli_main(
                ["verify", "--data-root", str(self.data_root)]
            )
        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(output.getvalue())["ready"])


if __name__ == "__main__":
    unittest.main()
