import sys
from pathlib import Path

if sys.version_info < (3, 11):
    raise RuntimeError(
        "This application requires Python 3.11 or newer. "
        f"You are running Python {sys.version.split()[0]} from {sys.executable}."
    )

import streamlit as st

from amanleek_validator.bootstrap import build_container
from amanleek_validator.ui.batch_page import render_batch_page
from amanleek_validator.ui.batch_validation_page import render_batch_validation_page
from amanleek_validator.ui.csv_converter_page import render_csv_converter_page
from amanleek_validator.ui.guide_page import render_guide_page
from amanleek_validator.ui.single_file_page import render_single_file_page
from amanleek_validator.ui.tpa_ingestion_page import render_tpa_ingestion_page
from amanleek_validator.ui.theme import apply_theme, render_sidebar_brand


APP_TITLE = "Amanleek Utilization File Validator"
APP_ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_theme()

try:
    container = build_container(APP_ROOT)
except RuntimeError as exc:
    st.error(f"Application configuration error: {exc}")
    st.stop()

with st.sidebar:
    render_sidebar_brand()
    st.markdown(
        '<div class="sidebar-label">Workspace</div>',
        unsafe_allow_html=True,
    )
    selected_page = st.radio(
        "Choose a page",
        (
            "Guide",
            "Single-file validation",
            "Batch check",
            "Batch validation",
            "CSV to XLSX",
            "Healthcare data ingestion",
        ),
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown(
        """
        <div class="sidebar-security">
            🔒 <strong>In-memory processing</strong><br>
            Files are not automatically stored on the server.
        </div>
        """,
        unsafe_allow_html=True,
    )

if selected_page == "Guide":
    render_guide_page()
elif selected_page == "Single-file validation":
    render_single_file_page(container.single_files)
elif selected_page == "Batch check":
    render_batch_page(container.batches)
elif selected_page == "Batch validation":
    render_batch_validation_page(container.batch_validation)
elif selected_page == "CSV to XLSX":
    render_csv_converter_page(container.csv_conversion)
else:
    render_tpa_ingestion_page()
