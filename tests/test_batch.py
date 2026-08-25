from __future__ import annotations

import unittest

import pandas as pd

from amanleek_validator.application.batch import BatchComparisonService
from amanleek_validator.domain.models import BatchStatus, UploadedWorkbook
from amanleek_validator.infrastructure.excel import OpenpyxlWorkbookAdapter


class BatchComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OpenpyxlWorkbookAdapter()
        self.service = BatchComparisonService(self.adapter)

    def workbook(self, columns: list[str], value: str) -> bytes:
        return self.adapter.write_excel(
            pd.DataFrame([{column: value for column in columns}]),
            "sheet1",
        )

    def test_matching_workbooks_are_reported_as_matching(self) -> None:
        uploads = (
            UploadedWorkbook("first.xlsx", self.workbook(["A", "B"], "first")),
            UploadedWorkbook("second.xlsx", self.workbook(["A", "B"], "second")),
        )

        comparison = self.service.compare(uploads)

        self.assertTrue(comparison.all_match)
        self.assertFalse(comparison.mismatches)

    def test_different_structure_is_reported(self) -> None:
        uploads = (
            UploadedWorkbook("first.xlsx", self.workbook(["A", "B"], "first")),
            UploadedWorkbook("second.xlsx", self.workbook(["B", "A"], "second")),
        )

        comparison = self.service.compare(uploads)

        self.assertFalse(comparison.all_match)
        self.assertEqual(BatchStatus.DIFFERENT, comparison.entries[1].status)

    def test_matching_csv_files_are_supported(self) -> None:
        uploads = (
            UploadedWorkbook("first.csv", b"A,B\n1,2\n"),
            UploadedWorkbook("second.csv", b"A,B\n3,4\n"),
        )

        comparison = self.service.compare(uploads)

        self.assertTrue(comparison.all_match)

    def test_csv_matches_canonical_single_sheet_workbook(self) -> None:
        uploads = (
            UploadedWorkbook("reference.xlsx", self.workbook(["A", "B"], "x")),
            UploadedWorkbook("data.csv", b"A,B\n1,2\n"),
        )

        comparison = self.service.compare(uploads)

        self.assertTrue(comparison.all_match)

    def test_invalid_utf8_csv_is_unreadable(self) -> None:
        uploads = (
            UploadedWorkbook("reference.csv", b"A,B\n1,2\n"),
            UploadedWorkbook("invalid.csv", b"A,B\n\xff,2\n"),
        )

        comparison = self.service.compare(uploads)

        self.assertEqual(BatchStatus.UNREADABLE, comparison.entries[1].status)


if __name__ == "__main__":
    unittest.main()
