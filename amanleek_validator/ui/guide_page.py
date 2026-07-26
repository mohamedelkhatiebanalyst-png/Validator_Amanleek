from __future__ import annotations

import streamlit as st

from amanleek_validator.ui.theme import (
    render_page_header,
    render_privacy_note,
    render_section_heading,
    render_step_card,
)


def render_guide_page() -> None:
    render_page_header(
        "Getting started",
        "Validate with confidence",
        "Check utilization workbooks, resolve safe formatting issues, and export "
        "clean files ready for Zoho WorkDrive.",
    )
    render_privacy_note()

    render_section_heading(
        "Validate one file",
        "A guided four-step process from upload to clean export.",
    )
    st.warning(
        "Workbook requirement: the uploaded Excel file must contain exactly one "
        "worksheet. If that worksheet is not named `sheet1`, the app can offer to "
        "rename it safely."
    )
    _render_flow(
        (
            (
                "1",
                "Upload",
                "Choose one `.xlsx` utilization file containing exactly one worksheet.",
            ),
            ("2", "Enter Techsheet name", "Type the name that should fill every row."),
            ("3", "Review and repair", "Read the messages and use any repair button shown."),
            ("4", "Download", "Choose validated Excel or validated CSV."),
        )
    )

    render_section_heading("Need help?", "Quick answers for common validation results.")
    with st.expander("What does a warning mean?", expanded=True):
        st.write(
            "Warnings tell you which selected cells need attention. You can still "
            "download the result. If row-level issues exist, you can also download "
            "a separate validation report."
        )

    with st.expander("What should I do if validation fails?"):
        st.write(
            "Read the error message and correct the original workbook. If the app "
            "offers a repair button, click it and validation will run again."
        )

    render_section_heading(
        "Check several files",
        "Compare workbook structures before processing a full batch.",
    )
    _render_flow(
        (
            ("1", "Open Batch check", "Choose Batch check from the left sidebar."),
            ("2", "Upload files", "Select at least two `.xlsx` workbooks."),
            ("3", "Compare", "The app checks sheets and exact column order."),
            ("4", "Review", "Confirm that every workbook shows Matches."),
        )
    )

    st.info(
        "Nothing is downloaded automatically. Your browser saves a file only after "
        "you click a download button."
    )


def _render_flow(steps: tuple[tuple[str, str, str], ...]) -> None:
    columns = st.columns(len(steps))
    for column, (number, title, description) in zip(columns, steps, strict=True):
        with column:
            render_step_card(number, title, description)
