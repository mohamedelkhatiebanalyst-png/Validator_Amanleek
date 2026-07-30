from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

import pandas as pd

from .models import RowValidation, SchemaCheck, Severity, ValidationIssue, WorkbookStructure
from .schema import ValidationSchema


MAX_ISSUES_PER_RULE = 100


def normalize_header(value: Any) -> str:
    return "" if value is None else str(value).strip()


def blank_mask(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def validate_schema(
    headers: Iterable[str],
    schema: ValidationSchema,
) -> SchemaCheck:
    normalized_headers = tuple(headers)
    errors: list[str] = []
    warnings: list[str] = []

    duplicates = sorted(
        header
        for header, count in Counter(normalized_headers).items()
        if header and count > 1
    )
    if duplicates:
        errors.append("Duplicate column headers: " + ", ".join(duplicates))

    missing = [
        column
        for column in schema.required_columns
        if column not in schema.optional_columns and column not in normalized_headers
    ]
    if missing:
        errors.append("Missing required columns: " + ", ".join(missing))

    approved_set = set(schema.approved_columns)
    actual_order = [column for column in normalized_headers if column in approved_set]
    expected_order = [
        column for column in schema.approved_columns if column in normalized_headers
    ]
    if actual_order != expected_order:
        mismatches = _order_mismatches(actual_order, expected_order)
        errors.append(
            "The approved columns are not in the confirmed relative order:\n"
            + "\n".join(mismatches[:15])
            + ("\n..." if len(mismatches) > 15 else "")
        )

    extras = tuple(
        column
        for column in normalized_headers
        if column and column not in approved_set
    )
    if extras:
        warnings.append("Extra columns found: " + ", ".join(extras))

    return SchemaCheck(tuple(errors), tuple(warnings), extras)


def _order_mismatches(actual: list[str], expected: list[str]) -> list[str]:
    details: list[str] = []
    for position, expected_header in enumerate(expected, start=1):
        found = actual[position - 1] if position <= len(actual) else "<missing>"
        if found != expected_header:
            details.append(
                f"Approved position {position}: expected '{expected_header}', "
                f"found '{found}'"
            )
    return details


def repairable_missing_columns(
    headers: Iterable[str],
    schema: ValidationSchema,
) -> tuple[str, ...]:
    normalized_headers = tuple(headers)
    non_blank = tuple(header for header in normalized_headers if header)
    if len(non_blank) != len(set(non_blank)):
        return ()

    return tuple(
        column
        for column in schema.required_columns
        if column not in schema.optional_columns and column not in normalized_headers
    )


def can_reorder_columns(
    headers: Iterable[str],
    schema: ValidationSchema,
) -> bool:
    normalized_headers = tuple(headers)
    non_blank = tuple(header for header in normalized_headers if header)
    if len(non_blank) != len(set(non_blank)):
        return False
    if not all(
        normalized_headers.count(column) == 1
        for column in schema.required_columns
        if column not in schema.optional_columns
    ):
        return False

    approved = set(schema.approved_columns)
    actual = [column for column in normalized_headers if column in approved]
    expected = [column for column in schema.approved_columns if column in normalized_headers]
    return actual != expected


def reorder_columns(data: pd.DataFrame, schema: ValidationSchema) -> pd.DataFrame:
    approved = [
        column for column in schema.approved_columns if column in data.columns
    ]
    extras = [column for column in data.columns if column not in schema.approved_columns]
    return data.loc[:, approved + extras].copy()


def validate_rows(data: pd.DataFrame, schema: ValidationSchema) -> RowValidation:
    cleaned = _trim_strings(data)
    warnings: list[str] = []
    issues: list[ValidationIssue] = []

    empty_rows = _empty_row_mask(cleaned)
    removed_rows = int(empty_rows.sum())
    cleaned = cleaned.loc[~empty_rows].copy()
    if removed_rows:
        warnings.append(f"Removed {removed_rows} completely empty row(s).")

    if cleaned.empty:
        return RowValidation(
            errors=("The worksheet contains no usable data rows.",),
            warnings=tuple(warnings),
            issues=(),
            cleaned_data=cleaned,
        )

    _check_required_values(cleaned, schema, warnings, issues)
    _check_individual_number(cleaned, warnings, issues)
    _check_birth_year(cleaned, warnings, issues)
    _normalize_text_columns(cleaned, schema.text_columns)
    _check_duplicate_key(cleaned, schema.duplicate_key, warnings, issues)

    selected_issues = tuple(
        issue for issue in issues if issue.column in schema.row_issue_columns
    )
    return RowValidation((), tuple(warnings), selected_issues, cleaned)


def issues_dataframe(issues: Iterable[ValidationIssue]) -> pd.DataFrame:
    return pd.DataFrame(issue.as_record() for issue in issues)


def describe_structure_difference(
    reference: WorkbookStructure,
    candidate: WorkbookStructure,
) -> str:
    expected_sheets = [sheet.name for sheet in reference]
    found_sheets = [sheet.name for sheet in candidate]
    if found_sheets != expected_sheets:
        return (
            f"Sheet sequence differs: expected {expected_sheets}, "
            f"found {found_sheets}."
        )

    for expected_sheet, found_sheet in zip(reference, candidate):
        if found_sheet.headers == expected_sheet.headers:
            continue
        missing = list(
            (Counter(expected_sheet.headers) - Counter(found_sheet.headers)).elements()
        )
        unexpected = list(
            (Counter(found_sheet.headers) - Counter(expected_sheet.headers)).elements()
        )
        if missing or unexpected:
            parts: list[str] = []
            if len(found_sheet.headers) != len(expected_sheet.headers):
                parts.append(
                    f"Sheet '{expected_sheet.name}' has {len(found_sheet.headers)} "
                    f"columns; expected {len(expected_sheet.headers)}."
                )
            if missing:
                parts.append("Missing column(s): " + _display_headers(missing) + ".")
            if unexpected:
                parts.append(
                    "Unexpected column(s): " + _display_headers(unexpected) + "."
                )
            return " ".join(parts)

        for position, (expected, found) in enumerate(
            zip(expected_sheet.headers, found_sheet.headers), start=1
        ):
            if found != expected:
                return (
                    f"Sheet '{expected_sheet.name}', column {position}: expected "
                    f"'{expected}', found '{found}'."
                )
    return "Structure matches the reference workbook."


def _trim_strings(data: pd.DataFrame) -> pd.DataFrame:
    cleaned = data.copy()
    return cleaned.apply(
        lambda column: column.map(
            lambda value: value.strip() if isinstance(value, str) else value
        )
    )


def _empty_row_mask(data: pd.DataFrame) -> pd.Series:
    blank_cells = data.isna() | data.astype(str).apply(
        lambda column: column.str.strip().eq("")
    )
    return blank_cells.all(axis=1)


def _check_required_values(
    data: pd.DataFrame,
    schema: ValidationSchema,
    warnings: list[str],
    issues: list[ValidationIssue],
) -> None:
    for column in schema.required_columns:
        if column in schema.optional_columns:
            continue
        if column not in schema.row_issue_columns:
            continue
        if column not in data.columns:
            continue
        mask = blank_mask(data[column])
        count = int(mask.sum())
        if not count:
            continue
        warnings.append(f"{column}: {count} empty required cell(s).")
        for index in data.index[mask][:MAX_ISSUES_PER_RULE]:
            issues.append(
                ValidationIssue(int(index) + 2, column, "Empty required value")
            )


def _check_individual_number(
    data: pd.DataFrame,
    warnings: list[str],
    issues: list[ValidationIssue],
) -> None:
    column = "INDIVIDUAL#"
    if column not in data.columns:
        return
    non_blank = ~blank_mask(data[column])
    numeric = pd.to_numeric(data.loc[non_blank, column], errors="coerce")
    invalid_indexes = numeric.index[numeric.isna()]
    if not len(invalid_indexes):
        return
    warnings.append(f"{column}: {len(invalid_indexes)} non-numeric value(s).")
    for index in invalid_indexes[:MAX_ISSUES_PER_RULE]:
        issues.append(
            ValidationIssue(
                int(index) + 2,
                column,
                f"Expected a number, found '{data.at[index, column]}'",
            )
        )


def _check_birth_year(
    data: pd.DataFrame,
    warnings: list[str],
    issues: list[ValidationIssue],
) -> None:
    column = "DATE OF BIRTH"
    if column not in data.columns:
        return
    non_blank = ~blank_mask(data[column])
    years = data.loc[non_blank, column].astype(str).str.strip()
    years = years.str.replace(r"\.0$", "", regex=True)
    invalid_indexes = years.index[~years.str.fullmatch(r"\d{4}")]
    if not len(invalid_indexes):
        return
    warnings.append(
        f"{column}: {len(invalid_indexes)} value(s) are not four-digit years."
    )
    for index in invalid_indexes[:MAX_ISSUES_PER_RULE]:
        issues.append(
            ValidationIssue(
                int(index) + 2,
                column,
                f"Expected a four-digit year, found '{data.at[index, column]}'",
            )
        )


def _normalize_text_columns(data: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in data.columns:
            data[column] = data[column].map(
                lambda value: "" if pd.isna(value) else str(value).strip()
            )


def _check_duplicate_key(
    data: pd.DataFrame,
    key: tuple[str, ...],
    warnings: list[str],
    issues: list[ValidationIssue],
) -> None:
    if not all(column in data.columns for column in key):
        return
    mask = data.duplicated(subset=list(key), keep=False)
    count = int(mask.sum())
    if not count:
        return
    key_label = " + ".join(key)
    warnings.append(
        f"{count} row(s) share the same {key_label} key. No rows were deleted."
    )
    for index in data.index[mask][:MAX_ISSUES_PER_RULE]:
        issues.append(
            ValidationIssue(
                int(index) + 2,
                key_label,
                "Duplicate provisional claim/member key",
                Severity.WARNING,
            )
        )


def _display_headers(headers: Iterable[str]) -> str:
    return ", ".join(header or "<blank>" for header in headers)
