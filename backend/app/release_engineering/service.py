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
_LOCKED_REQUIREMENT = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)$"
)
_DIRECT_REQUIREMENT = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^]]+\])?"
)
_IMAGE_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_ACTION_PIN = re.compile(
    r"^\s*-?\s*uses:\s*([^@\s]+)@([0-9a-f]{40})(?:\s+#.*)?$"
)
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

    @staticmethod
    def _canonical_package_name(value: str) -> str:
        return re.sub(r"[-_.]+", "-", value).lower()

    def dependency_contract(self) -> dict[str, Any]:
        lock_path = self.repo_root / "backend/requirements.lock"
        try:
            lock_bytes = lock_path.read_bytes()
            lock_text = lock_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ReleaseValidationError(
                "Backend dependency lock is missing or invalid."
            ) from exc

        locked: dict[str, str] = {}
        lock_order: list[str] = []
        for raw in lock_text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = _LOCKED_REQUIREMENT.fullmatch(line)
            if match is None:
                raise ReleaseValidationError(
                    "Backend dependency lock must use exact name==version pins."
                )
            name = self._canonical_package_name(match.group(1))
            if name in locked:
                raise ReleaseValidationError(
                    "Backend dependency lock contains duplicate packages."
                )
            locked[name] = match.group(2)
            lock_order.append(name)
        if not locked or lock_order != sorted(lock_order):
            raise ReleaseValidationError(
                "Backend dependency lock must be non-empty and sorted."
            )

        try:
            metadata = tomllib.loads(
                (self.repo_root / "backend/pyproject.toml").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ReleaseValidationError(
                "Backend package metadata is invalid."
            ) from exc
        direct_names: list[str] = []
        for requirement in metadata.get("project", {}).get("dependencies", []):
            declaration = str(requirement).strip()
            match = _DIRECT_REQUIREMENT.match(declaration)
            if match is None:
                raise ReleaseValidationError(
                    "Backend direct dependency declaration is invalid."
                )
            name = self._canonical_package_name(match.group(1))
            direct_names.append(name)
            exact = re.search(r"==\s*([A-Za-z0-9][A-Za-z0-9.!+_-]*)", declaration)
            if exact is not None and locked.get(name) != exact.group(1):
                raise ReleaseValidationError(
                    "Backend dependency lock violates an exact direct pin."
                )
        missing = sorted(set(direct_names) - set(locked))
        if missing:
            raise ReleaseValidationError(
                "Backend dependency lock is missing direct packages: "
                + ", ".join(missing)
            )

        try:
            requirements_alias = (
                self.repo_root / "backend/requirements.txt"
            ).read_text(encoding="utf-8")
        except OSError as exc:
            raise ReleaseValidationError(
                "Backend requirements compatibility entry point is missing."
            ) from exc
        alias_lines = [
            item.strip()
            for item in requirements_alias.splitlines()
            if item.strip() and not item.lstrip().startswith("#")
        ]
        if alias_lines != ["-r requirements.lock"]:
            raise ReleaseValidationError(
                "Backend requirements.txt must delegate only to requirements.lock."
            )

        frontend_lock_path = self.repo_root / "frontend/package-lock.json"
        frontend_lock = self._read_json("frontend/package-lock.json")
        if frontend_lock.get("lockfileVersion") != 3:
            raise ReleaseValidationError(
                "Frontend package lock format must be version 3."
            )
        frontend_packages = frontend_lock.get("packages")
        if not isinstance(frontend_packages, dict):
            raise ReleaseValidationError("Frontend package lock is invalid.")
        registry_packages = 0
        for name, value in frontend_packages.items():
            if not name:
                continue
            if not isinstance(value, dict):
                raise ReleaseValidationError("Frontend package lock is invalid.")
            if value.get("link"):
                continue
            registry_packages += 1
            if not all(value.get(key) for key in ("version", "resolved", "integrity")):
                raise ReleaseValidationError(
                    "Frontend package lock contains an unpinned package."
                )

        image_refs = self._pinned_image_refs()
        action_count = self._pinned_action_count()
        return {
            "backend_lock_sha256": _sha256(lock_bytes),
            "backend_locked_packages": len(locked),
            "backend_direct_packages": len(set(direct_names)),
            "frontend_lock_sha256": _sha256(frontend_lock_path.read_bytes()),
            "frontend_locked_packages": registry_packages,
            "pinned_images": image_refs,
            "pinned_github_actions": action_count,
        }

    def _pinned_image_refs(self) -> dict[str, str]:
        refs: dict[str, str] = {}
        for relative in ("backend/Dockerfile", "frontend/Dockerfile"):
            try:
                text = (self.repo_root / relative).read_text(encoding="utf-8")
            except OSError as exc:
                raise ReleaseValidationError(
                    f"Release Dockerfile is missing: {relative}"
                ) from exc
            for index, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped.upper().startswith("FROM "):
                    continue
                ref = stripped.split()[1]
                if _IMAGE_DIGEST.fullmatch(ref) is None:
                    raise ReleaseValidationError(
                        f"Container base image is not digest-pinned: {relative}:{index}"
                    )
                refs[f"{relative}:{index}"] = ref
        try:
            compose = (self.repo_root / "docker-compose.yml").read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            raise ReleaseValidationError("Compose configuration is missing.") from exc
        ollama = re.search(r"(?m)^\s*image:\s*(ollama/ollama\S*)\s*$", compose)
        if ollama is None or _IMAGE_DIGEST.fullmatch(ollama.group(1)) is None:
            raise ReleaseValidationError(
                "Ollama image must be pinned by SHA-256 digest."
            )
        refs["docker-compose.yml:ollama"] = ollama.group(1)

        backend = (self.repo_root / "backend/Dockerfile").read_text(
            encoding="utf-8"
        )
        if (
            "COPY requirements.lock ./" not in backend
            or "-r requirements.lock" not in backend
            or "python -m pip check" not in backend
            or "pip install --upgrade" in backend
            or "pip install --no-cache-dir ." in backend
        ):
            raise ReleaseValidationError(
                "Backend Dockerfile must install and check only the dependency lock."
            )
        return refs

    def _pinned_action_count(self) -> int:
        workflows = self.repo_root / ".github/workflows"
        try:
            paths = sorted(workflows.glob("*.yml")) + sorted(
                workflows.glob("*.yaml")
            )
        except OSError as exc:
            raise ReleaseValidationError("GitHub workflows are unavailable.") from exc
        count = 0
        for path in paths:
            workflow_text = path.read_text(encoding="utf-8")
            if "${{ runner.temp }}" in workflow_text:
                raise ReleaseValidationError(
                    "GitHub workflow runner.temp context is not allowed; "
                    "use runner-local paths that are valid in job-level env: "
                    f"{path.name}"
                )
            for index, line in enumerate(workflow_text.splitlines(), start=1):
                if "uses:" not in line:
                    continue
                match = _ACTION_PIN.fullmatch(line)
                if match is None:
                    raise ReleaseValidationError(
                        "GitHub Action is not commit-pinned: "
                        f"{path.name}:{index}"
                    )
                count += 1
        if count == 0:
            raise ReleaseValidationError("No pinned GitHub Actions were found.")
        return count

    def compatibility_matrix(self, version: str | None = None) -> dict[str, Any]:
        value = self._read_json("release-compatibility.json")
        if (
            value.get("format") != "novelforge-release-compatibility"
            or value.get("format_version") != 1
        ):
            raise ReleaseValidationError(
                "Release compatibility matrix format is unsupported."
            )
        release_version = str(value.get("release_version") or "")
        if version is not None and release_version != version:
            raise ReleaseValidationError(
                "Release compatibility matrix version does not match."
            )
        schema = value.get("schema")
        if not isinstance(schema, dict):
            raise ReleaseValidationError(
                "Release compatibility schema policy is invalid."
            )
        minimum = schema.get("minimum_runtime_version")
        current = schema.get("current_version")
        maximum = schema.get("maximum_runtime_version")
        from app.schema_version import CURRENT_SCHEMA_VERSION

        if (
            not all(type(item) is int for item in (minimum, current, maximum))
            or not minimum <= current <= maximum
            or current != CURRENT_SCHEMA_VERSION
        ):
            raise ReleaseValidationError(
                "Release compatibility schema versions are invalid."
            )
        upgrade = value.get("upgrade")
        rollback = value.get("rollback")
        if not isinstance(upgrade, list) or not isinstance(rollback, list):
            raise ReleaseValidationError(
                "Release compatibility paths are invalid."
            )
        if len({item.get("from_version") for item in upgrade if isinstance(item, dict)}) != len(upgrade):
            raise ReleaseValidationError("Upgrade paths must be unique.")
        if len({item.get("to_version") for item in rollback if isinstance(item, dict)}) != len(rollback):
            raise ReleaseValidationError("Rollback paths must be unique.")
        for item in upgrade:
            if (
                not isinstance(item, dict)
                or not _VERSION.fullmatch(str(item.get("from_version") or ""))
                or type(item.get("from_schema_version")) is not int
                or not minimum <= item.get("from_schema_version") <= maximum
                or item.get("decision") not in {"direct", "migrate"}
                or item.get("backup_required") is not True
            ):
                raise ReleaseValidationError("Upgrade path is invalid.")
        for item in rollback:
            if (
                not isinstance(item, dict)
                or not _VERSION.fullmatch(str(item.get("to_version") or ""))
                or type(item.get("maximum_schema_version")) is not int
                or not minimum <= item.get("maximum_schema_version") <= current
                or item.get("compatible_decision") != "direct"
                or item.get("newer_schema_decision") != "restore_backup"
                or item.get("backup_required") is not True
            ):
                raise ReleaseValidationError("Rollback path is invalid.")
        if value.get("unknown_path_decision") != "blocked":
            raise ReleaseValidationError(
                "Unknown release paths must fail closed."
            )
        return value

    def assess_compatibility(
        self,
        *,
        operation: str,
        other_version: str,
        schema_version: int,
    ) -> dict[str, Any]:
        matrix = self.compatibility_matrix(self.versions()["backend"])
        if operation == "upgrade":
            item = next(
                (
                    candidate
                    for candidate in matrix["upgrade"]
                    if candidate["from_version"] == other_version
                ),
                None,
            )
            decision = (
                item["decision"]
                if item is not None
                and item["from_schema_version"] == schema_version
                else matrix["unknown_path_decision"]
            )
        elif operation == "rollback":
            item = next(
                (
                    candidate
                    for candidate in matrix["rollback"]
                    if candidate["to_version"] == other_version
                ),
                None,
            )
            if item is None:
                decision = matrix["unknown_path_decision"]
            elif schema_version <= item["maximum_schema_version"]:
                decision = item["compatible_decision"]
            else:
                decision = item["newer_schema_decision"]
        else:
            raise ReleaseValidationError(
                "Compatibility operation must be upgrade or rollback."
            )
        return {
            "result": "ok",
            "operation": operation,
            "release_version": matrix["release_version"],
            "other_version": other_version,
            "schema_version": schema_version,
            "decision": decision,
            "backup_required": decision != "blocked",
        }

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

    def readiness_contract(
        self,
        version: str | None = None,
    ) -> dict[str, Any]:
        value = self._read_json("release-readiness.json")
        if (
            value.get("format") != "novelforge-release-readiness"
            or value.get("format_version") != 1
        ):
            raise ReleaseValidationError(
                "Release readiness contract format is unsupported."
            )
        release_version = str(value.get("release_version") or "")
        baseline_version = str(value.get("baseline_version") or "")
        if (
            _VERSION.fullmatch(release_version) is None
            or _VERSION.fullmatch(baseline_version) is None
            or release_version == baseline_version
        ):
            raise ReleaseValidationError(
                "Release readiness version policy is invalid."
            )
        if version is not None and release_version != version:
            raise ReleaseValidationError(
                "Release readiness version does not match."
            )

        required = value.get("required_acceptance")
        if not isinstance(required, list) or not required:
            raise ReleaseValidationError(
                "Release readiness acceptance requirements are invalid."
            )
        normalized: list[dict[str, str]] = []
        seen_sprints: set[str] = set()
        for item in required:
            if not isinstance(item, dict) or set(item) != {
                "sprint",
                "capability",
            }:
                raise ReleaseValidationError(
                    "Release readiness acceptance requirement is invalid."
                )
            sprint = str(item.get("sprint") or "")
            capability = str(item.get("capability") or "")
            if (
                not sprint
                or len(sprint) > 32
                or re.fullmatch(r"[a-z0-9_]+", capability) is None
                or sprint in seen_sprints
            ):
                raise ReleaseValidationError(
                    "Release readiness acceptance requirements must be unique."
                )
            seen_sprints.add(sprint)
            normalized.append(
                {"sprint": sprint, "capability": capability}
            )

        journey_sprint = str(value.get("journey_sprint") or "")
        checks = value.get("required_journey_checks")
        if (
            journey_sprint not in seen_sprints
            or not isinstance(checks, list)
            or not checks
            or any(
                not isinstance(item, str)
                or re.fullmatch(r"[a-z0-9_]+", item) is None
                for item in checks
            )
            or len(set(checks)) != len(checks)
        ):
            raise ReleaseValidationError(
                "Release readiness product journey policy is invalid."
            )
        if value.get("hosted_release_required") is not True:
            raise ReleaseValidationError(
                "Hosted release must remain a formal distribution gate."
            )
        return {
            **value,
            "required_acceptance": normalized,
            "required_journey_checks": list(checks),
        }

    def _all_acceptance_values(self) -> list[dict[str, Any]]:
        data_dir = self.repo_root / "data"
        records: list[dict[str, Any]] = []
        if not data_dir.is_dir():
            return records
        for path in sorted(data_dir.glob("sprint*_acceptance.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            records.append(
                {
                    "path": path.relative_to(self.repo_root).as_posix(),
                    "value": value,
                }
            )
        return records

    def go_no_go(
        self,
        *,
        expected_version: str | None = None,
    ) -> dict[str, Any]:
        status = self.validate(expected_version=expected_version)
        version = status["version"]
        contract = self.readiness_contract(version)
        records = self._all_acceptance_values()

        accepted: list[dict[str, str]] = []
        for requirement in contract["required_acceptance"]:
            matches = [
                record
                for record in records
                if record["value"].get("sprint") == requirement["sprint"]
                and record["value"].get("result") == "PASS"
                and _VERSION.fullmatch(
                    str(record["value"].get("version") or "")
                )
                is not None
            ]
            if not matches:
                raise ReleaseValidationError(
                    "Required PASS acceptance is missing: "
                    + requirement["sprint"]
                )
            selected = matches[-1]
            accepted.append(
                {
                    **requirement,
                    "path": selected["path"],
                    "version": str(selected["value"].get("version") or ""),
                }
            )

        journey_records = [
            record
            for record in records
            if record["value"].get("sprint") == contract["journey_sprint"]
            and record["value"].get("version") == version
            and record["value"].get("result") == "PASS"
        ]
        if len(journey_records) != 1:
            raise ReleaseValidationError(
                "Exactly one current-version PASS product journey is required."
            )
        journey_record = journey_records[0]
        journey = journey_record["value"].get("product_journey")
        journey_checks = (
            journey.get("checks") if isinstance(journey, dict) else None
        )
        if not isinstance(journey_checks, dict):
            raise ReleaseValidationError(
                "Product journey acceptance checks are missing."
            )
        failed_checks = [
            item
            for item in contract["required_journey_checks"]
            if journey_checks.get(item) is not True
        ]
        if failed_checks:
            raise ReleaseValidationError(
                "Product journey checks are not PASS: "
                + ", ".join(failed_checks)
            )

        automation = journey_record["value"].get("automation")
        if (
            not isinstance(automation, dict)
            or type(automation.get("hosted_ci_executed")) is not bool
            or type(automation.get("hosted_release_executed")) is not bool
        ):
            raise ReleaseValidationError(
                "Product journey automation evidence is missing."
            )
        if (
            journey_record["value"].get("production_data_modified") is not True
            or journey_record["value"].get("secrets_recorded") is not False
            or journey_record["value"].get("provider_endpoints_recorded")
            is not False
            or journey_record["value"].get("business_content_recorded")
            is not False
        ):
            raise ReleaseValidationError(
                "Product journey data-handling evidence is invalid."
            )
        hosted_ci = automation.get("hosted_ci_executed") is True
        hosted_release = automation.get("hosted_release_executed") is True
        distribution_decision = (
            "go"
            if hosted_ci and hosted_release
            else "pending_hosted_release"
        )
        return {
            "result": "ok",
            "version": version,
            "tag": f"v{version}",
            "baseline_version": contract["baseline_version"],
            "local_decision": "go",
            "distribution_decision": distribution_decision,
            "hosted_ci_executed": hosted_ci,
            "hosted_release_executed": hosted_release,
            "required_acceptance": accepted,
            "journey_acceptance": journey_record["path"],
            "journey_checks": {
                item: True
                for item in contract["required_journey_checks"]
            },
        }

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
        dependencies = self.dependency_contract()
        compatibility = self.compatibility_matrix(version)
        return {
            "result": "ok",
            "version": version,
            "tag": f"v{version}",
            "versions": versions,
            "acceptance": records,
            "compose_portable": True,
            "dependencies": dependencies,
            "compatibility": {
                "schema": compatibility["schema"],
                "upgrade_paths": len(compatibility["upgrade"]),
                "rollback_paths": len(compatibility["rollback"]),
                "unknown_path_decision": compatibility[
                    "unknown_path_decision"
                ],
            },
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
            "backend/requirements.lock",
            "backend/requirements.txt",
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
            "release-compatibility.json",
            "release-readiness.json",
            ".github/dependabot.yml",
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
        readiness = None
        if "-" not in version:
            readiness = self.go_no_go(expected_version=version)
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
        if readiness is not None:
            manifest["readiness"] = readiness
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
            "readiness": readiness,
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
