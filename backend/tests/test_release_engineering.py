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
        self._write("backend/Dockerfile", "FROM python:3.12-slim\n")
        self._write("backend/.dockerignore", "__pycache__/\n")
        self._write("backend/pyproject.toml", "[project]\nname='fixture'\n")
        self._write("frontend/package.json", json.dumps({"version": "1.2.3-alpha.4"}))
        self._write(
            "frontend/package-lock.json",
            json.dumps(
                {
                    "version": "1.2.3-alpha.4",
                    "packages": {"": {"version": "1.2.3-alpha.4"}},
                }
            ),
        )
        self._write("frontend/Dockerfile", "FROM nginx:alpine\n")
        self._write("frontend/index.html", "<div id='app'></div>\n")
        self._write("frontend/nginx.conf", "server {}\n")
        self._write("frontend/vite.config.js", "export default {}\n")
        self._write("frontend/src/main.js", "console.log('fixture')\n")
        self._write("docker-compose.yml", "services:\n  backend:\n    build:\n      context: ./backend\n")
        self._write("docker-compose.worker.yml", "services: {}\n")
        self._write(".env.example", "AUTH_ENABLED=false\n")
        self._write("README.md", "# Fixture\n")
        self._write("docs/operations/RELEASE.md", "release\n")
        self._write("scripts/release.ps1", "Write-Output ok\n")
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

    def test_mismatched_frontend_or_lock_version_fails_closed(self) -> None:
        self._write("frontend/package.json", json.dumps({"version": "1.2.3"}))
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
            self.assertIn("frontend/index.html", names)
            self.assertIn("frontend/vite.config.js", names)
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


if __name__ == "__main__":
    unittest.main()
