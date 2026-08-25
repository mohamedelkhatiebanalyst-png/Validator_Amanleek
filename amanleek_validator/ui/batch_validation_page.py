from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from amanleek_validator.application.batch_validation import (
    BatchValidationEntry,
    BatchValidationInput,
    BatchValidationService,
    BatchValidationStatus,
)
from amanleek_validator.ui.theme import (
    render_page_header,
    render_privacy_note,
    render_section_heading,
)


MAX_BATCH_VALIDATION_FILES = 50


def render_batch_validation_page(service: BatchValidationService) -> None:
    render_page_header(
        "Batch validation",
        "Validate multiple utilization files",
        "Apply the same schema and row rules as Single-file validation to each "
        "workbook independently.",
    )
    uploads = st.file_uploader(
        "Choose XLSX workbooks",
        type=["xlsx"],
        accept_multiple_files=True,
        key="batch_validation_uploads",
        help=f"Upload up to {MAX_BATCH_VALIDATION_FILES} workbooks.",
    )
    if not uploads:
        render_privacy_note()
        return
    if len(uploads) > MAX_BATCH_VALIDATION_FILES:
        st.error(
            f"Upload no more than {MAX_BATCH_VALIDATION_FILES} files at once."
        )
        return

    render_section_heading(
        "Techsheet names",
        "Enter the Techsheet name that will be written to every retained row "
        "in each workbook.",
    )
    inputs: list[BatchValidationInput] = []
    missing_names = False
    for index, upload in enumerate(uploads):
        content = upload.getvalue()
        file_id = sha256(upload.name.encode() + content).hexdigest()[:16]
        techsheet = st.text_input(
            f"{upload.name} — Techsheet name",
            key=f"batch_techsheet_{index}_{file_id}",
        )
        missing_names = missing_names or not techsheet.strip()
        inputs.append(BatchValidationInput(upload.name, content, techsheet))

    if st.button(
        "Validate all files",
        type="primary",
        disabled=missing_names,
    ):
        with st.spinner("Validating files..."):
            st.session_state["batch_validation_results"] = tuple(
                service.validate(item) for item in inputs
            )
            st.session_state["batch_validation_signature"] = _signature(inputs)

    results = st.session_state.get("batch_validation_results")
    if st.session_state.get("batch_validation_signature") != _signature(inputs):
        results = None
    if not results:
        if missing_names:
            st.info("Enter a Techsheet name for every file to enable validation.")
        return
    _render_results(results)


def _render_results(results: tuple[BatchValidationEntry, ...]) -> None:
    summary = pd.DataFrame([
        {
            "File": item.file_name,
            "Status": item.status.value,
            "Rows": item.row_count,
            "Issues": item.issue_count,
            "Warnings": len(item.warnings),
            "Errors": len(item.errors),
        }
        for item in results
    ])
    st.dataframe(summary, width="stretch", hide_index=True)

    excel_files: list[tuple[str, bytes]] = []
    csv_files: list[tuple[str, bytes]] = []
    report_files: list[tuple[str, bytes]] = []
    for index, item in enumerate(results):
        with st.expander(f"{item.file_name} — {item.status.value}"):
            for error in item.errors:
                st.error(error)
            for warning in item.warnings:
                st.warning(warning)
            if item.status is BatchValidationStatus.NEEDS_REPAIR:
                st.info(
                    "Use Single-file validation to review and apply the available "
                    "structural repairs, then include the repaired file in a new batch."
                )
            if item.validated_excel is None or item.validated_csv is None:
                continue
            stem = Path(item.file_name).stem
            excel_name = f"{stem}_validated.xlsx"
            csv_name = f"{stem}_validated.csv"
            excel_files.append((excel_name, item.validated_excel))
            csv_files.append((csv_name, item.validated_csv))
            columns = st.columns(3)
            columns[0].download_button(
                "Validated XLSX",
                item.validated_excel,
                excel_name,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"batch_valid_xlsx_{index}",
            )
            columns[1].download_button(
                "Validated CSV",
                item.validated_csv,
                csv_name,
                "text/csv",
                key=f"batch_valid_csv_{index}",
            )
            if item.validation_report is not None:
                report_name = f"{stem}_validation_report.xlsx"
                report_files.append((report_name, item.validation_report))
                columns[2].download_button(
                    "Issue report",
                    item.validation_report,
                    report_name,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"batch_valid_report_{index}",
                )

    if excel_files:
        render_section_heading("Download successful files")
        downloads = st.columns(3)
        downloads[0].download_button(
            "All validated XLSX",
            _zip_files(excel_files),
            "validated_xlsx_files.zip",
            "application/zip",
            type="primary",
        )
        downloads[1].download_button(
            "All validated CSV",
            _zip_files(csv_files),
            "validated_csv_files.zip",
            "application/zip",
        )
        if report_files:
            downloads[2].download_button(
                "All issue reports",
                _zip_files(report_files),
                "validation_reports.zip",
                "application/zip",
            )


def _signature(items: list[BatchValidationInput]) -> str:
    digest = sha256()
    for item in items:
        digest.update(item.name.encode())
        digest.update(item.content)
        digest.update(item.techsheet_name.strip().encode())
    return digest.hexdigest()


def _zip_files(files: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return output.getvalue()
