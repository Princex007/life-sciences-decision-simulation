"""Validated local JSON persistence for observed product histories.

Mirrors the simulation builder's storage rules: one file per record, an ID that can be
turned into a safe filename, and explicit validation before anything reaches disk.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from app.domain.history import ProductHistory

MAX_POINTS = 500


class HistoryValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class ProductHistoryStore:
    """CRUD for stored period series, with no engine or forecast coupling."""

    def __init__(self, storage_dir: Path | str | None = None):
        project = Path(__file__).resolve().parents[2]
        self.storage_dir = Path(storage_dir) if storage_dir else project / "histories"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[ProductHistory]:
        return [ProductHistory.model_validate(json.loads(path.read_text(encoding="utf-8")))
                for path in sorted(self.storage_dir.glob("*.json"))]

    def get(self, history_id: str) -> ProductHistory:
        path = self._path(history_id)
        if not path.is_file():
            raise FileNotFoundError(f"Product history '{history_id}' was not found.")
        return ProductHistory.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def create(self, history: ProductHistory) -> ProductHistory:
        self.validate(history)
        path = self._path(history.history_id)
        if path.exists():
            raise FileExistsError(f"Product history '{history.history_id}' already exists.")
        self._write(path, history)
        return history

    def update(self, history_id: str, history: ProductHistory) -> ProductHistory:
        if history_id != history.history_id:
            raise HistoryValidationError(["Path history ID must match history_id."])
        path = self._path(history_id)
        if not path.is_file():
            raise FileNotFoundError(f"Product history '{history_id}' was not found.")
        self.validate(history)
        self._write(path, history)
        return history

    def delete(self, history_id: str) -> None:
        path = self._path(history_id)
        if not path.is_file():
            raise FileNotFoundError(f"Product history '{history_id}' was not found.")
        path.unlink()

    def validate(self, history: ProductHistory) -> list[str]:
        self._path(history.history_id)
        # Pydantic already bounds the length and rejects non-numbers; infinity is the
        # one value that would silently poison every downstream fit.
        errors = [f"Value at period {index} is not a finite number."
                  for index, value in enumerate(history.values) if not math.isfinite(value)]
        if errors:
            raise HistoryValidationError(errors)
        return []

    def _path(self, history_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", history_id):
            raise ValueError("History ID may contain only letters, numbers, underscores, and hyphens.")
        return self.storage_dir / f"{history_id}.json"

    @staticmethod
    def _write(path: Path, history: ProductHistory) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history.model_dump(mode="json"), indent=2), encoding="utf-8")
