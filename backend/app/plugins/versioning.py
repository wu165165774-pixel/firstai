from __future__ import annotations

import re

from dataclasses import dataclass
from functools import total_ordering


_SEMANTIC_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@total_ordering
@dataclass(frozen=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        release = (self.major, self.minor, self.patch)
        other_release = (other.major, other.minor, other.patch)
        if release != other_release:
            return release < other_release
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_numeric = left.isdigit()
            right_numeric = right.isdigit()
            if left_numeric and right_numeric:
                return int(left) < int(right)
            if left_numeric != right_numeric:
                return left_numeric
            return left < right
        return len(self.prerelease) < len(other.prerelease)


def parse_semantic_version(value: str) -> SemanticVersion:
    match = _SEMANTIC_VERSION.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError("version must use semantic version syntax")
    prerelease = tuple((match.group(4) or "").split("."))
    if prerelease == ("",):
        prerelease = ()
    if any(
        item.isdigit() and len(item) > 1 and item.startswith("0")
        for item in prerelease
    ):
        raise ValueError(
            "numeric prerelease identifiers must not have leading zeroes"
        )
    return SemanticVersion(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=prerelease,
    )
