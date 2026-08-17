from __future__ import annotations

import argparse
import importlib.metadata
import json
import re

from pathlib import Path
from typing import Mapping


_LOCKED_REQUIREMENT = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)$"
)
_BOOTSTRAP_PACKAGES = {"pip", "setuptools", "wheel"}


class RuntimeLockError(RuntimeError):
    pass


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def load_lock(path: str | Path) -> dict[str, str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeLockError("Dependency lock is unavailable.") from exc
    result: dict[str, str] = {}
    order: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCKED_REQUIREMENT.fullmatch(line)
        if match is None:
            raise RuntimeLockError("Dependency lock contains an invalid pin.")
        name = canonical_name(match.group(1))
        if name in result:
            raise RuntimeLockError("Dependency lock contains a duplicate package.")
        result[name] = match.group(2)
        order.append(name)
    if not result or order != sorted(order):
        raise RuntimeLockError("Dependency lock is empty or unsorted.")
    return result


def installed_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            continue
        name = canonical_name(raw_name)
        if name in _BOOTSTRAP_PACKAGES or name == "novelforge-backend":
            continue
        if name in result:
            raise RuntimeLockError(
                "Runtime contains duplicate installed distributions."
            )
        result[name] = distribution.version
    return result


def verify_runtime_lock(
    path: str | Path,
    *,
    installed: Mapping[str, str] | None = None,
) -> dict[str, object]:
    expected = load_lock(path)
    actual = (
        {canonical_name(name): version for name, version in installed.items()}
        if installed is not None
        else installed_versions()
    )
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    mismatched = sorted(
        name
        for name in set(expected) & set(actual)
        if expected[name] != actual[name]
    )
    if missing or unexpected or mismatched:
        raise RuntimeLockError(
            "Installed runtime does not match the dependency lock."
        )
    return {
        "result": "ok",
        "locked_packages": len(expected),
        "missing": 0,
        "unexpected": 0,
        "mismatched": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify installed Python distributions against a lock"
    )
    parser.add_argument("--lock", default="requirements.lock")
    args = parser.parse_args(argv)
    try:
        result = verify_runtime_lock(args.lock)
    except RuntimeLockError as exc:
        print(json.dumps({"result": "error", "error": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
