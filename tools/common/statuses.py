"""Shared execution statuses for QA tooling."""

from enum import StrEnum


class StepStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
