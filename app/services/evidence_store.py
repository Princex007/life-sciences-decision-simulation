"""Deterministic evidence storage with in-memory and local JSON implementations."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, Iterable, Any

from app.domain.evidence import Evidence


class EvidenceStore(Protocol):
    def add(self, evidence: Evidence) -> Evidence: ...
    def update(self, evidence: Evidence) -> Evidence: ...
    def delete(self, evidence_id: str) -> bool: ...
    def get(self, evidence_id: str) -> Evidence | None: ...
    def list(self) -> list[Evidence]: ...
    def query(self, text: str = "", metadata: dict[str, Any] | None = None) -> list[Evidence]: ...


class InMemoryEvidenceStore:
    def __init__(self, records: Iterable[Evidence] = ()):
        self._records: dict[str, Evidence] = {}
        for item in records:
            self.add(item)

    def add(self, evidence: Evidence) -> Evidence:
        if evidence.evidence_id in self._records:
            raise FileExistsError(f"Evidence '{evidence.evidence_id}' already exists.")
        self._records[evidence.evidence_id] = evidence.model_copy(deep=True)
        return evidence.model_copy(deep=True)

    def get(self, evidence_id: str) -> Evidence | None:
        item = self._records.get(evidence_id)
        return item.model_copy(deep=True) if item else None

    def update(self, evidence: Evidence) -> Evidence:
        if evidence.evidence_id not in self._records:
            raise FileNotFoundError(f"Evidence '{evidence.evidence_id}' was not found.")
        self._records[evidence.evidence_id] = evidence.model_copy(deep=True)
        return evidence.model_copy(deep=True)

    def delete(self, evidence_id: str) -> bool:
        return self._records.pop(evidence_id, None) is not None

    def list(self) -> list[Evidence]:
        return [self._records[key].model_copy(deep=True) for key in sorted(self._records)]

    def query(self, text: str = "", metadata: dict[str, Any] | None = None) -> list[Evidence]:
        terms = {part.casefold() for part in re.findall(r"[\w-]+", text) if len(part) > 2}
        filters = metadata or {}
        result = []
        for item in self.list():
            values = item.model_dump(mode="python")
            if any(key not in values or (value not in values[key] if isinstance(values[key], list)
                    else values[key] != value) for key, value in filters.items()):
                continue
            haystack = " ".join([item.title, item.content, item.source, item.domain, *item.tags]).casefold()
            if terms and not any(term in haystack for term in terms):
                continue
            result.append(item)
        return result

    def filter_metadata(self, **metadata: Any) -> list[Evidence]:
        return self.query(metadata=metadata)


class JsonEvidenceStore(InMemoryEvidenceStore):
    """One JSON file per evidence record; IDs are constrained to safe filenames."""
    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def add(self, evidence: Evidence) -> Evidence:
        path = self._path(evidence.evidence_id)
        if path.exists():
            raise FileExistsError(f"Evidence '{evidence.evidence_id}' already exists.")
        path.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
        return evidence.model_copy(deep=True)

    def get(self, evidence_id: str) -> Evidence | None:
        path = self._path(evidence_id)
        return Evidence.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None

    def update(self, evidence: Evidence) -> Evidence:
        path = self._path(evidence.evidence_id)
        if not path.is_file():
            raise FileNotFoundError(f"Evidence '{evidence.evidence_id}' was not found.")
        path.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
        return evidence.model_copy(deep=True)

    def delete(self, evidence_id: str) -> bool:
        path = self._path(evidence_id)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def list(self) -> list[Evidence]:
        return [Evidence.model_validate_json(path.read_text(encoding="utf-8"))
                for path in sorted(self.directory.glob("*.json"))]

    def _path(self, evidence_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", evidence_id):
            raise ValueError("Evidence ID may contain only letters, numbers, underscores, and hyphens.")
        return self.directory / f"{evidence_id}.json"
