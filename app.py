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
from amanleek_validator.ui.guide_page import render_guide_page
from amanleek_validator.ui.single_file_page import render_single_file_page


APP_TITLE = "Amanleek Utilization File Validator"
APP_ROOT = Path(__file__).resolve().parent

st.set_page_config(page_title=APP_TITLE, page_icon="✅", layout="wide")
st.title(APP_TITLE)

try:
    container = build_container(APP_ROOT)
except RuntimeError as exc:
    st.error(f"Application configuration error: {exc}")
    st.stop()

with st.sidebar:
    st.header("Navigation")
    selected_page = st.radio(
        "Choose a page",
        (
            "Guide",
            "Single-file validation",
            "Batch check",
        ),
        label_visibility="collapsed",
    )
    st.divider()
    st.caption(
        "Uploaded and generated files are processed in memory and are not "
        "automatically stored on the server."
    )

if selected_page == "Guide":
    render_guide_page()
elif selected_page == "Single-file validation":
    render_single_file_page(container.single_files)
else:
    render_batch_page(container.batches)
