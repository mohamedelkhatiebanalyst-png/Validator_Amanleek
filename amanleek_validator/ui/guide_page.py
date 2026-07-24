from __future__ import annotations

import streamlit as st


def render_guide_page() -> None:
    st.subheader("How to use the app")
    st.write(
        "Use this app to check Excel files, fix safe formatting problems, and "
        "download the result. Your files are not automatically saved on the server."
    )

    st.markdown("### Validate one file")
    _render_flow(
        (
            ("1", "Upload", "Choose one `.xlsx` utilization file."),
            ("2", "Enter Techsheet name", "Type the name that should fill every row."),
            ("3", "Review and repair", "Read the messages and use any repair button shown."),
            ("4", "Download", "Choose validated Excel or validated CSV."),
        )
    )

    with st.expander("What should I do if I see a warning?", expanded=True):
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

    st.markdown("### Check several files")
    _render_flow(
        (
            ("1", "Open Batch check", "Choose **Batch check** from the left sidebar."),
            ("2", "Upload files", "Select at least two `.xlsx` workbooks."),
            ("3", "Compare", "Confirm that every file shows **Matches**."),
            ("4", "Review the result", "All files should show **Matches**."),
        )
    )

    st.info(
        "Nothing is downloaded automatically. Your browser saves a file only after "
        "you click a download button."
    )


def _render_flow(steps: tuple[tuple[str, str, str], ...]) -> None:
    for position, (number, title, description) in enumerate(steps):
        with st.container(border=True):
            st.markdown(f"**{number}. {title}**")
            st.write(description)
        if position < len(steps) - 1:
            st.markdown(
                "<div style='text-align:center; font-size:1.6rem;'>↓</div>",
                unsafe_allow_html=True,
            )
