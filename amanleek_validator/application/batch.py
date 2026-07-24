from __future__ import annotations

import logging
from collections.abc import Sequence

from amanleek_validator.domain.models import (
    BatchComparison,
    BatchEntry,
    BatchStatus,
    UploadedWorkbook,
    WorkbookStructure,
)
from amanleek_validator.domain.validation import describe_structure_difference

from .ports import WorkbookPort


logger = logging.getLogger(__name__)


class BatchComparisonService:
    def __init__(self, workbooks: WorkbookPort) -> None:
        self.workbooks = workbooks

    def compare(self, uploads: Sequence[UploadedWorkbook]) -> BatchComparison:
        inspections: list[
            tuple[UploadedWorkbook, WorkbookStructure | None, str | None]
        ] = []
        for upload in uploads:
            try:
                structure = self.workbooks.inspect(upload.content)
                inspections.append((upload, structure, None))
            except (OSError, ValueError, KeyError) as exc:
                inspections.append((upload, None, str(exc)))
            except Exception:
                logger.exception("Unexpected workbook parsing failure: %s", upload.name)
                inspections.append(
                    (upload, None, "Workbook parsing failed unexpectedly.")
                )

        reference_item = next(
            (item for item in inspections if item[1] is not None),
            None,
        )
        if reference_item is None:
            entries = tuple(
                BatchEntry(
                    upload.name,
                    BatchStatus.UNREADABLE,
                    error or "Workbook could not be opened.",
                    None,
                )
                for upload, _, error in inspections
            )
            return BatchComparison(None, None, entries)

        reference_upload, reference_structure, _ = reference_item
        entries: list[BatchEntry] = []
        for upload, structure, error in inspections:
            if structure is None:
                entries.append(
                    BatchEntry(
                        upload.name,
                        BatchStatus.UNREADABLE,
                        error or "Workbook could not be opened.",
                        None,
                    )
                )
                continue
            matches = structure == reference_structure
            entries.append(
                BatchEntry(
                    upload.name,
                    BatchStatus.MATCHES if matches else BatchStatus.DIFFERENT,
                    describe_structure_difference(reference_structure, structure),
                    structure,
                )
            )
        return BatchComparison(
            reference_upload.name,
            reference_structure,
            tuple(entries),
        )
