from __future__ import annotations

import hashlib
import io
import json
import re
import tomllib
import zipfile

from pathlib import Path, PurePosixPath
from typing import Any


RELEASE_FORMAT = "novelforge-source-release"
RELEASE_FORMAT_VERSION = 1
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
_BACKEND_VERSION = re.compile(
    r'^APP_VERSION\s*=\s*"([^"]+)"\s*$',
    re.MULTILINE,
)
_ABSOLUTE_WINDOWS = re.compile(r"(?im)^\s*context:\s*[A-Za-z]:[\\/]")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class ReleaseValidationError(RuntimeError):
    pass


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ReleaseEngineeringService:
    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def _read_json(self, relative: str) -> dict[str, Any]:
        path = self.repo_root / relative
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseValidationError(
                f"Invalid release metadata file: {relative}"
            ) from exc
        if not isinstance(value, dict):
            raise ReleaseValidationError(
                f"Release metadata must be an object: {relative}"
            )
        return value

    def versions(self) -> dict[str, str]:
        version_path = self.repo_root / "backend/app/version.py"
        try:
            backend_text = version_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReleaseValidationError("Backend version file is missing.") from exc
        match = _BACKEND_VERSION.search(backend_text)
        if match is None:
            raise ReleaseValidationError("Backend APP_VERSION is invalid.")
        package_metadata_path = self.repo_root / "backend/pyproject.toml"
        try:
            package_metadata = tomllib.loads(
                package_metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ReleaseValidationError(
                "Backend package metadata is invalid."
            ) from exc
        package = self._read_json("frontend/package.json")
        lock = self._read_json("frontend/package-lock.json")
        lock_root = lock.get("packages", {}).get("", {})
        values = {
            "backend": match.group(1),
            "backend_package": str(
                package_metadata.get("project", {}).get("version") or ""
            ),
            "frontend": str(package.get("version") or ""),
            "frontend_lock": str(lock.get("version") or ""),
            "frontend_lock_root": str(lock_root.get("version") or ""),
        }
        if any(not _VERSION.fullmatch(value) for value in values.values()):
            raise ReleaseValidationError("A release version is malformed.")
        return values

    def _acceptance_records(self, version: str) -> list[dict[str, Any]]:
        data_dir = self.repo_root / "data"
        records: list[dict[str, Any]] = []
        if data_dir.is_dir():
            for path in sorted(data_dir.glob("sprint*_acceptance.json")):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(value, dict)
                    and value.get("version") == version
                ):
                    records.append(
                        {
                            "path": path.relative_to(self.repo_root).as_posix(),
                            "sprint": str(value.get("sprint") or ""),
                            "result": str(value.get("result") or ""),
                        }
                    )
        return records

    def validate(
        self,
        *,
        expected_version: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        versions = self.versions()
        unique = set(versions.values())
        if len(unique) != 1:
            raise ReleaseValidationError(
                "Backend application/package, Frontend and lockfile versions "
                "do not match."
            )
        version = versions["backend"]
        if expected_version is not None and expected_version != version:
            raise ReleaseValidationError(
                f"Expected version {expected_version}, found {version}."
            )
        if tag is not None and tag != f"v{version}":
            raise ReleaseValidationError(
                f"Tag {tag} does not match release version v{version}."
            )

        compose = (self.repo_root / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        if _ABSOLUTE_WINDOWS.search(compose):
            raise ReleaseValidationError(
                "Compose build contexts must be repository-relative."
            )
        if "context: ./backend" not in compose:
            raise ReleaseValidationError(
                "Backend Compose build context must be ./backend."
            )

        records = self._acceptance_records(version)
        if not records:
            raise ReleaseValidationError(
                f"No acceptance record exists for version {version}."
            )
        failed = [item["path"] for item in records if item["result"] != "PASS"]
        if failed:
            raise ReleaseValidationError(
                "Release acceptance is not PASS: " + ", ".join(failed)
            )
        return {
            "result": "ok",
            "version": version,
            "tag": f"v{version}",
            "versions": versions,
            "acceptance": records,
            "compose_portable": True,
        }

    @staticmethod
    def _wanted(path: PurePosixPath) -> bool:
        value = path.as_posix()
        if value in {
            ".env.example",
            "README.md",
            "docker-compose.yml",
            "docker-compose.worker.yml",
            "backend/Dockerfile",
            "backend/.dockerignore",
            "backend/pyproject.toml",
            "frontend/Dockerfile",
            "frontend/.dockerignore",
            "frontend/index.html",
            "frontend/nginx.conf",
            "frontend/package.json",
            "frontend/package-lock.json",
            "frontend/vite.config.js",
            "docs/CHANGELOG.md",
            "docs/CURRENT_IMPLEMENTATION.md",
            "docs/ROADMAP.md",
            "plugins/.gitkeep",
        }:
            return True
        prefixes = (
            ".github/workflows/",
            "backend/app/",
            "frontend/src/",
            "frontend/scripts/",
            "scripts/",
            "docs/operations/",
            "docs/sprints/",
        )
        return value.startswith(prefixes)

    def _source_files(self) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        for path in sorted(self.repo_root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = PurePosixPath(path.relative_to(self.repo_root).as_posix())
            if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if self._wanted(relative):
                files[relative.as_posix()] = path.read_bytes()
        return files

    @staticmethod
    def _write_zip(files: dict[str, bytes]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name, content in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content, compresslevel=9)
        return output.getvalue()

    def package(
        self,
        output_dir: str | Path,
        *,
        expected_version: str | None = None,
        tag: str | None = None,
        commit: str | None = None,
    ) -> dict[str, Any]:
        status = self.validate(expected_version=expected_version, tag=tag)
        version = status["version"]
        acceptance = [item["path"] for item in status["acceptance"]]
        payload = self._source_files()
        manifest = {
            "format": RELEASE_FORMAT,
            "format_version": RELEASE_FORMAT_VERSION,
            "version": version,
            "tag": f"v{version}",
            "commit": commit or None,
            "acceptance": status["acceptance"],
            "files": [
                {
                    "path": name,
                    "bytes": len(content),
                    "sha256": _sha256(content),
                }
                for name, content in sorted(payload.items())
            ],
        }
        archive = self._write_zip(
            {"release-manifest.json": _json_bytes(manifest), **payload}
        )
        target_dir = Path(output_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"novelforge-v{version}-source.zip"
        target.write_bytes(archive)
        digest = _sha256(archive)
        checksum = target_dir / "SHA256SUMS"
        checksum.write_text(
            f"{digest}  {target.name}\n",
            encoding="utf-8",
            newline="\n",
        )
        verified = self.verify(target)
        return {
            "result": "ok",
            "version": version,
            "artifact": str(target),
            "sha256": digest,
            "file_count": verified["file_count"],
            "acceptance": acceptance,
        }

    @staticmethod
    def verify(archive_path: str | Path) -> dict[str, Any]:
        path = Path(archive_path)
        try:
            with zipfile.ZipFile(path, "r") as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise ReleaseValidationError(
                        "Release artifact contains duplicate members."
                    )
                if any(
                    name.startswith("/") or ".." in PurePosixPath(name).parts
                    for name in names
                ):
                    raise ReleaseValidationError(
                        "Release artifact contains an unsafe member path."
                    )
                if "release-manifest.json" not in names:
                    raise ReleaseValidationError(
                        "Release manifest is missing."
                    )
                manifest = json.loads(
                    archive.read("release-manifest.json").decode("utf-8")
                )
                if (
                    manifest.get("format") != RELEASE_FORMAT
                    or manifest.get("format_version")
                    != RELEASE_FORMAT_VERSION
                ):
                    raise ReleaseValidationError(
                        "Release manifest format is unsupported."
                    )
                declared = {
                    item["path"]: item
                    for item in manifest.get("files", [])
                }
                if set(names) - {"release-manifest.json"} != set(declared):
                    raise ReleaseValidationError(
                        "Release members do not match the manifest."
                    )
                for name, item in declared.items():
                    content = archive.read(name)
                    if (
                        len(content) != item.get("bytes")
                        or _sha256(content) != item.get("sha256")
                    ):
                        raise ReleaseValidationError(
                            f"Release member verification failed: {name}"
                        )
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise ReleaseValidationError(
                "Release artifact cannot be verified."
            ) from exc
        return {
            "result": "ok",
            "version": manifest["version"],
            "tag": manifest["tag"],
            "file_count": len(declared) + 1,
            "sha256": _sha256(path.read_bytes()),
        }
