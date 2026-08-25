from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import streamlit as st

from amanleek_validator.application.csv_conversion import CsvConversionService
from amanleek_validator.ui.theme import (
    render_page_header,
    render_privacy_note,
    render_section_heading,
)


MAX_CONVERSION_FILES = 50


def render_csv_converter_page(service: CsvConversionService) -> None:
    render_page_header(
        "File conversion",
        "CSV to XLSX",
        "Convert multiple UTF-8 CSV files into Excel workbooks in memory.",
    )
    render_section_heading(
        "Upload CSV files",
        f"Select up to {MAX_CONVERSION_FILES} files. Each output contains sheet1.",
    )
    uploads = st.file_uploader(
        "Choose CSV files",
        type=["csv"],
        accept_multiple_files=True,
        key="csv_converter_uploads",
    )
    if not uploads:
        render_privacy_note()
        return
    if len(uploads) > MAX_CONVERSION_FILES:
        st.error(f"Upload no more than {MAX_CONVERSION_FILES} CSV files at once.")
        return

    converted: list[tuple[str, bytes]] = []
    used_names: set[str] = set()
    for upload in uploads:
        try:
            result = service.convert(upload.getvalue())
        except (OSError, ValueError) as exc:
            st.error(f"{upload.name}: {exc}")
            continue
        output_name = _unique_output_name(upload.name, used_names)
        converted.append((output_name, result.content))
        left, right = st.columns((3, 1))
        left.success(
            f"{upload.name}: {result.rows:,} row(s), "
            f"{result.columns:,} column(s)"
        )
        right.download_button(
            "Download XLSX",
            data=result.content,
            file_name=output_name,
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            key=f"csv_xlsx_download_{len(converted)}_{output_name}",
        )

    if converted:
        st.download_button(
            "Download all XLSX as ZIP",
            data=_zip_files(converted),
            file_name="converted_xlsx_files.zip",
            mime="application/zip",
            type="primary",
        )


def _unique_output_name(source_name: str, used: set[str]) -> str:
    base = Path(source_name).stem or "converted"
    candidate = f"{base}.xlsx"
    number = 2
    while candidate.casefold() in used:
        candidate = f"{base}_{number}.xlsx"
        number += 1
    used.add(candidate.casefold())
    return candidate


def _zip_files(files: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return output.getvalue()
