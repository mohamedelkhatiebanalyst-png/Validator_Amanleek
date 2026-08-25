from __future__ import annotations

from dataclasses import dataclass

from amanleek_validator.application.ports import WorkbookPort
from amanleek_validator.application.tpa_ingestion import read_csv_source


MAX_EXCEL_ROWS = 1_048_576
MAX_EXCEL_COLUMNS = 16_384
FORMULA_PREFIXES = ("=", "+", "-", "@")


@dataclass(frozen=True)
class CsvConversion:
    content: bytes
    rows: int
    columns: int


class CsvConversionService:
    def __init__(self, workbooks: WorkbookPort) -> None:
        self.workbooks = workbooks

    def convert(self, content: bytes) -> CsvConversion:
        data = read_csv_source(content)
        if len(data) + 1 > MAX_EXCEL_ROWS:
            raise ValueError(
                f"The CSV exceeds Excel's {MAX_EXCEL_ROWS:,}-row worksheet limit"
            )
        if len(data.columns) > MAX_EXCEL_COLUMNS:
            raise ValueError(
                f"The CSV exceeds Excel's {MAX_EXCEL_COLUMNS:,}-column limit"
            )
        safe_data = data.map(_escape_formula)
        return CsvConversion(
            content=self.workbooks.write_excel(safe_data, "sheet1"),
            rows=len(data),
            columns=len(data.columns),
        )


def _escape_formula(value: object) -> object:
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value
