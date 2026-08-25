from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import pandas as pd

from amanleek_validator.domain.validation import parse_mixed_datetime


TABLE_FIELDS = {
    "Members": (
        "Member_ID", "Member_Name", "Date_of_Birth", "Gender", "Country",
        "Region", "Relation",
    ),
    "Providers": (
        "Provider_ID", "Provider_Name", "Provider_Type", "Provider_Country",
        "Provider_Region",
    ),
    "Transactions": (
        "Claim_ID", "Claim_Date", "Service_Name", "Service_Amount",
        "ICD_10_Code", "Service_Category", "Claim_Type", "Chronic_Flag",
        "Network_Flag", "Member_ID", "Provider_ID",
    ),
}
STANDARD_FIELDS = tuple(dict.fromkeys(sum(TABLE_FIELDS.values(), ())))
IDENTIFIER_FIELDS = ("Member_ID", "Provider_ID", "Claim_ID", "ICD_10_Code")
DATE_FIELDS = ("Date_of_Birth", "Claim_Date")
FLAG_FIELDS = ("Chronic_Flag", "Network_Flag")
CLAIM_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def read_csv_source(content: bytes) -> pd.DataFrame:
    """Read a UTF-8 CSV while preserving identifier-like values as text."""
    if not content:
        raise ValueError("The CSV file is empty")
    try:
        return pd.read_csv(
            BytesIO(content), dtype=object, encoding="utf-8-sig"
        )
    except UnicodeDecodeError as exc:
        raise ValueError("The CSV file must use UTF-8 encoding") from exc
    except pd.errors.EmptyDataError as exc:
        raise ValueError("The CSV file has no header row") from exc


@dataclass
class ValidationResult:
    metrics: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, pd.DataFrame] = field(default_factory=dict)

    @property
    def can_load(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class IngestionFrames:
    standardized: pd.DataFrame
    members: pd.DataFrame
    providers: pd.DataFrame
    transactions: pd.DataFrame


def apply_master_data(
    frames: IngestionFrames,
    tpa_id: int,
    client_id: int,
) -> IngestionFrames:
    """Attach database-managed master keys without mutating validated frames."""
    if tpa_id <= 0 or client_id <= 0:
        raise ValueError("TPA_ID and Client_ID must be positive integers")
    members = frames.members.copy()
    transactions = frames.transactions.copy()
    members["Client_ID"] = client_id
    transactions["Client_ID"] = client_id
    return IngestionFrames(
        standardized=frames.standardized,
        members=members,
        providers=frames.providers,
        transactions=transactions,
    )


def clear_unknown_disease_codes(
    frames: IngestionFrames,
    unknown_codes: tuple[str, ...] | list[str],
) -> tuple[IngestionFrames, int]:
    """Replace explicitly identified unknown ICD codes with null for loading."""
    normalized = {str(code).strip().casefold() for code in unknown_codes}
    transactions = frames.transactions.copy()
    mask = transactions["ICD_10_Code"].map(
        lambda value: (
            False
            if pd.isna(value)
            else str(value).strip().casefold() in normalized
        )
    )
    transactions.loc[mask, "ICD_10_Code"] = pd.NA
    return (
        IngestionFrames(
            standardized=frames.standardized,
            members=frames.members,
            providers=frames.providers,
            transactions=transactions,
        ),
        int(mask.sum()),
    )


def validate_members(data: pd.DataFrame, raw_rows: int, raw_columns: int) -> ValidationResult:
    """Validate the first ingestion phase: the Members dimension only."""
    member_columns = list(TABLE_FIELDS["Members"])
    members_source = data.loc[:, member_columns]
    missing = members_source["Member_ID"].isna()
    conflicts = conflicting_keys(members_source, "Member_ID")
    conflict_count = conflicts["Member_ID"].nunique(dropna=True)
    result = ValidationResult(metrics={
        "Total source rows": raw_rows,
        "Total source columns": raw_columns,
        "Unique Member IDs": members_source["Member_ID"].nunique(dropna=True),
        "Missing Member IDs": int(missing.sum()),
        "Conflicting Member IDs": conflict_count,
    })
    if missing.any():
        result.errors.append(f"{int(missing.sum())} row(s) have no Member_ID.")
        result.details["Missing Member IDs"] = members_source.loc[missing]
    if conflict_count:
        result.errors.append(
            f"{conflict_count} Member_ID value(s) contain conflicting member information."
        )
        result.details["Conflicting Member IDs"] = conflicts
    return result


def apply_mapping(raw_df: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Return a canonical copy; the uploaded dataframe is never mutated."""
    result = pd.DataFrame(index=raw_df.index)
    for target in STANDARD_FIELDS:
        source = mapping.get(target)
        result[target] = raw_df[source].copy() if source in raw_df.columns else pd.NA
    return result


def normalize_bit_flag(value: Any) -> int | pd._libs.missing.NAType:
    if pd.isna(value):
        return pd.NA
    normalized = str(value).strip().casefold()
    if normalized in {"yes", "y", "true", "1", "1.0"}:
        return 1
    if normalized in {"no", "n", "false", "0", "0.0"}:
        return 0
    return pd.NA


def normalize_standardized(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    for column in result.columns:
        if column not in DATE_FIELDS and column != "Service_Amount":
            result[column] = result[column].map(_clean_string)
    for column in DATE_FIELDS:
        result[column] = parse_mixed_datetime(result[column])
    result["Service_Amount"] = pd.to_numeric(
        result["Service_Amount"], errors="coerce"
    )
    for column in FLAG_FIELDS:
        result[column] = result[column].map(normalize_bit_flag).astype("Int64")
    return result


def build_ingestion_frames(standardized: pd.DataFrame) -> IngestionFrames:
    members = _dimension(standardized, TABLE_FIELDS["Members"], "Member_ID")
    providers = _dimension(standardized, TABLE_FIELDS["Providers"], "Provider_ID")
    transaction_columns = [
        "Claim_ID", "Member_ID", "Provider_ID", "Claim_Date", "Service_Name",
        "Service_Amount", "ICD_10_Code", "Service_Category", "Claim_Type",
        "Chronic_Flag", "Network_Flag",
    ]
    transactions = standardized.loc[:, transaction_columns].copy()
    transactions = transactions.rename(columns={"Claim_Date": "Date_ID"})
    transactions["Date_ID"] = transactions["Date_ID"].dt.date
    transactions = transactions.drop_duplicates()
    return IngestionFrames(standardized, members, providers, transactions)


def validate_ingestion(
    frames: IngestionFrames,
    raw_rows: int,
    raw_columns: int,
    mapping: dict[str, str | None] | None = None,
    providers_enabled: bool = True,
) -> ValidationResult:
    data = frames.standardized
    result = ValidationResult(metrics={
        "Total rows": raw_rows,
        "Total columns": raw_columns,
        "Unique Member IDs": data["Member_ID"].nunique(dropna=True),
        "Missing Member IDs": int(data["Member_ID"].isna().sum()),
        "Unique Provider IDs": data["Provider_ID"].nunique(dropna=True),
        "Missing Provider IDs": int(data["Provider_ID"].isna().sum()),
        "Unique ICD codes": data["ICD_10_Code"].nunique(dropna=True),
        "Missing ICD codes": int(data["ICD_10_Code"].isna().sum()),
        "Total transactions": len(data),
        "Unique Claim IDs": data["Claim_ID"].nunique(dropna=True),
        "Missing Claim IDs": int(data["Claim_ID"].isna().sum()),
    })
    required_identifiers = [("Member_ID", "Member_ID")]
    if providers_enabled:
        required_identifiers.append(("Provider_ID", "Provider_ID"))
    for column, label in required_identifiers:
        missing = data[column].isna()
        if missing.any():
            result.errors.append(f"{int(missing.sum())} row(s) have missing {label}.")
            result.details[f"Missing {label}"] = data.loc[missing]

    missing_claim_ids = int(data["Claim_ID"].isna().sum())
    if missing_claim_ids:
        result.warnings.append(
            f"{missing_claim_ids} row(s) have no Claim_ID. Exact-row comparison "
            "will be used for those transactions."
        )
        result.details["Missing Claim_ID"] = data.loc[data["Claim_ID"].isna()]

    _invalid_from_source(data, "Claim_Date", "Invalid Claim Dates", result, critical=True)
    if mapping is None or mapping.get("Service_Amount"):
        _invalid_from_source(data, "Service_Amount", "Invalid Service Amounts", result)
    for column in FLAG_FIELDS:
        if mapping is None or mapping.get(column):
            _invalid_from_source(data, column, f"Invalid {column.replace('_', ' ')}", result)

    if result.metrics["Missing ICD codes"]:
        result.warnings.append(
            f"{result.metrics['Missing ICD codes']} row(s) have no ICD code."
        )
    dimension_checks = [
        (data.loc[:, list(TABLE_FIELDS["Members"])], "Member_ID", "Member IDs"),
    ]
    if providers_enabled:
        dimension_checks.insert(
            1,
            (data.loc[:, list(TABLE_FIELDS["Providers"])], "Provider_ID", "Provider IDs"),
        )
    for frame, key, label in dimension_checks:
        conflicts = conflicting_keys(frame, key)
        conflict_count = conflicts[key].nunique(dropna=True)
        result.metrics[f"Conflicting {label}"] = conflict_count
        if not conflicts.empty:
            result.warnings.append(f"Conflicting values found for {conflict_count} {label}.")
            result.details[f"Conflicting {label}"] = conflicts

    present_claim_ids = data["Claim_ID"].dropna()
    repeated_claim_rows = int(present_claim_ids.duplicated(keep=False).sum())
    result.metrics["Rows sharing a Claim ID"] = repeated_claim_rows
    if repeated_claim_rows:
        result.warnings.append(
            f"{repeated_claim_rows} row(s) share a Claim_ID and will be treated as "
            "separate transaction line items."
        )
    return result


def conflicting_keys(data: pd.DataFrame, key: str) -> pd.DataFrame:
    usable = data[data[key].notna()]
    if usable.empty:
        return usable
    non_keys = [column for column in usable.columns if column != key]
    conflict_ids = [
        value for value, group in usable.groupby(key, dropna=True)
        if len(group.loc[:, non_keys].drop_duplicates()) > 1
    ]
    return usable[usable[key].isin(conflict_ids)].sort_values(key)


def _dimension(data: pd.DataFrame, columns: tuple[str, ...], key: str) -> pd.DataFrame:
    return data.loc[data[key].notna(), list(columns)].drop_duplicates(key, keep="first")


def _clean_string(value: Any) -> Any:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    return text if text else pd.NA


def _invalid_from_source(
    data: pd.DataFrame,
    column: str,
    label: str,
    result: ValidationResult,
    critical: bool = False,
) -> None:
    # A mapped, non-empty source value that normalized to null is invalid. The UI
    # also treats an entirely missing required date as invalid.
    invalid = data[column].isna()
    count = int(invalid.sum())
    result.metrics[label] = count
    if not count:
        return
    message = f"{count} row(s) have {label.lower()}."
    (result.errors if critical else result.warnings).append(message)
    result.details[label] = data.loc[invalid]
