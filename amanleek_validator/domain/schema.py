from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ValidationSchema:
    expected_sheet: str
    required_columns: tuple[str, ...]
    optional_columns: frozenset[str]
    text_columns: frozenset[str]
    duplicate_key: tuple[str, ...]
    row_issue_columns: frozenset[str]
    individual_number_type: str
    birth_year_format: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ValidationSchema":
        schema = cls(
            expected_sheet=str(values["sheet_name"]),
            required_columns=tuple(values["required_columns_in_order"]),
            optional_columns=frozenset(values.get("optional_columns", ())),
            text_columns=frozenset(values.get("text_columns", ())),
            duplicate_key=tuple(values["duplicate_key"]),
            row_issue_columns=frozenset(values.get("row_issue_columns", ())),
            individual_number_type=str(values["individual_number_type"]),
            birth_year_format=str(values["birth_year_format"]),
        )
        schema._validate_configuration()
        return schema

    @property
    def approved_columns(self) -> tuple[str, ...]:
        return self.required_columns

    def _validate_configuration(self) -> None:
        if not self.expected_sheet:
            raise ValueError("sheet_name must not be empty")
        if len(self.required_columns) != len(set(self.required_columns)):
            raise ValueError("required_columns_in_order contains duplicate names")

        approved = set(self.required_columns)
        unknown_optional = self.optional_columns - approved
        unknown_text = self.text_columns - approved
        unknown_duplicate_keys = set(self.duplicate_key) - approved
        unknown_row_issue = self.row_issue_columns - approved
        unknown = (
            unknown_optional
            | unknown_text
            | unknown_duplicate_keys
            | unknown_row_issue
        )
        if unknown:
            raise ValueError(
                "Schema configuration references unknown columns: "
                + ", ".join(sorted(unknown))
            )
        if self.individual_number_type != "number":
            raise ValueError("individual_number_type must be 'number'")
        if self.birth_year_format != "YYYY":
            raise ValueError("birth_year_format must be 'YYYY'")
