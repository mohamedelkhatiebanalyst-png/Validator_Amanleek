from datetime import datetime
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.datetime import MAC_EPOCH

from amanleek_validator.bootstrap import build_container
from amanleek_validator.domain.dates import DATE_COLUMNS, parse_mixed_datetime
from amanleek_validator.domain.validation import validate_rows
from amanleek_validator.application.batch_validation import BatchValidationInput
from amanleek_validator.ui.batch_validation_page import _render_results
from amanleek_validator.ui.single_file_page import _render_issue_report


class DateTests(unittest.TestCase):
    def setUp(self):
        self.container = build_container(Path(__file__).resolve().parents[1])
        self.single = self.container.single_files

    def row(self, value):
        row = {column: "value" for column in self.container.schema.approved_columns}
        row.update({column: value for column in DATE_COLUMNS})
        row.update({"INDIVIDUAL#": "123", "DATE OF BIRTH": "1990"})
        return row

    def test_supported_formats_and_seconds(self):
        samples = {
            "03/04/2026": "2026-04-03 00:00:00",
            "08/20/2026": "2026-08-20 00:00:00",
            "2026-Aug-20": "2026-08-20 00:00:00",
            "2026-03-04": "2026-03-04 00:00:00",
            "20.08.2026": "2026-08-20 00:00:00",
            "20-8-2026 2:30 PM": "2026-08-20 14:30:00",
            " August 21, 2026 01:02:03 ": "2026-08-21 01:02:03",
            "21-Aug-2026": "2026-08-21 00:00:00",
            "2026/08/20 14:30:45.123456789": "2026-08-20 14:30:45",
            "2026-08-20T14:30:45": "2026-08-20 14:30:45",
            "20260820": "2026-08-20 00:00:00",
            20260820: "2026-08-20 00:00:00",
            46000.5: "2025-12-09 12:00:00",
            "46000.5": "2025-12-09 12:00:00",
            datetime(2024, 2, 29, 1, 2, 3): "2024-02-29 01:02:03",
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                actual = parse_mixed_datetime(pd.Series([source], dtype=object))
                self.assertEqual(expected, actual.dt.strftime("%Y-%m-%d %H:%M:%S").iloc[0])

    def test_invalid_inputs_do_not_guess_dates_or_crash(self):
        samples = ["31/02/2026", "29/02/2025", "2026-13-01", "2026", "2026-08",
                   "03/04/26", "13/14/2026", "tomorrow", "14:30", "garbage",
                   0, -1, 100001, 20260231, float("inf"), True, 60,
                   "2026-08-20 24:00", "2026-08-20 12:60:00",
                   "2026-08-20T12:00:00+03:00", "2026-08-20T12:00:00Z",
                   pd.Timestamp("2026-08-20", tz="UTC"), "1500-01-01"]
        parsed = parse_mixed_datetime(pd.Series(samples, dtype=object))
        self.assertTrue(parsed.isna().all(), parsed.to_string())

    def test_all_columns_round_trip_xlsx_and_csv(self):
        data = pd.DataFrame([self.row("03/04/2026 2:30:45 PM")])
        original = self.single.workbooks.write_excel(data, "sheet1")
        result = self.container.batch_validation.validate(
            BatchValidationInput("dates.xlsx", original, "Dates"))
        self.assertEqual("Validated", result.status)
        excel = self.single.workbooks.read_sheet(result.validated_excel, "sheet1")
        csv = pd.read_csv(BytesIO(result.validated_csv), dtype=object)
        for frame in (excel, csv):
            for column in DATE_COLUMNS:
                self.assertEqual("2026-04-03 14:30:45", frame.at[0, column])
            self.assertEqual("1990", frame.at[0, "DATE OF BIRTH"])

    def test_invalid_column_blocks_exports_and_all_rows_are_reported(self):
        for column in DATE_COLUMNS:
            with self.subTest(column=column):
                row = self.row("2026-08-20")
                row[column] = "31/02/2026"
                data = pd.DataFrame([row] * 105)
                source = self.single.workbooks.write_excel(data, "sheet1")
                result = self.container.batch_validation.validate(
                    BatchValidationInput("bad.xlsx", source, "Dates"))
                self.assertEqual("Rejected", result.status)
                self.assertIsNone(result.validated_excel)
                self.assertIsNone(result.validated_csv)
                report = pd.read_excel(BytesIO(result.validation_report))
                errors = report[report["Severity"].eq("Error")]
                self.assertEqual(105, len(errors))
                self.assertEqual({column}, set(errors["Column"]))
                self.assertEqual(list(range(2, 107)), errors["Excel Row"].tolist())

    def test_blank_dates_remain_blank_and_native_columns_become_strings(self):
        data = pd.DataFrame([self.row(None), self.row("  "),
                             self.row(datetime(2026, 8, 20))])
        result = validate_rows(data, self.container.schema)
        self.assertFalse(result.errors)
        for column in DATE_COLUMNS:
            self.assertTrue(result.cleaned_data[column].iloc[:2].isna().all())
            self.assertEqual("2026-08-20 00:00:00", result.cleaned_data.at[2, column])
        native = pd.DataFrame({"CLAIM DATE": pd.to_datetime(["2026-08-20"])})
        result = validate_rows(native, self.container.schema)
        self.assertIsInstance(result.cleaned_data.at[0, "CLAIM DATE"], str)

    def test_1904_workbook_serial_dates(self):
        workbook = Workbook()
        workbook.epoch = MAC_EPOCH
        workbook.active.title = "sheet1"
        workbook.active.append(list(self.container.schema.approved_columns))
        workbook.active.append(list(self.row(46000.5).values()))
        output = BytesIO()
        workbook.save(output)
        result = self.single.validate_data(output.getvalue(), "Dates")
        self.assertFalse(result.errors)
        self.assertEqual("2029-12-10 12:00:00", result.cleaned_data.at[0, "CLAIM DATE"])
        repaired = self.single.reorder(output.getvalue())
        result = self.single.validate_data(repaired.content, "Dates")
        self.assertEqual("2029-12-10 12:00:00", result.cleaned_data.at[0, "CLAIM DATE"])

    def test_invalid_text_markers_are_not_silently_read_as_blank(self):
        data = pd.DataFrame([self.row(value) for value in ("NA", "N/A", "NULL", "NaN")])
        content = self.single.workbooks.write_excel(data, "sheet1")
        result = self.single.validate_data(content, "Dates")
        self.assertEqual(5, len(result.errors))
        self.assertEqual(20, sum(issue.severity == "Error" for issue in result.issues))

    def test_rejected_reports_are_available_in_both_pages(self):
        rows = validate_rows(pd.DataFrame([self.row("invalid")]), self.container.schema)
        with patch("amanleek_validator.ui.single_file_page.st") as st:
            _render_issue_report(self.single, "bad.xlsx", rows)
            self.assertTrue(st.download_button.called)
        content = self.single.workbooks.write_excel(pd.DataFrame([self.row("invalid")]), "sheet1")
        result = self.container.batch_validation.validate(BatchValidationInput("bad.xlsx", content, "Dates"))
        with patch("amanleek_validator.ui.batch_validation_page.st") as st:
            _render_results((result,))
            labels = [call.args[0] for call in st.download_button.call_args_list]
            self.assertIn("Issue report", labels)
            self.assertIn("All issue reports", labels)


if __name__ == "__main__":
    unittest.main()
