from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from amanleek_validator.application.single_file import SingleFileValidationService
from amanleek_validator.domain.validation import issues_dataframe


class BatchValidationStatus(StrEnum):
    VALIDATED = "Validated"
    NEEDS_REPAIR = "Needs repair"
    REJECTED = "Rejected"


@dataclass(frozen=True)
class BatchValidationInput:
    name: str
    content: bytes
    techsheet_name: str


@dataclass(frozen=True)
class BatchValidationEntry:
    file_name: str
    status: BatchValidationStatus
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    validated_excel: bytes | None = None
    validated_csv: bytes | None = None
    validation_report: bytes | None = None
    row_count: int = 0
    issue_count: int = 0


class BatchValidationService:
    """Apply the single-file rules independently to every batch item."""

    def __init__(self, single_files: SingleFileValidationService) -> None:
        self.single_files = single_files

    def validate(self, item: BatchValidationInput) -> BatchValidationEntry:
        if not item.techsheet_name.strip():
            return BatchValidationEntry(
                item.name,
                BatchValidationStatus.REJECTED,
                errors=("Techsheet name is required.",),
            )
        try:
            assessment = self.single_files.assess(item.content)
        except (OSError, ValueError, KeyError) as exc:
            return BatchValidationEntry(
                item.name,
                BatchValidationStatus.REJECTED,
                errors=(str(exc),),
            )
        if assessment.errors:
            return BatchValidationEntry(
                item.name,
                (
                    BatchValidationStatus.NEEDS_REPAIR
                    if assessment.is_pending
                    else BatchValidationStatus.REJECTED
                ),
                errors=assessment.errors,
                warnings=assessment.warnings,
            )
        try:
            rows = self.single_files.validate_data(
                item.content, item.techsheet_name
            )
        except (OSError, ValueError, KeyError) as exc:
            return BatchValidationEntry(
                item.name,
                BatchValidationStatus.REJECTED,
                errors=(str(exc),),
                warnings=assessment.warnings,
            )
        issues = issues_dataframe(rows.issues)
        if rows.errors:
            return BatchValidationEntry(
                item.name,
                BatchValidationStatus.REJECTED,
                errors=rows.errors,
                warnings=(*assessment.warnings, *rows.warnings),
                validation_report=(self.single_files.validation_report(issues)
                                   if not issues.empty else None),
                row_count=len(rows.cleaned_data),
                issue_count=len(rows.issues),
            )
        return BatchValidationEntry(
            item.name,
            BatchValidationStatus.VALIDATED,
            warnings=(*assessment.warnings, *rows.warnings),
            validated_excel=self.single_files.validated_excel(rows.cleaned_data),
            validated_csv=self.single_files.validated_csv(rows.cleaned_data),
            validation_report=(
                self.single_files.validation_report(issues)
                if not issues.empty
                else None
            ),
            row_count=len(rows.cleaned_data),
            issue_count=len(rows.issues),
        )
