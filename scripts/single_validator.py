"""Compatibility entrypoint for running only the single-file validator."""

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

if sys.version_info < (3, 11):
    raise RuntimeError(
        "This application requires Python 3.11 or newer. "
        f"You are running Python {sys.version.split()[0]} from {sys.executable}."
    )

import streamlit as st

from amanleek_validator.bootstrap import build_container
from amanleek_validator.ui.single_file_page import render_single_file_page


APP_TITLE = "Amanleek Utilization File Validator"

st.set_page_config(page_title=APP_TITLE, page_icon="✅", layout="wide")
st.title(APP_TITLE)

try:
    container = build_container(APP_ROOT)
except RuntimeError as exc:
    st.error(f"Application configuration error: {exc}")
    st.stop()

render_single_file_page(container.single_files)
