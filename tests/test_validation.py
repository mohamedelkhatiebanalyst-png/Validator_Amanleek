from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from amanleek_validator.application.single_file import SingleFileValidationService
from amanleek_validator.domain.schema import ValidationSchema
from amanleek_validator.domain.validation import validate_rows, validate_schema
from amanleek_validator.infrastructure.excel import OpenpyxlWorkbookAdapter


ROOT = Path(__file__).resolve().parents[1]


def load_test_schema() -> tuple[dict, ValidationSchema]:
    values = json.loads((ROOT / "config" / "schema.json").read_text(encoding="utf-8"))
    return values, ValidationSchema.from_mapping(values)


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_schema, self.schema = load_test_schema()

    def test_row_issues_are_limited_to_configured_columns(self) -> None:
        row = {column: "value" for column in self.schema.approved_columns}
        row.update(
            {
                "INDIVIDUAL#": "123",
                "DATE OF BIRTH": "1990",
                "PROVIDER": "",
                "CONTRACT #": "",
            }
        )

        result = validate_rows(pd.DataFrame([row]), self.schema)

        self.assertEqual(["PROVIDER"], [issue.column for issue in result.issues])
        self.assertTrue(any(item.startswith("PROVIDER:") for item in result.warnings))
        self.assertFalse(
            any(item.startswith("CONTRACT #:") for item in result.warnings)
        )

    def test_optional_column_may_be_absent(self) -> None:
        values = dict(self.raw_schema)
        values["optional_columns"] = ["PROVIDER"]
        schema = ValidationSchema.from_mapping(values)
        headers = tuple(
            column for column in schema.approved_columns if column != "PROVIDER"
        )

        result = validate_schema(headers, schema)

        self.assertFalse(
            any("PROVIDER" in error for error in result.errors),
            result.errors,
        )

    def test_techsheet_name_is_trimmed_and_fills_every_row(self) -> None:
        adapter = OpenpyxlWorkbookAdapter()
        service = SingleFileValidationService(self.schema, adapter)
        rows = [
            {column: str(index) for column in self.schema.approved_columns}
            for index in (1, 2)
        ]
        for row in rows:
            row["DATE OF BIRTH"] = "1990"
        content = adapter.write_excel(pd.DataFrame(rows), self.schema.expected_sheet)

        result = service.validate_data(content, " July Techsheet ")

        self.assertEqual(
            ["July Techsheet", "July Techsheet"],
            result.cleaned_data["TECSHEET NAME"].tolist(),
        )
        validated_excel = service.validated_excel(result.cleaned_data)
        exported = adapter.read_sheet(validated_excel, self.schema.expected_sheet)
        self.assertEqual(
            ["July Techsheet", "July Techsheet"],
            exported["TECSHEET NAME"].tolist(),
        )


class WorkbookSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OpenpyxlWorkbookAdapter()

    def test_invalid_xlsx_archive_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid .xlsx"):
            self.adapter.inspect(b"not an xlsx file")

    def test_csv_formula_values_are_escaped(self) -> None:
        exported = self.adapter.write_csv(
            pd.DataFrame({"unsafe": ["=2+2", "@SUM(A1:A2)"], "safe": ["text", 2]})
        )
        text = exported.decode("utf-8-sig")

        self.assertIn("'=2+2", text)
        self.assertIn("'@SUM(A1:A2)", text)


if __name__ == "__main__":
    unittest.main()
