from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile

from pathlib import Path

from app.release_engineering.cli import main as release_main
from app.release_engineering.service import (
    ReleaseEngineeringService,
    ReleaseValidationError,
)


class ReleaseFixture:
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._write("backend/app/version.py", 'APP_VERSION = "1.2.3-alpha.4"\n')
        self._write("backend/app/main.py", "VALUE = 1\n")
        self._write(
            "backend/Dockerfile",
            "FROM python:3.12-slim@sha256:" + "a" * 64 + "\n"
            "COPY requirements.lock ./\n"
            "RUN python -m pip install --no-cache-dir "
            "-r requirements.lock && python -m pip check\n",
        )
        self._write("backend/.dockerignore", "__pycache__/\n")
        self._write(
            "backend/pyproject.toml",
            "[project]\nname='fixture'\nversion='1.2.3-alpha.4'\n",
        )
        self._write("backend/requirements.lock", "example-runtime==1.0.0\n")
        self._write(
            "backend/requirements.txt",
            "# Compatibility alias.\n-r requirements.lock\n",
        )
        self._write("frontend/package.json", json.dumps({"version": "1.2.3-alpha.4"}))
        self._write(
            "frontend/package-lock.json",
            json.dumps(
                {
                    "version": "1.2.3-alpha.4",
                    "lockfileVersion": 3,
                    "packages": {"": {"version": "1.2.3-alpha.4"}},
                }
            ),
        )
        self._write(
            "frontend/Dockerfile",
            "FROM node:22-alpine@sha256:" + "b" * 64 + " AS build\n"
            "FROM nginx:alpine@sha256:" + "c" * 64 + "\n",
        )
        self._write("frontend/index.html", "<div id='app'></div>\n")
        self._write("frontend/nginx.conf", "server {}\n")
        self._write("frontend/vite.config.js", "export default {}\n")
        self._write("frontend/src/main.js", "console.log('fixture')\n")
        self._write(
            "docker-compose.yml",
            "services:\n"
            "  backend:\n"
            "    build:\n"
            "      context: ./backend\n"
            "  ollama:\n"
            "    image: ollama/ollama@sha256:" + "d" * 64 + "\n",
        )
        self._write("docker-compose.worker.yml", "services: {}\n")
        self._write(
            ".github/workflows/ci.yml",
            "steps:\n  - uses: actions/checkout@" + "e" * 40 + " # v4.2.2\n",
        )
        self._write(".github/dependabot.yml", "version: 2\nupdates: []\n")
        self._write(".env.example", "AUTH_ENABLED=false\n")
        self._write("README.md", "# Fixture\n")
        self._write("docs/operations/RELEASE.md", "release\n")
        self._write("plugins/.gitkeep", "")
        self._write("scripts/release.ps1", "Write-Output ok\n")
        self._write(
            "release-compatibility.json",
            json.dumps(
                {
                    "format": "novelforge-release-compatibility",
                    "format_version": 1,
                    "release_version": "1.2.3-alpha.4",
                    "schema": {
                        "minimum_runtime_version": 0,
                        "current_version": 1,
                        "maximum_runtime_version": 1,
                    },
                    "upgrade": [
                        {
                            "from_version": "1.2.3-alpha.3",
                            "from_schema_version": 1,
                            "decision": "direct",
                            "backup_required": True,
                        }
                    ],
                    "rollback": [
                        {
                            "to_version": "1.2.3-alpha.3",
                            "maximum_schema_version": 1,
                            "compatible_decision": "direct",
                            "newer_schema_decision": "restore_backup",
                            "backup_required": True,
                        }
                    ],
                    "unknown_path_decision": "blocked",
                }
            ),
        )
        self._write(
            "data/sprint09d_acceptance.json",
            json.dumps(
                {
                    "sprint": "09D",
                    "version": "1.2.3-alpha.4",
                    "result": "PASS",
                }
            ),
        )
        self.service = ReleaseEngineeringService(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class ReleaseEngineeringTests(ReleaseFixture, unittest.TestCase):
    def test_matching_versions_tag_acceptance_and_portable_compose_pass(self) -> None:
        result = self.service.validate(
            expected_version="1.2.3-alpha.4",
            tag="v1.2.3-alpha.4",
        )
        self.assertEqual(result["version"], "1.2.3-alpha.4")
        self.assertTrue(result["compose_portable"])
        self.assertEqual(result["acceptance"][0]["result"], "PASS")
        self.assertEqual(result["dependencies"]["backend_locked_packages"], 1)
        self.assertEqual(result["dependencies"]["pinned_github_actions"], 1)
        self.assertEqual(result["compatibility"]["rollback_paths"], 1)

    def test_mismatched_frontend_or_lock_version_fails_closed(self) -> None:
        self._write("frontend/package.json", json.dumps({"version": "1.2.3"}))
        with self.assertRaisesRegex(ReleaseValidationError, "do not match"):
            self.service.validate()

    def test_mismatched_backend_package_version_fails_closed(self) -> None:
        self._write(
            "backend/pyproject.toml",
            "[project]\nname='fixture'\nversion='1.2.3-alpha.3'\n",
        )
        with self.assertRaisesRegex(ReleaseValidationError, "do not match"):
            self.service.validate()

    def test_tag_and_expected_version_must_match(self) -> None:
        with self.assertRaisesRegex(ReleaseValidationError, "Expected version"):
            self.service.validate(expected_version="9.9.9")
        with self.assertRaisesRegex(ReleaseValidationError, "does not match"):
            self.service.validate(tag="v1.2.3")

    def test_missing_or_failed_acceptance_is_rejected(self) -> None:
        acceptance = self.root / "data/sprint09d_acceptance.json"
        acceptance.unlink()
        with self.assertRaisesRegex(ReleaseValidationError, "No acceptance"):
            self.service.validate()
        self._write(
            "data/sprint09d_acceptance.json",
            json.dumps(
                {
                    "version": "1.2.3-alpha.4",
                    "result": "FAIL",
                }
            ),
        )
        with self.assertRaisesRegex(ReleaseValidationError, "not PASS"):
            self.service.validate()

    def test_absolute_windows_compose_context_is_rejected(self) -> None:
        self._write(
            "docker-compose.yml",
            "services:\n  backend:\n    build:\n      context: D:\\AI\\novel-ai\\backend\n",
        )
        with self.assertRaisesRegex(ReleaseValidationError, "repository-relative"):
            self.service.validate()

    def test_dependency_lock_and_compatibility_alias_fail_closed(self) -> None:
        self._write("backend/requirements.lock", "example-runtime>=1.0.0\n")
        with self.assertRaisesRegex(ReleaseValidationError, "exact name==version"):
            self.service.validate()
        self._write("backend/requirements.lock", "example-runtime==1.0.0\n")
        self._write(
            "backend/pyproject.toml",
            "[project]\nname='fixture'\nversion='1.2.3-alpha.4'\n"
            "dependencies=['example-runtime==2.0.0']\n",
        )
        with self.assertRaisesRegex(ReleaseValidationError, "exact direct pin"):
            self.service.validate()
        self._write(
            "backend/pyproject.toml",
            "[project]\nname='fixture'\nversion='1.2.3-alpha.4'\n",
        )
        self._write("backend/requirements.txt", "example-runtime==1.0.0\n")
        with self.assertRaisesRegex(ReleaseValidationError, "delegate only"):
            self.service.validate()

    def test_mutable_container_or_action_reference_fails_closed(self) -> None:
        self._write("frontend/Dockerfile", "FROM nginx:alpine\n")
        with self.assertRaisesRegex(ReleaseValidationError, "digest-pinned"):
            self.service.validate()
        self._write(
            "frontend/Dockerfile",
            "FROM nginx:alpine@sha256:" + "c" * 64 + "\n",
        )
        self._write(
            ".github/workflows/ci.yml",
            "steps:\n  - uses: actions/checkout@v4\n",
        )
        with self.assertRaisesRegex(ReleaseValidationError, "commit-pinned"):
            self.service.validate()

    def test_upgrade_and_rollback_matrix_is_fail_closed(self) -> None:
        upgraded = self.service.assess_compatibility(
            operation="upgrade",
            other_version="1.2.3-alpha.3",
            schema_version=1,
        )
        self.assertEqual(upgraded["decision"], "direct")
        unknown = self.service.assess_compatibility(
            operation="upgrade",
            other_version="1.2.3-alpha.2",
            schema_version=1,
        )
        self.assertEqual(unknown["decision"], "blocked")
        rollback = self.service.assess_compatibility(
            operation="rollback",
            other_version="1.2.3-alpha.3",
            schema_version=2,
        )
        self.assertEqual(rollback["decision"], "restore_backup")

    def test_package_is_deterministic_scoped_and_self_verifying(self) -> None:
        self._write("data/private.db", "must-not-ship")
        first = self.service.package(self.root / "dist-one")
        second = self.service.package(self.root / "dist-two")
        self.assertEqual(first["sha256"], second["sha256"])
        first_path = Path(first["artifact"])
        self.assertEqual(first_path.read_bytes(), Path(second["artifact"]).read_bytes())
        verified = self.service.verify(first_path)
        self.assertEqual(verified["version"], "1.2.3-alpha.4")
        with zipfile.ZipFile(first_path) as archive:
            names = set(archive.namelist())
            self.assertIn("release-manifest.json", names)
            self.assertIn("backend/app/main.py", names)
            self.assertIn("backend/.dockerignore", names)
            self.assertIn("backend/requirements.lock", names)
            self.assertIn("backend/requirements.txt", names)
            self.assertIn("frontend/index.html", names)
            self.assertIn("frontend/vite.config.js", names)
            self.assertIn("plugins/.gitkeep", names)
            self.assertIn("release-compatibility.json", names)
            self.assertIn(".github/dependabot.yml", names)
            self.assertNotIn("data/sprint09d_acceptance.json", names)
            self.assertNotIn("data/private.db", names)
            manifest = json.loads(archive.read("release-manifest.json"))
            self.assertEqual(
                manifest["acceptance"][0]["path"],
                "data/sprint09d_acceptance.json",
            )

    def test_tampered_artifact_is_rejected(self) -> None:
        result = self.service.package(self.root / "dist")
        source = Path(result["artifact"])
        target = self.root / "tampered.zip"
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as changed:
            for name in original.namelist():
                content = original.read(name)
                if name == "README.md":
                    content = b"tampered"
                changed.writestr(name, content)
        with self.assertRaisesRegex(ReleaseValidationError, "verification failed"):
            self.service.verify(target)

    def test_cli_validate_package_and_verify(self) -> None:
        self.assertEqual(
            release_main(
                [
                    "validate",
                    "--repo-root",
                    str(self.root),
                    "--tag",
                    "v1.2.3-alpha.4",
                ]
            ),
            0,
        )
        output = self.root / "cli-dist"
        self.assertEqual(
            release_main(
                [
                    "package",
                    "--repo-root",
                    str(self.root),
                    "--output-dir",
                    str(output),
                ]
            ),
            0,
        )
        artifact = output / "novelforge-v1.2.3-alpha.4-source.zip"
        self.assertEqual(release_main(["verify", str(artifact)]), 0)
        self.assertEqual(
            release_main(
                [
                    "assess",
                    "--repo-root",
                    str(self.root),
                    "--operation",
                    "rollback",
                    "--other-version",
                    "1.2.3-alpha.3",
                    "--schema-version",
                    "2",
                ]
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
