from __future__ import annotations

from typing import Protocol

import pandas as pd

from amanleek_validator.domain.models import (
    WorkbookStructure,
)


class WorkbookPort(Protocol):
    def inspect(self, content: bytes) -> WorkbookStructure: ...

    def read_sheet(self, content: bytes, sheet_name: str) -> pd.DataFrame: ...

    def write_excel(self, data: pd.DataFrame, sheet_name: str) -> bytes: ...

    def write_csv(self, data: pd.DataFrame) -> bytes: ...

    def rename_single_sheet(
        self,
        content: bytes,
        current_name: str,
        new_name: str,
    ) -> bytes: ...
