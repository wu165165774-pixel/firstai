from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from app.release_engineering.runtime_lock import (
    RuntimeLockError,
    load_lock,
    verify_runtime_lock,
)


class DependencyRuntimeLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.lock = Path(self.temp.name) / "requirements.lock"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_sorted_lock_matches_installed_versions(self) -> None:
        self.lock.write_text(
            "# generated\nalpha-package==1.2.3\nbeta_package==4.5.6\n",
            encoding="utf-8",
        )
        result = verify_runtime_lock(
            self.lock,
            installed={"Alpha_Package": "1.2.3", "beta-package": "4.5.6"},
        )
        self.assertEqual(result["locked_packages"], 2)

    def test_ranges_duplicates_and_unsorted_locks_are_rejected(self) -> None:
        invalid_values = (
            "alpha>=1.0\n",
            "alpha==1.0\nalpha==1.0\n",
            "beta==1.0\nalpha==1.0\n",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                self.lock.write_text(value, encoding="utf-8")
                with self.assertRaises(RuntimeLockError):
                    load_lock(self.lock)

    def test_missing_unexpected_or_mismatched_runtime_fails_closed(self) -> None:
        self.lock.write_text("alpha==1.0\n", encoding="utf-8")
        invalid_values = (
            {},
            {"alpha": "1.0", "beta": "1.0"},
            {"alpha": "2.0"},
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(RuntimeLockError):
                    verify_runtime_lock(self.lock, installed=value)


if __name__ == "__main__":
    unittest.main()
