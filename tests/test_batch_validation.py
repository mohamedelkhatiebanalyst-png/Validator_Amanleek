from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from amanleek_validator.application.batch_validation import (
    BatchValidationInput,
    BatchValidationService,
    BatchValidationStatus,
)
from amanleek_validator.application.single_file import SingleFileValidationService
from amanleek_validator.domain.schema import ValidationSchema
from amanleek_validator.infrastructure.excel import OpenpyxlWorkbookAdapter


ROOT = Path(__file__).resolve().parents[1]


class BatchValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        values = json.loads(
            (ROOT / "config" / "schema.json").read_text(encoding="utf-8")
        )
        self.schema = ValidationSchema.from_mapping(values)
        self.adapter = OpenpyxlWorkbookAdapter()
        single = SingleFileValidationService(self.schema, self.adapter)
        self.service = BatchValidationService(single)

    def workbook(self) -> bytes:
        row = {column: "value" for column in self.schema.approved_columns}
        row.update({
            "INDIVIDUAL#": "123",
            "DATE OF BIRTH": "1990",
            "CLAIM DATE": "2026-08-20 14:30:00",
            "VISA/SOAP#": "C1",
        })
        return self.adapter.write_excel(
            pd.DataFrame([row]), self.schema.expected_sheet
        )

    def test_valid_file_uses_its_own_techsheet_name(self) -> None:
        result = self.service.validate(
            BatchValidationInput("one.xlsx", self.workbook(), "Client One")
        )

        self.assertEqual(BatchValidationStatus.VALIDATED, result.status)
        exported = self.adapter.read_sheet(
            result.validated_excel or b"", self.schema.expected_sheet
        )
        self.assertEqual("Client One", exported.at[0, "TECSHEET NAME"])

    def test_missing_techsheet_name_rejects_only_that_file(self) -> None:
        result = self.service.validate(
            BatchValidationInput("one.xlsx", self.workbook(), "  ")
        )

        self.assertEqual(BatchValidationStatus.REJECTED, result.status)
        self.assertIn("Techsheet name is required.", result.errors)

    def test_repairable_structure_is_reported_without_modification(self) -> None:
        data = self.adapter.read_sheet(self.workbook(), self.schema.expected_sheet)
        content = self.adapter.write_excel(data, "wrong-sheet")

        result = self.service.validate(
            BatchValidationInput("wrong.xlsx", content, "Client")
        )

        self.assertEqual(BatchValidationStatus.NEEDS_REPAIR, result.status)
        self.assertIsNone(result.validated_excel)


if __name__ == "__main__":
    unittest.main()
