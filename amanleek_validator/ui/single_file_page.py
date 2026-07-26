from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st

from amanleek_validator.application.single_file import (
    RepairResult,
    SingleFileValidationService,
)
from amanleek_validator.domain.models import RowValidation, WorkbookAssessment
from amanleek_validator.domain.validation import issues_dataframe
from amanleek_validator.ui.theme import (
    render_page_header,
    render_privacy_note,
    render_section_heading,
)


logger = logging.getLogger(__name__)

REPAIRED_BYTES_KEY = "single_file_repaired_bytes"
UPLOAD_ID_KEY = "single_file_upload_id"
REPAIR_MESSAGES_KEY = "single_file_repair_messages"
TECHSHEET_NAME_KEY = "single_file_techsheet_name"


def render_single_file_page(service: SingleFileValidationService) -> None:
    render_page_header(
        "Single-file validation",
        "Inspect, repair, and export",
        "Validate one client-utilization workbook and resolve safe structural "
        "issues before uploading it to Zoho WorkDrive.",
    )
    _render_template_download(service)

    render_section_heading(
        "Upload workbook",
        "Accepted format: Excel .xlsx. Maximum file size: 100 MB.",
    )
    uploaded_file = st.file_uploader(
        "Choose an Excel workbook",
        type=["xlsx"],
        key="single_file_upload",
    )
    if uploaded_file is None:
        render_privacy_note()
        return

    original_bytes = uploaded_file.getvalue()
    _reset_state_for_new_upload(uploaded_file.name, original_bytes)
    working_bytes = st.session_state.get(REPAIRED_BYTES_KEY, original_bytes)
    file_size_mb = len(original_bytes) / (1024 * 1024)
    st.success(f"Ready: {uploaded_file.name} · {file_size_mb:.2f} MB")
    techsheet_name = st.text_input(
        "Techsheet name",
        placeholder="Enter the Techsheet name",
        help="This value will fill the TECSHEET NAME column in every data row.",
        key=TECHSHEET_NAME_KEY,
    ).strip()
    if not techsheet_name:
        st.info("Enter the Techsheet name to continue.")
        return

    try:
        assessment = service.assess(working_bytes)
    except Exception:
        logger.exception("Unexpected assessment failure for %s", uploaded_file.name)
        _render_rejected(
            ("The workbook could not be assessed due to an unexpected error.",),
        )
        return

    _render_metrics(service, assessment)
    if _render_repairs(service, assessment, working_bytes):
        return

    _render_repair_messages()
    if assessment.is_pending:
        _render_pending(assessment)
        return
    if assessment.errors:
        _render_rejected(assessment.errors)
        return

    try:
        row_result = service.validate_data(working_bytes, techsheet_name)
    except Exception:
        logger.exception("Unexpected data-validation failure for %s", uploaded_file.name)
        _render_rejected(
            ("The worksheet data could not be read due to an unexpected error.",),
        )
        return

    if row_result.errors:
        _render_rejected(row_result.errors)
        _render_warnings((*assessment.warnings, *row_result.warnings))
        return

    _render_validated(service, uploaded_file.name, assessment, row_result)


def _render_template_download(service: SingleFileValidationService) -> None:
    with st.expander("Need a clean template?"):
        template_column, action_column = st.columns([3, 1])
        with template_column:
            st.markdown("**All_in_one_2026.xlsx**")
            st.caption(
                "An empty sheet1 template with every approved column in exact order."
            )
        with action_column:
            st.download_button(
                "Download template",
                data=service.template(),
                file_name="All_in_one_2026.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                icon=":material/download:",
                width="stretch",
            )


def _reset_state_for_new_upload(file_name: str, content: bytes) -> None:
    upload_id = sha256(file_name.encode("utf-8") + content).hexdigest()
    if st.session_state.get(UPLOAD_ID_KEY) == upload_id:
        return
    st.session_state[UPLOAD_ID_KEY] = upload_id
    st.session_state.pop(REPAIRED_BYTES_KEY, None)
    st.session_state.pop(TECHSHEET_NAME_KEY, None)
    st.session_state[REPAIR_MESSAGES_KEY] = []


def _render_repairs(
    service: SingleFileValidationService,
    assessment: WorkbookAssessment,
    content: bytes,
) -> bool:
    repairs = assessment.repairs
    if repairs.rename_from:
        st.warning(
            f"The worksheet is named '{repairs.rename_from}' instead of "
            f"'{service.schema.expected_sheet}'."
        )
        if st.button(
            f"Rename worksheet to {service.schema.expected_sheet}",
            icon=":material/drive_file_rename_outline:",
        ):
            return _apply_repair(
                lambda: service.rename_sheet(content, repairs.rename_from or ""),
                f"Worksheet renamed to {service.schema.expected_sheet}.",
            )

    if repairs.missing_columns:
        st.warning(
            "Required column(s) missing: " + ", ".join(repairs.missing_columns) + "."
        )
        if st.button(
            "Add missing required columns with null values",
            type="primary",
            icon=":material/add_column_right:",
        ):
            details = ", ".join(
                f"{column} (position {service.schema.approved_columns.index(column) + 1})"
                for column in repairs.missing_columns
            )
            return _apply_repair(
                lambda: service.add_missing_columns(content, repairs.missing_columns),
                f"Added with empty values: {details}.",
            )

    if repairs.extra_columns:
        st.warning("Extra column(s) found: " + ", ".join(repairs.extra_columns) + ".")
        if st.button("Delete extra columns", icon=":material/delete_sweep:"):
            return _apply_repair(
                lambda: service.delete_extra_columns(content, repairs.extra_columns),
                "Deleted extra columns: " + ", ".join(repairs.extra_columns) + ".",
            )

    if repairs.can_reorder:
        st.warning(
            "All required columns were found, but they are not in the approved order."
        )
        if st.button(
            "Reorder required columns",
            type="primary",
            icon=":material/reorder:",
        ):
            return _apply_repair(
                lambda: service.reorder(content),
                "Required columns were reordered into the approved order.",
            )
    return False


def _apply_repair(
    operation: Callable[[], RepairResult],
    success_message: str,
) -> bool:
    try:
        result = operation()
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"The repair could not be completed: {exc}")
        return True
    except Exception:
        logger.exception("Unexpected workbook repair failure")
        st.error("The repair failed unexpectedly. Check the application logs.")
        return True

    st.session_state[REPAIRED_BYTES_KEY] = result.content
    messages = list(st.session_state.get(REPAIR_MESSAGES_KEY, []))
    messages.append(success_message)
    st.session_state[REPAIR_MESSAGES_KEY] = messages
    st.rerun()
    return True


def _render_metrics(
    service: SingleFileValidationService,
    assessment: WorkbookAssessment,
) -> None:
    columns = st.columns(3)
    columns[0].metric("Required columns", len(service.schema.required_columns))
    columns[1].metric("Detected columns", len(assessment.headers))
    columns[2].metric("Detected sheets", len(assessment.structure))


def _render_repair_messages() -> None:
    for message in st.session_state.get(REPAIR_MESSAGES_KEY, []):
        st.success(message)


def _render_pending(assessment: WorkbookAssessment) -> None:
    st.warning(
        "Validation is pending an available repair. No file has been stored."
    )
    _render_messages(assessment.errors)


def _render_rejected(errors: tuple[str, ...]) -> None:
    st.error("Validation failed. Do not upload this file to WorkDrive.")
    _render_messages(errors)
    st.info("The uploaded workbook was processed in memory and was not stored.")


def _render_validated(
    service: SingleFileValidationService,
    uploaded_name: str,
    assessment: WorkbookAssessment,
    row_result: RowValidation,
) -> None:
    st.success("Validation passed. The workbook structure is ready for WorkDrive upload.")
    _render_warnings((*assessment.warnings, *row_result.warnings))
    _render_schema(service)

    issues = issues_dataframe(row_result.issues)
    if not issues.empty:
        st.subheader("Row-level issues")
        st.dataframe(issues, width="stretch", hide_index=True)
        st.download_button(
            "Download validation report",
            data=service.validation_report(issues),
            file_name=f"{Path(uploaded_name).stem}_validation_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    base_name = Path(uploaded_name).stem
    validated_excel = service.validated_excel(row_result.cleaned_data)
    validated_csv = service.validated_csv(row_result.cleaned_data)
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "Download validated Excel",
        data=validated_excel,
        file_name=f"{base_name}_validated.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        icon=":material/download:",
        width="stretch",
    )
    download_columns[1].download_button(
        "Download validated CSV",
        data=validated_csv,
        file_name=f"{base_name}_validated.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
    )
    st.caption(
        "Files are generated in memory and are saved only when you click a "
        "download button."
    )


def _render_warnings(warnings: tuple[str, ...]) -> None:
    if not warnings:
        st.info("No warnings were found.")
        return
    st.warning(f"Validation completed with {len(warnings)} warning(s).")
    _render_messages(warnings)


def _render_schema(service: SingleFileValidationService) -> None:
    schema = service.schema
    with st.expander("Approved raw schema", expanded=False):
        data = pd.DataFrame(
            {
                "Position": range(1, len(schema.approved_columns) + 1),
                "Approved column": schema.approved_columns,
                "Requirement": [
                    "Optional" if column in schema.optional_columns else "Required"
                    for column in schema.approved_columns
                ],
            }
        )
        st.dataframe(data, width="stretch", hide_index=True)


def _render_messages(messages: tuple[str, ...]) -> None:
    for message in messages:
        st.markdown(f"- {message}")
