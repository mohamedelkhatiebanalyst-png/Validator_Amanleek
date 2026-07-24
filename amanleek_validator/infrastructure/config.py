from __future__ import annotations

import json
from pathlib import Path

from amanleek_validator.domain.schema import ValidationSchema


def load_schema(path: Path) -> ValidationSchema:
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Schema file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Schema file is invalid JSON: {exc}") from exc
    try:
        return ValidationSchema.from_mapping(values)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Schema configuration is invalid: {exc}") from exc

