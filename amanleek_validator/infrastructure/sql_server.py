from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator

import pandas as pd
import numpy as np


@dataclass(frozen=True)
class Comparison:
    incoming: int
    new: int
    existing: int
    changed: int
    changed_rows: pd.DataFrame


class SqlServerGateway:
    """Parameterized, batched SQL Server access; credentials stay in configuration."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string

    @classmethod
    def from_environment(cls) -> "SqlServerGateway | None":
        value = os.getenv("AMANLEEK_SQL_CONNECTION_STRING", "").strip()
        return cls(value) if value else None

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError("pyodbc is required for SQL Server loading") from exc
        connection = pyodbc.connect(self.connection_string, autocommit=False)
        try:
            yield connection
        finally:
            connection.close()

    def compare(self, connection: Any, table: str, key: str, incoming: pd.DataFrame) -> Comparison:
        existing = self._fetch_keys(connection, table, key, incoming[key].dropna().tolist())
        if existing.empty:
            return Comparison(len(incoming), len(incoming), 0, 0, incoming.iloc[0:0])
        existing = existing.set_index(key)
        incoming_indexed = incoming.set_index(key)
        common = incoming_indexed.index.intersection(existing.index)
        changed_ids = []
        for value in common:
            if any(
                not _equal(incoming_indexed.at[value, column], existing.at[value, column])
                for column in incoming.columns if column != key
            ):
                changed_ids.append(value)
        changed = incoming[incoming[key].isin(changed_ids)]
        return Comparison(
            len(incoming), int((~incoming[key].isin(existing.index)).sum()),
            len(common), len(changed_ids), changed,
        )

    def compare_transactions(
        self,
        connection: Any,
        incoming: pd.DataFrame,
        table: str = "dbo.Transactions",
    ) -> Comparison:
        new_rows, existing_count = self._new_transaction_rows(
            connection, table, incoming
        )
        return Comparison(
            incoming=len(incoming),
            new=len(new_rows),
            existing=existing_count,
            changed=0,
            changed_rows=incoming.iloc[0:0],
        )

    def load_all(
        self,
        frames: Any,
        tables: dict[str, str] | None = None,
        tpa_id: int | None = None,
        client_id: int | None = None,
    ) -> dict[str, int]:
        destinations = tables or {
            "Members": "dbo.Members",
            "Providers": "dbo.Providers",
            "Date_Dimension": "dbo.Date_Dimension",
            "Transactions": "dbo.Transactions",
        }
        counts: dict[str, int] = {}
        with self.connect() as connection:
            try:
                if tpa_id is not None or client_id is not None:
                    if tpa_id is None or client_id is None:
                        raise ValueError("Both TPA_ID and Client_ID are required")
                    self._verify_master_data(connection, tpa_id, client_id)
                counts.update(self._upsert(connection, destinations["Members"], "Member_ID", frames.members))
                if "Providers" in destinations:
                    counts.update(self._upsert(connection, destinations["Providers"], "Provider_ID", frames.providers))
                counts["Dates inserted"] = self.ensure_date_dimension_dates(
                    connection,
                    frames.transactions["Date_ID"].dropna().unique(),
                    destinations["Date_Dimension"],
                )
                transaction_comparison = self.compare_transactions(
                    connection, frames.transactions, destinations["Transactions"]
                )
                new_transactions, _ = self._new_transaction_rows(
                    connection, destinations["Transactions"], frames.transactions
                )
                self._insert_rows(
                    connection, destinations["Transactions"], new_transactions
                )
                counts["Transactions inserted"] = len(new_transactions)
                counts["Transactions skipped"] = transaction_comparison.existing
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return counts

    def list_tables(self) -> list[str]:
        """Return selectable user tables as schema-qualified names."""
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_TYPE = ? ORDER BY TABLE_SCHEMA, TABLE_NAME",
                "BASE TABLE",
            )
            return [f"{row[0]}.{row[1]}" for row in cursor.fetchall()]

    def table_columns(self, table: str) -> set[str]:
        schema, name = _table_parts(table)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
                schema,
                name,
            )
            return {str(row[0]) for row in cursor.fetchall()}

    def list_tpas(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT TPA_ID, TPA_Name FROM dbo.TPA ORDER BY TPA_Name")
            return [(int(row[0]), str(row[1])) for row in cursor.fetchall()]

    def list_clients(self, tpa_id: int) -> list[tuple[int, str]]:
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT Client_ID, Client_Name FROM dbo.Clients "
                "WHERE TPA_ID = ? ORDER BY Client_Name",
                tpa_id,
            )
            return [(int(row[0]), str(row[1])) for row in cursor.fetchall()]

    def missing_disease_codes(
        self,
        connection: Any,
        codes: list[Any],
        table: str = "dbo.icds",
    ) -> list[str]:
        requested = {
            str(code).strip() for code in codes if pd.notna(code) and str(code).strip()
        }
        if not requested:
            return []
        existing = self._fetch_keys(
            connection, table, "code", sorted(requested)
        )
        existing_normalized = {
            str(code).strip().casefold()
            for code in existing.get("code", ())
            if pd.notna(code)
        }
        return sorted(
            code for code in requested if code.casefold() not in existing_normalized
        )

    @staticmethod
    def _verify_master_data(connection: Any, tpa_id: int, client_id: int) -> None:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT 1 FROM dbo.Clients c INNER JOIN dbo.TPA t ON t.TPA_ID = c.TPA_ID "
            "WHERE t.TPA_ID = ? AND c.Client_ID = ?",
            tpa_id,
            client_id,
        )
        if cursor.fetchone() is None:
            raise ValueError("The selected Client does not belong to the selected TPA")

    def load_members(self, members: pd.DataFrame, table: str = "dbo.Members") -> dict[str, int]:
        """Insert/update Members atomically without touching any other table."""
        with self.connect() as connection:
            try:
                counts = self._upsert(connection, table, "Member_ID", members)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return counts

    def ensure_date_dimension_dates(
        self,
        connection: Any,
        dates: Any,
        table: str = "dbo.Date_Dimension",
    ) -> int:
        values = sorted({value for value in dates if pd.notna(value)})
        existing = self._fetch_keys(connection, table, "Date_ID", values)
        existing_values = set(existing.get("Date_ID", []))
        rows = pd.DataFrame([_date_row(value) for value in values if value not in existing_values])
        self._insert_rows(connection, table, rows)
        return len(rows)

    def _upsert(self, connection: Any, table: str, key: str, data: pd.DataFrame) -> dict[str, int]:
        comparison = self.compare(connection, table, key, data)
        columns = [column for column in data.columns if column != key]
        cursor = connection.cursor()
        update_sql = ", ".join(f"[{column}] = COALESCE(?, [{column}])" for column in columns)
        for row in comparison.changed_rows.itertuples(index=False, name=None):
            record = dict(zip(data.columns, row))
            cursor.execute(
                f"UPDATE {_quote_table(table)} SET {update_sql} WHERE [{key}] = ?",
                *[_db_value(record[column]) for column in columns], _db_value(record[key]),
            )
        existing_keys = set(self._fetch_keys(connection, table, key, data[key].tolist()).get(key, []))
        new_rows = data[~data[key].isin(existing_keys)]
        self._insert_rows(connection, table, new_rows)
        return {
            f"{table} inserted": len(new_rows), f"{table} updated": comparison.changed,
            f"{table} skipped": comparison.existing - comparison.changed,
        }

    def _fetch_keys(self, connection: Any, table: str, key: str, values: list[Any]) -> pd.DataFrame:
        if not values:
            return pd.DataFrame()
        rows: list[tuple[Any, ...]] = []
        columns: list[str] = []
        cursor = connection.cursor()
        for start in range(0, len(values), 900):
            batch = values[start:start + 900]
            cursor.execute(
                f"SELECT * FROM {_quote_table(table)} WHERE [{key}] IN ({','.join('?' for _ in batch)})",
                *[_db_value(value) for value in batch],
            )
            if not columns:
                columns = [item[0] for item in cursor.description]
            rows.extend(cursor.fetchall())
        return pd.DataFrame.from_records(rows, columns=columns)

    def _new_transaction_rows(
        self,
        connection: Any,
        table: str,
        incoming: pd.DataFrame,
    ) -> tuple[pd.DataFrame, int]:
        """Return line items not already stored, ignoring the identity key."""
        if incoming.empty:
            return incoming.copy(), 0
        existing_with_claim_id = self._fetch_keys(
            connection,
            table,
            "Claim_ID",
            incoming["Claim_ID"].dropna().drop_duplicates().tolist(),
        )
        null_client_ids = (
            incoming.loc[incoming["Claim_ID"].isna(), "Client_ID"]
            .dropna()
            .drop_duplicates()
            .tolist()
        )
        existing_without_claim_id = self._fetch_null_claim_transactions(
            connection, table, null_client_ids
        )
        existing = pd.concat(
            (existing_with_claim_id, existing_without_claim_id),
            ignore_index=True,
        )
        comparable_columns = list(incoming.columns)
        if existing.empty:
            return incoming.copy(), 0
        missing = set(comparable_columns) - set(existing.columns)
        if missing:
            raise ValueError(
                "Transactions destination is missing columns: "
                + ", ".join(sorted(missing))
            )
        existing_by_claim: dict[Any, list[dict[str, Any]]] = {}
        for candidate in existing.loc[:, comparable_columns].to_dict("records"):
            bucket = _claim_bucket(candidate["Claim_ID"])
            existing_by_claim.setdefault(bucket, []).append(candidate)
        is_existing: list[bool] = []
        for record in incoming.to_dict("records"):
            candidates = existing_by_claim.get(_claim_bucket(record["Claim_ID"]), ())
            match = any(
                all(
                    _equal(record[column], candidate[column])
                    for column in comparable_columns
                )
                for candidate in candidates
            )
            is_existing.append(match)
        mask = pd.Series(is_existing, index=incoming.index, dtype=bool)
        return incoming.loc[~mask].copy(), int(mask.sum())

    @staticmethod
    def _fetch_null_claim_transactions(
        connection: Any,
        table: str,
        client_ids: list[Any],
    ) -> pd.DataFrame:
        if not client_ids:
            return pd.DataFrame()
        rows: list[tuple[Any, ...]] = []
        columns: list[str] = []
        cursor = connection.cursor()
        for start in range(0, len(client_ids), 900):
            batch = client_ids[start:start + 900]
            cursor.execute(
                f"SELECT * FROM {_quote_table(table)} WHERE [Claim_ID] IS NULL "
                f"AND [Client_ID] IN ({','.join('?' for _ in batch)})",
                *[_db_value(value) for value in batch],
            )
            if not columns:
                columns = [item[0] for item in cursor.description]
            rows.extend(cursor.fetchall())
        return pd.DataFrame.from_records(rows, columns=columns)

    @staticmethod
    def _insert_rows(connection: Any, table: str, data: pd.DataFrame) -> None:
        if data.empty:
            return
        columns = list(data.columns)
        sql = (
            f"INSERT INTO {_quote_table(table)} ({','.join(f'[{c}]' for c in columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})"
        )
        cursor = connection.cursor()
        cursor.fast_executemany = True
        cursor.executemany(sql, [tuple(_db_value(value) for value in row) for row in data.itertuples(index=False, name=None)])


def _date_row(value: date) -> dict[str, Any]:
    iso = value.isocalendar()
    quarter = (value.month - 1) // 3 + 1
    return {
        "Date_ID": value, "Date": value, "Day": value.day,
        "Day_Name": value.strftime("%A"), "Day_of_Week": value.isoweekday(),
        "Day_of_Month": value.day, "Day_of_Year": value.timetuple().tm_yday,
        "Week": iso.week, "Week_Number": iso.week, "Month": value.strftime("%B"),
        "Month_Number": value.month, "Quarter": f"Q{quarter}",
        "Quarter_Number": quarter, "Year": value.year,
        "Year_Month": value.strftime("%Y-%m"),
        "Year_Quarter": f"{value.year}-Q{quarter}",
        "Is_Weekend": int(value.isoweekday() >= 6),
    }


def _db_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _equal(left: Any, right: Any) -> bool:
    left_missing = bool(pd.isna(left))
    right_missing = bool(pd.isna(right))
    if left_missing or right_missing:
        return left_missing and right_missing
    return left == right


def _claim_bucket(value: Any) -> Any:
    return None if pd.isna(value) else value


def _table_parts(table: str) -> tuple[str, str]:
    parts = table.split(".", 1)
    schema, name = parts if len(parts) == 2 else ("dbo", parts[0])
    identifier = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    if not identifier.fullmatch(schema) or not identifier.fullmatch(name):
        raise ValueError("Invalid SQL Server table identifier")
    return schema, name


def _quote_table(table: str) -> str:
    schema, name = _table_parts(table)
    return f"[{schema}].[{name}]"
