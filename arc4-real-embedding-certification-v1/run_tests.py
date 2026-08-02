"""Run the public Arc 4 unit suite and write a deterministic per-test receipt."""

from __future__ import annotations

import json
import platform
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULES = ("test_arc4lib", "test_release_asset")


class ReceiptResult(unittest.TestResult):
    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, dict[str, str]] = {}

    def startTest(self, test: unittest.case.TestCase) -> None:
        super().startTest(test)
        self.records[test.id()] = {"test": test.id(), "status": "running"}

    def addSuccess(self, test: unittest.case.TestCase) -> None:
        super().addSuccess(test)
        self.records[test.id()]["status"] = "PASS"

    def addFailure(self, test: unittest.case.TestCase, err: object) -> None:
        super().addFailure(test, err)
        self.records[test.id()].update(
            {"status": "FAIL", "detail": self._exc_info_to_string(err, test)}
        )

    def addError(self, test: unittest.case.TestCase, err: object) -> None:
        super().addError(test, err)
        self.records[test.id()].update(
            {"status": "ERROR", "detail": self._exc_info_to_string(err, test)}
        )

    def addSkip(self, test: unittest.case.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self.records[test.id()].update({"status": "SKIP", "detail": reason})


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = ReceiptResult()
    suite.run(result)
    payload = {
        "schema_version": "arc4-public-test-results-v1",
        "command": "py -3 run_tests.py",
        "python_version": platform.python_version(),
        "status": "PASS" if result.wasSuccessful() else "FAIL",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "tests": [result.records[name] for name in sorted(result.records)],
    }
    (HERE / "TEST-RESULTS.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({key: payload[key] for key in ("status", "tests_run", "failures", "errors", "skipped")}, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
