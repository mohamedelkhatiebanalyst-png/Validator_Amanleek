from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from amanleek_validator.application.batch import BatchComparisonService
from amanleek_validator.application.batch_validation import BatchValidationService
from amanleek_validator.application.csv_conversion import CsvConversionService
from amanleek_validator.application.single_file import SingleFileValidationService
from amanleek_validator.domain.schema import ValidationSchema
from amanleek_validator.infrastructure.config import load_schema
from amanleek_validator.infrastructure.excel import OpenpyxlWorkbookAdapter


@dataclass(frozen=True)
class AppContainer:
    schema: ValidationSchema
    single_files: SingleFileValidationService
    batches: BatchComparisonService
    batch_validation: BatchValidationService
    csv_conversion: CsvConversionService


def build_container(root: Path) -> AppContainer:
    schema = load_schema(root / "config" / "schema.json")
    workbook_adapter = OpenpyxlWorkbookAdapter()
    single_files = SingleFileValidationService(schema, workbook_adapter)
    return AppContainer(
        schema=schema,
        single_files=single_files,
        batches=BatchComparisonService(workbook_adapter),
        batch_validation=BatchValidationService(single_files),
        csv_conversion=CsvConversionService(workbook_adapter),
    )
