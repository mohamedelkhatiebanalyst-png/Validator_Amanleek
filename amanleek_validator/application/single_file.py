from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from amanleek_validator.domain.models import (
    RepairOptions,
    RowValidation,
    WorkbookAssessment,
)
from amanleek_validator.domain.schema import ValidationSchema
from amanleek_validator.domain.dates import DATE_COLUMNS, CLAIM_DATETIME_FORMAT, parse_mixed_datetime
from amanleek_validator.domain.validation import (
    can_reorder_columns,
    repairable_missing_columns,
    reorder_columns,
    validate_rows,
    validate_schema,
)

from .ports import WorkbookPort


@dataclass(frozen=True)
class RepairResult:
    content: bytes
    affected_columns: tuple[str, ...] = ()


class SingleFileValidationService:
    def __init__(self, schema: ValidationSchema, workbooks: WorkbookPort) -> None:
        self.schema = schema
        self.workbooks = workbooks

    def assess(self, content: bytes) -> WorkbookAssessment:
        structure = self.workbooks.inspect(content)
        workbook_errors = self._workbook_errors(structure)
        rename_from = self._rename_candidate(structure)
        expected_sheet = next(
            (sheet for sheet in structure if sheet.name == self.schema.expected_sheet),
            None,
        )
        headers = expected_sheet.headers if expected_sheet else ()

        schema_check = (
            validate_schema(headers, self.schema)
            if expected_sheet is not None
            else None
        )
        errors = list(workbook_errors)
        warnings: list[str] = []
        extra_columns: tuple[str, ...] = ()
        if schema_check:
            errors.extend(schema_check.errors)
            warnings.extend(schema_check.warnings)
            extra_columns = schema_check.extra_columns

        repairs = RepairOptions(
            rename_from=rename_from,
            missing_columns=(
                repairable_missing_columns(headers, self.schema)
                if expected_sheet is not None and not workbook_errors
                else ()
            ),
            extra_columns=extra_columns if not workbook_errors else (),
            can_reorder=(
                can_reorder_columns(headers, self.schema)
                if headers and not workbook_errors
                else False
            ),
        )
        return WorkbookAssessment(
            structure=structure,
            headers=headers,
            errors=tuple(errors),
            warnings=tuple(warnings),
            repairs=repairs,
        )

    def validate_data(self, content: bytes, techsheet_name: str) -> RowValidation:
        data = self.workbooks.read_sheet(content, self.schema.expected_sheet)
        normalized_name = techsheet_name.strip()
        if not normalized_name:
            raise ValueError("Techsheet name is required")
        if "TECSHEET NAME" not in data.columns:
            raise ValueError("The workbook does not contain the TECSHEET NAME column")
        data["TECSHEET NAME"] = normalized_name
        return validate_rows(data, self.schema)

    def rename_sheet(self, content: bytes, current_name: str) -> RepairResult:
        repaired = self.workbooks.rename_single_sheet(
            content,
            current_name,
            self.schema.expected_sheet,
        )
        return RepairResult(repaired)

    def add_missing_columns(
        self,
        content: bytes,
        columns: tuple[str, ...],
    ) -> RepairResult:
        allowed = set(self.schema.required_columns) - set(self.schema.optional_columns)
        if any(column not in allowed for column in columns):
            raise ValueError("One or more requested columns are not required columns")
        data = self._read_normalized(content)
        for column in columns:
            if column not in data.columns:
                data[column] = pd.NA
        repaired = reorder_columns(data, self.schema)
        return RepairResult(
            self.workbooks.write_excel(repaired, self.schema.expected_sheet),
            columns,
        )

    def delete_extra_columns(
        self,
        content: bytes,
        columns: tuple[str, ...],
    ) -> RepairResult:
        data = self._read_normalized(content)
        approved = set(self.schema.approved_columns)
        safe_columns = tuple(
            column
            for column in columns
            if column in data.columns and column not in approved
        )
        repaired = data.drop(columns=list(safe_columns))
        return RepairResult(
            self.workbooks.write_excel(repaired, self.schema.expected_sheet),
            safe_columns,
        )

    def reorder(self, content: bytes) -> RepairResult:
        data = reorder_columns(self._read_normalized(content), self.schema)
        return RepairResult(
            self.workbooks.write_excel(data, self.schema.expected_sheet)
        )

    def template(self) -> bytes:
        empty = pd.DataFrame(columns=self.schema.approved_columns)
        return self.workbooks.write_excel(empty, self.schema.expected_sheet)

    def validation_report(self, issues: pd.DataFrame) -> bytes:
        return self.workbooks.write_excel(issues, "Validation Issues")

    def validated_csv(self, cleaned_data: pd.DataFrame) -> bytes:
        return self.workbooks.write_csv(cleaned_data)

    def validated_excel(self, cleaned_data: pd.DataFrame) -> bytes:
        return self.workbooks.write_excel(cleaned_data, self.schema.expected_sheet)

    def _read_normalized(self, content: bytes) -> pd.DataFrame:
        data = self.workbooks.read_sheet(content, self.schema.expected_sheet)
        data.columns = [str(column).strip() for column in data.columns]
        # Repairs create a new workbook with the default Excel epoch. Convert
        # recognized dates first so raw 1904-system serials retain their meaning.
        for column in DATE_COLUMNS:
            if column in data.columns:
                epoch = data.attrs.get("excel_epoch")
                parsed = (parse_mixed_datetime(data[column], epoch) if epoch is not None
                          else parse_mixed_datetime(data[column]))
                valid = parsed.notna()
                data[column] = data[column].astype(object)
                data.loc[valid, column] = parsed.loc[valid].dt.strftime(CLAIM_DATETIME_FORMAT)
        return data

    def _workbook_errors(self, structure: tuple) -> list[str]:
        sheet_names = [sheet.name for sheet in structure]
        errors: list[str] = []
        if len(sheet_names) != 1:
            errors.append(
                "The workbook must contain exactly one worksheet. Found: "
                + ", ".join(sheet_names)
            )
        if self.schema.expected_sheet not in sheet_names:
            errors.append(
                f"The worksheet must be named exactly '{self.schema.expected_sheet}'. "
                f"Found: {', '.join(sheet_names)}"
            )
        return errors

    def _rename_candidate(self, structure: tuple) -> str | None:
        if len(structure) != 1:
            return None
        only_sheet = structure[0].name
        return only_sheet if only_sheet != self.schema.expected_sheet else None
