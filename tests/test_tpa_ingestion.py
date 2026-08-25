from __future__ import annotations

import unittest

import pandas as pd

from amanleek_validator.application.tpa_ingestion import (
    apply_mapping,
    apply_master_data,
    build_ingestion_frames,
    clear_unknown_disease_codes,
    normalize_bit_flag,
    normalize_standardized,
    read_csv_source,
    validate_members,
    validate_ingestion,
)
from amanleek_validator.infrastructure.sql_server import SqlServerGateway


class _MasterDataCursor:
    def __init__(self, found: bool) -> None:
        self.found = found
        self.parameters: tuple[int, int] | None = None

    def execute(self, _query: str, *parameters: int) -> None:
        self.parameters = parameters

    def fetchone(self) -> tuple[int] | None:
        return (1,) if self.found else None


class _MasterDataConnection:
    def __init__(self, found: bool) -> None:
        self.test_cursor = _MasterDataCursor(found)

    def cursor(self) -> _MasterDataCursor:
        return self.test_cursor


class _TransactionComparisonGateway(SqlServerGateway):
    def __init__(self, existing: pd.DataFrame) -> None:
        super().__init__("unused")
        self.existing = existing

    def _fetch_keys(
        self, _connection: object, _table: str, _key: str, _values: list[object]
    ) -> pd.DataFrame:
        if not _values:
            return pd.DataFrame()
        requested = {str(value).casefold() for value in _values}
        return self.existing[
            self.existing[_key].map(lambda value: str(value).casefold() in requested)
        ].copy()

    def _fetch_null_claim_transactions(
        self, _connection: object, _table: str, client_ids: list[object]
    ) -> pd.DataFrame:
        if not client_ids:
            return pd.DataFrame()
        return self.existing[
            self.existing["Claim_ID"].isna()
            & self.existing["Client_ID"].isin(client_ids)
        ].copy()


class TpaIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = pd.DataFrame({
            "Member Number": ["001", "001", "002"],
            "Provider Code": ["P1", "P1", "P1"],
            "Claim Number": ["C1", "C2", "C3"],
            "Claim Date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "ICD": ["E11.9", "E11.9", "E11.9"],
            "Amount": [10, 20, 30],
        })
        self.mapping = {
            "Member_ID": "Member Number", "Provider_ID": "Provider Code",
            "Claim_ID": "Claim Number", "Claim_Date": "Claim Date",
            "ICD_10_Code": "ICD", "Service_Amount": "Amount",
        }

    def test_mapping_preserves_source_and_identifier_leading_zeros(self) -> None:
        original = self.raw.copy(deep=True)
        standardized = normalize_standardized(apply_mapping(self.raw, self.mapping))
        pd.testing.assert_frame_equal(self.raw, original)
        self.assertEqual("001", standardized.at[0, "Member_ID"])

    def test_csv_source_preserves_identifier_leading_zeros(self) -> None:
        data = read_csv_source(
            b"Member Number,Claim Number,Amount\n001,C01,10\n"
        )

        self.assertEqual("001", data.at[0, "Member Number"])
        self.assertEqual("C01", data.at[0, "Claim Number"])

    def test_csv_source_rejects_non_utf8_content(self) -> None:
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            read_csv_source(b"Name\n\xff\n")

    def test_claim_dates_use_canonical_format_without_changing_values(self) -> None:
        raw = self.raw.assign(**{
            "Claim Date": [
                "2026-01-01 08:30:45.987654",
                "2026/01/02 13:45:12",
                "Jan 3, 2026 01:02:03",
            ]
        })

        standardized = normalize_standardized(apply_mapping(raw, self.mapping))

        self.assertEqual(
            [
                "2026-01-01 08:30:45",
                "2026-01-02 13:45:12",
                "2026-01-03 01:02:03",
            ],
            standardized["Claim_Date"].dt.strftime(
                "%Y-%m-%d %H:%M:%S"
            ).tolist(),
        )
        frames = build_ingestion_frames(standardized)
        self.assertEqual("2026-01-01", frames.transactions.at[0, "Date_ID"].isoformat())

    def test_member_dimension_deduplicates_while_claims_remain(self) -> None:
        frames = build_ingestion_frames(
            normalize_standardized(apply_mapping(self.raw, self.mapping))
        )
        self.assertEqual(2, len(frames.members))
        self.assertEqual(1, len(frames.providers))
        self.assertEqual(3, len(frames.transactions))

    def test_repeated_claim_id_is_allowed_as_separate_line_item(self) -> None:
        raw = pd.concat([self.raw, self.raw.iloc[[0]].assign(Amount=99)], ignore_index=True)
        frames = build_ingestion_frames(normalize_standardized(apply_mapping(raw, self.mapping)))
        result = validate_ingestion(frames, len(raw), len(raw.columns))
        self.assertTrue(result.can_load)
        self.assertEqual(2, result.metrics["Rows sharing a Claim ID"])

    def test_missing_claim_id_is_warning_not_blocking_error(self) -> None:
        raw = self.raw.assign(**{"Claim Number": [None, "C2", "C3"]})
        frames = build_ingestion_frames(
            normalize_standardized(apply_mapping(raw, self.mapping))
        )

        result = validate_ingestion(frames, len(raw), len(raw.columns))

        self.assertTrue(result.can_load)
        self.assertEqual(1, result.metrics["Missing Claim IDs"])
        self.assertEqual(0, result.metrics["Rows sharing a Claim ID"])

    def test_bit_normalization_does_not_assume_unknown_is_false(self) -> None:
        self.assertEqual(1, normalize_bit_flag("YES"))
        self.assertEqual(0, normalize_bit_flag("n"))
        self.assertTrue(pd.isna(normalize_bit_flag("maybe")))

    def test_member_validation_blocks_conflicting_member_details(self) -> None:
        raw = self.raw.assign(**{"Member Name": ["Ali", "Different", "Mona"]})
        mapping = {**self.mapping, "Member_Name": "Member Name"}
        standardized = normalize_standardized(apply_mapping(raw, mapping))

        result = validate_members(standardized, len(raw), len(raw.columns))

        self.assertFalse(result.can_load)
        self.assertEqual(1, result.metrics["Conflicting Member IDs"])

    def test_master_data_keys_are_added_without_mutating_base_frames(self) -> None:
        frames = build_ingestion_frames(
            normalize_standardized(apply_mapping(self.raw, self.mapping))
        )

        contextual = apply_master_data(frames, tpa_id=7, client_id=12)

        self.assertNotIn("Client_ID", frames.members.columns)
        self.assertNotIn("TPA_ID", frames.transactions.columns)
        self.assertEqual({12}, set(contextual.members["Client_ID"]))
        self.assertNotIn("TPA_ID", contextual.transactions.columns)
        self.assertEqual({12}, set(contextual.transactions["Client_ID"]))

    def test_master_data_keys_must_be_positive(self) -> None:
        frames = build_ingestion_frames(
            normalize_standardized(apply_mapping(self.raw, self.mapping))
        )
        with self.assertRaises(ValueError):
            apply_master_data(frames, tpa_id=0, client_id=12)

    def test_master_data_relationship_is_verified_by_both_ids(self) -> None:
        connection = _MasterDataConnection(found=True)

        SqlServerGateway._verify_master_data(connection, tpa_id=7, client_id=12)

        self.assertEqual((7, 12), connection.test_cursor.parameters)

    def test_invalid_master_data_relationship_blocks_loading(self) -> None:
        connection = _MasterDataConnection(found=False)
        with self.assertRaisesRegex(ValueError, "does not belong"):
            SqlServerGateway._verify_master_data(
                connection, tpa_id=7, client_id=12
            )

    def test_transaction_comparison_ignores_identity_and_skips_exact_row(self) -> None:
        frames = build_ingestion_frames(
            normalize_standardized(apply_mapping(self.raw, self.mapping))
        )
        transactions = apply_master_data(frames, 7, 12).transactions
        existing = transactions.iloc[[0]].assign(Transaction_ID=99)
        gateway = _TransactionComparisonGateway(existing)

        comparison = gateway.compare_transactions(
            object(), transactions, "dbo.Transactions"
        )

        self.assertEqual(3, comparison.incoming)
        self.assertEqual(2, comparison.new)
        self.assertEqual(1, comparison.existing)
        self.assertEqual(0, comparison.changed)

    def test_same_claim_with_different_line_data_is_new_transaction(self) -> None:
        frames = build_ingestion_frames(
            normalize_standardized(apply_mapping(self.raw, self.mapping))
        )
        transactions = apply_master_data(frames, 7, 12).transactions.iloc[[0]]
        existing = transactions.assign(Service_Amount=999, Transaction_ID=99)
        gateway = _TransactionComparisonGateway(existing)

        comparison = gateway.compare_transactions(
            object(), transactions, "dbo.Transactions"
        )

        self.assertEqual(1, comparison.new)
        self.assertEqual(0, comparison.existing)

    def test_unknown_disease_codes_are_reported_from_static_reference(self) -> None:
        existing = pd.DataFrame({"code": ["E11.9"]})
        gateway = _TransactionComparisonGateway(existing)

        missing = gateway.missing_disease_codes(
            object(), ["e11.9", "A01", pd.NA, ""]
        )

        self.assertEqual(["A01"], missing)

    def test_unknown_disease_codes_can_be_cleared_without_mutating_frames(self) -> None:
        frames = build_ingestion_frames(
            normalize_standardized(apply_mapping(self.raw, self.mapping))
        )

        cleared, count = clear_unknown_disease_codes(frames, ["e11.9"])

        self.assertEqual(3, count)
        self.assertTrue(cleared.transactions["ICD_10_Code"].isna().all())
        self.assertTrue(frames.transactions["ICD_10_Code"].notna().all())

    def test_null_claim_id_exact_row_is_skipped_on_repeat_ingestion(self) -> None:
        raw = self.raw.assign(**{"Claim Number": [None, "C2", "C3"]})
        frames = build_ingestion_frames(
            normalize_standardized(apply_mapping(raw, self.mapping))
        )
        transactions = apply_master_data(frames, 7, 12).transactions
        existing = transactions.iloc[[0]].assign(Transaction_ID=99)
        gateway = _TransactionComparisonGateway(existing)

        comparison = gateway.compare_transactions(
            object(), transactions.iloc[[0]], "dbo.Transactions"
        )

        self.assertEqual(0, comparison.new)
        self.assertEqual(1, comparison.existing)


if __name__ == "__main__":
    unittest.main()
