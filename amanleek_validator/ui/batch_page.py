from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd
import streamlit as st

from amanleek_validator.application.batch import BatchComparisonService
from amanleek_validator.domain.models import (
    BatchComparison,
    BatchEntry,
    BatchStatus,
    UploadedWorkbook,
)
from amanleek_validator.ui.theme import (
    render_page_header,
    render_privacy_note,
    render_section_heading,
)


MAX_BATCH_FILES = 50


def render_batch_page(service: BatchComparisonService) -> None:
    render_page_header(
        "Batch structure check",
        "Compare files at a glance",
        "Compare worksheet structure and exact column order across multiple "
        "workbooks using the first readable file as the reference.",
    )
    render_section_heading(
        "Upload workbooks",
        f"Select 2–{MAX_BATCH_FILES} .xlsx or UTF-8 .csv files for comparison.",
    )

    uploaded_files = st.file_uploader(
        "Choose Excel workbooks",
        type=["xlsx", "csv"],
        accept_multiple_files=True,
        key="admin_batch_uploads",
        help=f"Upload up to {MAX_BATCH_FILES} XLSX or CSV files.",
    )
    if not uploaded_files:
        render_privacy_note()
        return
    if len(uploaded_files) > MAX_BATCH_FILES:
        st.error(
            f"This batch contains {len(uploaded_files)} files. "
            f"Upload no more than {MAX_BATCH_FILES} files at once."
        )
        return
    if len(uploaded_files) == 1:
        st.warning("Upload at least one more workbook for a meaningful comparison.")

    total_size_mb = sum(len(upload.getvalue()) for upload in uploaded_files) / (
        1024 * 1024
    )
    st.success(f"{len(uploaded_files)} file(s) ready · {total_size_mb:.2f} MB total")
    uploads = tuple(
        UploadedWorkbook(upload.name, upload.getvalue()) for upload in uploaded_files
    )
    comparison = _compare_with_progress(service, uploads)
    _render_comparison(comparison)


def _compare_with_progress(
    service: BatchComparisonService,
    uploads: Sequence[UploadedWorkbook],
) -> BatchComparison:
    progress = st.progress(0, text="Inspecting workbook structures...")
    try:
        comparison = service.compare(uploads)
        progress.progress(1.0, text=f"Inspected {len(uploads)} workbooks")
        return comparison
    finally:
        progress.empty()


def _render_comparison(comparison: BatchComparison) -> None:
    summary = [_summary_row(entry) for entry in comparison.entries]
    metrics = st.columns(4)
    metrics[0].metric("Uploaded", len(summary))
    metrics[1].metric(
        "Matching",
        sum(entry.status is BatchStatus.MATCHES for entry in comparison.entries),
    )
    metrics[2].metric(
        "Different",
        sum(entry.status is BatchStatus.DIFFERENT for entry in comparison.entries),
    )
    metrics[3].metric(
        "Unreadable",
        sum(entry.status is BatchStatus.UNREADABLE for entry in comparison.entries),
    )

    if comparison.reference_file is None:
        st.error("None of the uploaded workbooks could be opened.")
    else:
        st.info(f"Reference workbook: `{comparison.reference_file}`")
        if comparison.all_match:
            st.success(
                "All uploaded workbooks have the same sheet structure and column order."
            )
        elif comparison.mismatches:
            st.error(
                f"{len(comparison.mismatches)} workbook(s) do not match the "
                "reference structure."
            )

    st.dataframe(pd.DataFrame(summary), width="stretch", hide_index=True)
    if comparison.mismatches:
        with st.expander("Structure differences", expanded=True):
            for entry in comparison.mismatches:
                st.markdown(f"- **{entry.file_name}:** {entry.detail}")


def _summary_row(entry: BatchEntry) -> dict[str, Any]:
    structure = entry.structure
    return {
        "File": entry.file_name,
        "Result": entry.status.value,
        "Sheets": len(structure) if structure is not None else None,
        "Columns per sheet": (
            ", ".join(
                f"{sheet.name}: {len(sheet.headers)}" for sheet in structure
            )
            if structure is not None
            else None
        ),
        "Details": entry.detail,
    }
