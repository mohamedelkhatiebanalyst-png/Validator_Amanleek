from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd


class Severity(StrEnum):
    WARNING = "Warning"


@dataclass(frozen=True)
class ValidationIssue:
    excel_row: int
    column: str
    description: str
    severity: Severity = Severity.WARNING

    def as_record(self) -> dict[str, int | str]:
        return {
            "Excel Row": self.excel_row,
            "Column": self.column,
            "Issue": self.description,
            "Severity": self.severity.value,
        }


@dataclass(frozen=True)
class SheetStructure:
    name: str
    headers: tuple[str, ...]


WorkbookStructure = tuple[SheetStructure, ...]


@dataclass(frozen=True)
class SchemaCheck:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    extra_columns: tuple[str, ...]


@dataclass(frozen=True)
class RowValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]
    cleaned_data: pd.DataFrame


@dataclass(frozen=True)
class RepairOptions:
    rename_from: str | None = None
    missing_columns: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()
    can_reorder: bool = False

    @property
    def has_blocking_repair(self) -> bool:
        return bool(self.rename_from or self.missing_columns or self.can_reorder)


@dataclass(frozen=True)
class WorkbookAssessment:
    structure: WorkbookStructure
    headers: tuple[str, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    repairs: RepairOptions

    @property
    def is_pending(self) -> bool:
        return bool(self.errors and self.repairs.has_blocking_repair)

class BatchStatus(StrEnum):
    MATCHES = "Matches"
    DIFFERENT = "Different"
    UNREADABLE = "Unreadable"


@dataclass(frozen=True)
class UploadedWorkbook:
    name: str
    content: bytes


@dataclass(frozen=True)
class BatchEntry:
    file_name: str
    status: BatchStatus
    detail: str
    structure: WorkbookStructure | None


@dataclass(frozen=True)
class BatchComparison:
    reference_file: str | None
    reference_structure: WorkbookStructure | None
    entries: tuple[BatchEntry, ...]

    @property
    def mismatches(self) -> tuple[BatchEntry, ...]:
        return tuple(
            entry for entry in self.entries if entry.status is not BatchStatus.MATCHES
        )

    @property
    def all_match(self) -> bool:
        return len(self.entries) >= 2 and not self.mismatches
