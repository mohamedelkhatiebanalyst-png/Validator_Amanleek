from __future__ import annotations

import logging
from hashlib import sha256
from io import BytesIO

import pandas as pd
import streamlit as st

from amanleek_validator.application.tpa_ingestion import (
    CLAIM_DATETIME_FORMAT,
    TABLE_FIELDS,
    apply_master_data,
    apply_mapping,
    build_ingestion_frames,
    clear_unknown_disease_codes,
    normalize_standardized,
    read_csv_source,
    validate_ingestion,
)
from amanleek_validator.infrastructure.sql_server import SqlServerGateway
from amanleek_validator.ui.theme import render_page_header, render_section_heading


logger = logging.getLogger(__name__)
NOT_MAPPED = "-- Not Mapped --"
REQUIRED_MAPPING = {
    "Members": {"Member_ID"},
    "Transactions": {"Claim_Date", "Member_ID"},
}
DB_COLUMNS = {
    "Members": set(TABLE_FIELDS["Members"]) | {"Client_ID"},
    "Transactions": {
        "Claim_ID", "Member_ID", "Provider_ID", "Date_ID", "Service_Name",
        "Service_Amount", "ICD_10_Code", "Service_Category", "Claim_Type",
        "Chronic_Flag", "Network_Flag",
        "Client_ID", "Transaction_ID",
    },
    "Date_Dimension": {
        "Date_ID", "Date", "Day", "Day_Name", "Day_of_Week", "Day_of_Month",
        "Day_of_Year", "Week", "Week_Number", "Month", "Month_Number",
        "Quarter", "Quarter_Number", "Year", "Year_Month", "Year_Quarter",
        "Is_Weekend",
    },
}


def render_tpa_ingestion_page() -> None:
    render_page_header(
        "Data ingestion",
        "Healthcare Data Ingestion",
        "Connect to SQL Server, map members and transactions, then validate and "
        "ingest them safely. Diseases are static reference data and provider "
        "ingestion is disabled.",
    )
    connection = _connection_section()
    if connection is None:
        return
    gateway, destinations, tpa_id, client_id = connection

    uploaded = st.file_uploader(
        "Upload an Excel workbook or CSV file",
        type=["xlsx", "xls", "csv"],
        key="tpa_upload",
    )
    if uploaded is None:
        st.info("Upload an XLSX, XLS, or UTF-8 CSV file to begin.")
        return
    content = uploaded.getvalue()
    upload_id = sha256(uploaded.name.encode() + content).hexdigest()
    if st.session_state.get("ingestion_upload_id") != upload_id:
        _clear_ingestion_state()
        st.session_state["ingestion_upload_id"] = upload_id
    try:
        if uploaded.name.lower().endswith(".csv"):
            sheet = "CSV"
            raw_df = read_csv_source(content)
        else:
            workbook = pd.ExcelFile(BytesIO(content))
            sheet = st.selectbox(
                "Worksheet", workbook.sheet_names, key="ingestion_sheet"
            )
            raw_df = pd.read_excel(workbook, sheet_name=sheet, dtype=object)
    except Exception as exc:
        logger.exception("Ingestion source file could not be read")
        st.error(f"The uploaded file could not be read: {exc}")
        return
    if raw_df.empty:
        st.error("The selected worksheet is empty.")
        return

    render_section_heading("1. Preview")
    columns = st.columns(4)
    columns[0].metric("File", uploaded.name)
    columns[1].metric("Sheet", sheet)
    columns[2].metric("Rows", len(raw_df))
    columns[3].metric("Columns", len(raw_df.columns))
    st.dataframe(raw_df.head(20), width="stretch", hide_index=True)

    render_section_heading(
        "2. Map fields",
        "Fields marked Required must be mapped before ingestion. Date Dimension is "
        "created automatically from Claim Date.",
    )
    mapping = _mapping_editor(tuple(str(column) for column in raw_df.columns))
    clicked = st.button("Apply mapping and validate", type="primary")
    if not clicked and "ingestion_frames" not in st.session_state:
        return
    if clicked or st.session_state.get("ingestion_mapping") != mapping:
        standardized = normalize_standardized(apply_mapping(raw_df, mapping))
        frames = build_ingestion_frames(standardized)
        validation = validate_ingestion(
            frames, len(raw_df), len(raw_df.columns), mapping,
            providers_enabled=False,
        )
        st.session_state["ingestion_mapping"] = mapping
        st.session_state["ingestion_frames"] = frames
        st.session_state["ingestion_validation"] = validation
        st.session_state.pop("ingestion_comparisons", None)

    frames = apply_master_data(
        st.session_state["ingestion_frames"], tpa_id, client_id
    )
    validation = st.session_state["ingestion_validation"]
    render_section_heading("3. Validate and review")
    frame_tabs = st.tabs(("Standardized", "Members", "Transactions"))
    for index, (tab, frame) in enumerate(zip(frame_tabs, (
        frames.standardized, frames.members, frames.transactions,
    ))):
        with tab:
            st.caption(f"{len(frame):,} row(s)")
            display_frame = frame.head(200).copy()
            if index == 0 and "Claim_Date" in display_frame.columns:
                display_frame["Claim_Date"] = display_frame["Claim_Date"].dt.strftime(
                    CLAIM_DATETIME_FORMAT
                )
                st.caption("Claim Date format: yyyy-MM-dd HH:mm:ss")
            st.dataframe(display_frame, width="stretch", hide_index=True)
    _render_validation(validation)
    if not validation.can_load:
        st.error("Ingestion is disabled until critical validation errors are resolved.")
        return

    render_section_heading("4. Compare with SQL Server")
    allow_unknown_icd = st.checkbox(
        "Load unknown ICD codes as blank (NULL)",
        value=False,
        help=(
            "Codes absent from dbo.icds will not be stored in Transactions. "
            "Known codes are preserved."
        ),
    )
    if st.button("Compare all datasets"):
        try:
            with gateway.connect() as database_connection:
                missing_icd_codes = gateway.missing_disease_codes(
                    database_connection,
                    frames.transactions["ICD_10_Code"].dropna().tolist(),
                )
                comparison_frames = frames
                cleared_icd_rows = 0
                if missing_icd_codes and allow_unknown_icd:
                    comparison_frames, cleared_icd_rows = clear_unknown_disease_codes(
                        frames, missing_icd_codes
                    )
                if missing_icd_codes and not allow_unknown_icd:
                    st.error(
                        "Ingestion is blocked because the following ICD codes are not "
                        "present in dbo.icds: "
                        + ", ".join(missing_icd_codes[:50])
                    )
                    if len(missing_icd_codes) > 50:
                        st.caption(f"And {len(missing_icd_codes) - 50} more code(s).")
                    return
                comparisons = {
                    "Members": gateway.compare(database_connection, destinations["Members"], "Member_ID", comparison_frames.members),
                    "Transactions": gateway.compare_transactions(database_connection, comparison_frames.transactions, destinations["Transactions"]),
                }
            st.session_state["ingestion_comparisons"] = comparisons
            st.session_state["ingestion_destinations"] = destinations
            st.session_state["ingestion_master_ids"] = (tpa_id, client_id)
            st.session_state["ingestion_allow_unknown_icd"] = allow_unknown_icd
            st.session_state["ingestion_missing_icd_codes"] = tuple(missing_icd_codes)
            st.session_state["ingestion_cleared_icd_rows"] = cleared_icd_rows
        except Exception:
            logger.exception("Database comparison failed")
            st.error("SQL Server comparison failed. Check the application logs.")
            return
    comparisons = st.session_state.get("ingestion_comparisons")
    if st.session_state.get("ingestion_destinations") != destinations:
        comparisons = None
    if st.session_state.get("ingestion_master_ids") != (tpa_id, client_id):
        comparisons = None
    if st.session_state.get("ingestion_allow_unknown_icd") != allow_unknown_icd:
        comparisons = None
    if not comparisons:
        return
    missing_icd_codes = st.session_state.get("ingestion_missing_icd_codes", ())
    if allow_unknown_icd and missing_icd_codes:
        frames, cleared_icd_rows = clear_unknown_disease_codes(
            frames, missing_icd_codes
        )
        st.warning(
            f"{cleared_icd_rows:,} transaction row(s) contain ICD codes absent "
            "from dbo.icds. Those codes will be loaded as NULL."
        )
    st.dataframe(pd.DataFrame([
        {"Dataset": name, "Incoming": value.incoming, "New": value.new,
         "Existing": value.existing, "Changed": value.changed}
        for name, value in comparisons.items()
    ]), width="stretch", hide_index=True)
    st.caption(
        "Load order: Members → Date Dimension → Transactions. "
        "All writes use one database transaction."
    )
    if st.button("Ingest validated data", type="primary"):
        try:
            counts = gateway.load_all(
                frames, destinations, tpa_id=tpa_id, client_id=client_id
            )
        except Exception as exc:
            logger.exception("Database ingestion rolled back")
            st.error(
                "Ingestion failed and all database changes were rolled back. "
                f"Database error: {_safe_database_error(exc)}"
            )
            return
        st.success("Data ingested successfully")
        st.dataframe(pd.DataFrame(counts.items(), columns=["Result", "Count"]), hide_index=True)


def _mapping_editor(raw_columns: tuple[str, ...]) -> dict[str, str | None]:
    options = (NOT_MAPPED, *raw_columns)
    mapping: dict[str, str | None] = {}
    enabled_fields = (
        ("Members", TABLE_FIELDS["Members"]),
        (
            "Transactions",
            tuple(field for field in TABLE_FIELDS["Transactions"] if field != "Provider_ID"),
        ),
    )
    tabs = st.tabs(("Members", "Transactions"))
    for tab, (table, fields) in zip(tabs, enabled_fields):
        with tab:
            required = REQUIRED_MAPPING[table]
            st.markdown(
                "**Required:** " + (", ".join(sorted(required)) if required else "None")
            )
            layout = st.columns(2)
            for index, field in enumerate(fields):
                if field in mapping:
                    st.info(f"{field} uses the mapping selected in an earlier tab.")
                    continue
                label = f"{field} *" if field in required else field
                selected = layout[index % 2].selectbox(
                    label, options, key=f"ingestion_map_{field}",
                    help="Required for ingestion" if field in required else "Optional",
                )
                mapping[field] = None if selected == NOT_MAPPED else selected
    return mapping


def _render_validation(validation: object) -> None:
    st.dataframe(
        pd.DataFrame(validation.metrics.items(), columns=["Validation check", "Count"]),
        width="stretch", hide_index=True,
    )
    if validation.errors:
        for message in validation.errors:
            st.error(message)
    else:
        st.success("Critical validation checks passed.")
    for message in validation.warnings:
        st.warning(message)
    for label, rows in validation.details.items():
        with st.expander(f"View {label} ({len(rows)} rows)"):
            st.dataframe(rows.head(500), width="stretch", hide_index=True)


def _connection_section() -> tuple[
    SqlServerGateway, dict[str, str], int, int
] | None:
    render_section_heading("Database connection")
    with st.expander("SQL Server settings", expanded="db_string" not in st.session_state):
        with st.form("db_form"):
            left, right = st.columns(2)
            server = left.text_input("Server", value=r"DESKTOP-VSJU84N\SQLEXPRESS")
            database = right.text_input("Database", value="Amanleek")
            driver = left.selectbox("ODBC driver", ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"))
            authentication = right.selectbox("Authentication", ("Windows authentication", "SQL Server login"))
            username = left.text_input("Username", disabled=authentication == "Windows authentication")
            password = right.text_input("Password", type="password", disabled=authentication == "Windows authentication")
            trust = st.checkbox("Trust local server certificate", value=True)
            connect_clicked = st.form_submit_button("Test connection", type="primary")
    if connect_clicked:
        if not server.strip() or not database.strip():
            st.error("Server and Database are required.")
            return None
        if authentication == "SQL Server login" and (not username.strip() or not password):
            st.error("Username and Password are required for SQL Server login.")
            return None
        value = _build_connection_string(driver, server, database, authentication, username, password, trust)
        try:
            candidate = SqlServerGateway(value)
            tables = candidate.list_tables()
        except Exception:
            logger.exception("Connection test failed")
            st.error("Connection failed. Check the settings and application logs.")
            return None
        st.session_state["db_string"] = value
        st.session_state["db_tables"] = tables
        for key in list(st.session_state):
            if key.startswith("destination_"):
                st.session_state.pop(key)
    value = st.session_state.get("db_string")
    tables = st.session_state.get("db_tables", [])
    if not value:
        st.info("Enter the SQL Server details and test the connection.")
        return None
    st.success("Connected successfully to SQL Server.")
    if not tables:
        st.error("No user tables were found in this database.")
        return None
    gateway = SqlServerGateway(value)
    st.caption("Select and verify the destination for each dataset.")
    selectors = st.columns(2)
    destinations: dict[str, str] = {}
    for index, logical_name in enumerate(DB_COLUMNS):
        default = next(
            (position for position, table in enumerate(tables) if table.casefold().endswith("." + logical_name.casefold())),
            0,
        )
        destinations[logical_name] = selectors[index % 2].selectbox(
            logical_name.replace("_", " "), tables, index=default,
            key=f"destination_{logical_name}",
        )
    problems = []
    try:
        for logical_name, table in destinations.items():
            missing = sorted(DB_COLUMNS[logical_name] - gateway.table_columns(table))
            if missing:
                problems.append(f"{logical_name}: {table} is missing {', '.join(missing)}")
    except Exception:
        logger.exception("Destination schema inspection failed")
        st.error("Could not inspect the selected destination tables.")
        return None
    if problems:
        for problem in problems:
            st.error(problem)
        return None
    st.success("All three destination tables are compatible.")

    render_section_heading(
        "TPA and Client",
        "Choose existing master records. This ingestion cannot create or edit them.",
    )
    try:
        tpas = gateway.list_tpas()
    except Exception:
        logger.exception("TPA master data could not be loaded")
        st.error("Could not load TPA master data. Verify dbo.TPA and permissions.")
        return None
    if not tpas:
        st.error("No TPA records exist. Add a TPA in SQL Server before ingestion.")
        return None
    tpa_by_label = {
        f"{name} (ID: {identifier})": identifier for identifier, name in tpas
    }
    selected_tpa = st.selectbox("TPA", tuple(tpa_by_label), key="ingestion_tpa")
    tpa_id = tpa_by_label[selected_tpa]
    try:
        clients = gateway.list_clients(tpa_id)
    except Exception:
        logger.exception("Client master data could not be loaded")
        st.error("Could not load Clients for the selected TPA.")
        return None
    if not clients:
        st.error("The selected TPA has no Clients. Add one in SQL Server first.")
        return None
    client_by_label = {
        f"{name} (ID: {identifier})": identifier for identifier, name in clients
    }
    selected_client = st.selectbox(
        "Client", tuple(client_by_label), key="ingestion_client"
    )
    return gateway, destinations, tpa_id, client_by_label[selected_client]


def _build_connection_string(
    driver: str, server: str, database: str, authentication: str,
    username: str, password: str, trust: bool,
) -> str:
    parts = [f"Driver={{{driver}}}", f"Server={_odbc_value(server)}",
             f"Database={_odbc_value(database)}", "Encrypt=yes",
             f"TrustServerCertificate={'yes' if trust else 'no'}"]
    if authentication == "Windows authentication":
        parts.append("Trusted_Connection=yes")
    else:
        parts.extend((f"UID={_odbc_value(username)}", f"PWD={_odbc_value(password)}"))
    return ";".join(parts)


def _odbc_value(value: str) -> str:
    return "{" + value.strip().replace("}", "}}") + "}"


def _safe_database_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    return message[:500] if message else error.__class__.__name__


def _clear_ingestion_state() -> None:
    for key in (
        "ingestion_sheet", "ingestion_mapping", "ingestion_frames",
        "ingestion_validation", "ingestion_comparisons", "ingestion_destinations",
        "ingestion_master_ids",
        "ingestion_allow_unknown_icd", "ingestion_missing_icd_codes",
        "ingestion_cleared_icd_rows",
    ):
        st.session_state.pop(key, None)
