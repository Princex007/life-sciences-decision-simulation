"""Read a CSV or Excel file into named numeric series for the forecaster.

The file is never stored: this produces a preview, and the user picks one column before
anything reaches histories/. Only plain numbers are accepted, because a straight-line fit
over a cell that means something else (a date, a percentage, a text note) would quietly
project the wrong quantity.
"""
from __future__ import annotations

import base64
import csv
import io
import math
import re
import zipfile
from datetime import date, datetime, time

MAX_FILE_BYTES = 5_000_000
MAX_POINTS = 500
MIN_POINTS = 2
CSV_SUFFIXES = (".csv", ".txt")
EXCEL_SUFFIXES = (".xlsx", ".xlsm")

_CURRENCY = re.compile(r"^[$€£¥₹]|[$€£¥₹]+$")


class TableImportError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _column_label(index: int) -> str:
    label = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _number(value) -> float | None:
    """Parse one cell into a finite float, or None when it is not a plain number.

    Percent-formatted text is rejected rather than guessed: 12% could be 12 or 0.12 and
    neither reading can be confirmed from the cell alone.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (datetime, date, time)):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text or "%" in text:
        return None
    text = _CURRENCY.sub("", text.replace(",", "")).strip()
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _csv_rows(text: str) -> list[list[str]]:
    sample = text[:65536]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {item: sample.count(item) for item in (",", ";", "\t")}
        best = max(counts, key=counts.get)
        if counts[best]:
            delimiter = best
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader]


def _excel_rows(raw: bytes, sheet: str) -> tuple[list[list], list[str], str]:
    try:
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException
    except ImportError as error:  # pragma: no cover - environment guard
        raise TableImportError(["Excel import needs the openpyxl package installed "
                                "(pip install openpyxl). Import the file as CSV instead."]) from error
    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except (InvalidFileException, OSError, ValueError, zipfile.BadZipFile) as error:
        raise TableImportError([f"That file could not be opened as an .xlsx workbook ({error}). "
                                "If it is an older .xls file, save it as CSV first."]) from error
    try:
        names = list(workbook.sheetnames)
        if sheet and sheet not in names:
            raise TableImportError([f"Sheet '{sheet}' is not in this workbook. Sheets: {', '.join(names)}."])
        worksheet = workbook[sheet] if sheet else workbook.worksheets[0]
        rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
        used = worksheet.title
    finally:
        workbook.close()
    return rows, names, used


def _read_table(file_name: str, raw: bytes, sheet: str) -> tuple[list, list[str], str]:
    suffix = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if not raw:
        raise TableImportError(["The file is empty."])
    if len(raw) > MAX_FILE_BYTES:
        raise TableImportError([f"The file is larger than {MAX_FILE_BYTES // 1000000} MB. "
                                "Keep only the series you want to forecast."])
    if suffix in CSV_SUFFIXES:
        return _csv_rows(_decode(raw)), [], ""
    if suffix in EXCEL_SUFFIXES:
        return _excel_rows(raw, sheet)
    raise TableImportError([f"Only {', '.join(CSV_SUFFIXES + EXCEL_SUFFIXES)} files can be imported "
                            f"(got '{suffix or file_name}'). Save the sheet as CSV or .xlsx."])


def _series_from_rows(rows: list) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    width = max((len(row) for row in rows), default=0)
    columns: list[dict] = []
    for index in range(width):
        cells = [(row_number, row[index] if index < len(row) else None)
                 for row_number, row in enumerate(rows, start=1)]
        numbers = [(row_number, value) for row_number, cell in cells
                   if (value := _number(cell)) is not None]
        if len(numbers) < MIN_POINTS:
            continue
        # Text cells never enter `numbers`, so a header row is excluded from the values by
        # itself. The cell directly above the first number names the column.
        above = next((cell for row_number, cell in cells if row_number == numbers[0][0] - 1), None)
        label = "" if above is None or _number(above) is not None else str(above).strip()
        taken = numbers
        used_rows = {row_number for row_number, _ in taken}
        # Anything between the first and last number that is not a number is a period the fit
        # will not know about, so it is reported rather than quietly compressed out of the series.
        inside = sum(1 for row_number, _ in cells
                     if taken[0][0] <= row_number <= taken[-1][0] and row_number not in used_rows)
        values = [value for _, value in taken]
        if len(values) > MAX_POINTS:
            warnings.append(f"Column {_column_label(index)} had {len(values)} values; only the first "
                            f"{MAX_POINTS} were read, matching the stored-series limit.")
            values, taken = values[:MAX_POINTS], taken[:MAX_POINTS]
        columns.append({
            "column": _column_label(index),
            "name": label or f"Column {_column_label(index)}",
            "values": values,
            "points": len(values),
            "first_row": taken[0][0],
            "last_row": taken[-1][0],
            "skipped_in_range": inside,
        })
    return columns, warnings


def _label_column(rows: list) -> dict | None:
    """The first column as text, when it holds no numbers at all.

    A register laid out one row per entry — a name, then its numbers — would otherwise lose the
    names with the column, because only numeric columns are read as series. The header is returned
    with the cells so the caller can tell a name column from a period column instead of guessing.
    """
    if len(rows) < 2 or not rows[0]:
        return None
    cells = [row[0] if row else None for row in rows]
    if any(_number(cell) is not None for cell in cells):
        return None
    header = "" if cells[0] is None else str(cells[0]).strip()
    values = ["" if cell is None else str(cell).strip() for cell in cells[1:]]
    return None if not any(values) else {"name": header, "values": values}


def _text_columns(rows: list) -> list[dict]:
    """Every column that holds text rather than numbers, with its header and cells.

    A unit column ("USD per course") is the kind of metadata a register carries, and it can never
    appear among the numeric series, so the forecaster would have no way to name a variable's unit.
    Values are aligned to the rows, blanks included, so a cell still lines up with its entry.
    """
    columns = []
    for index in range(max((len(row) for row in rows), default=0)):
        cells = [row[index] if index < len(row) else None for row in rows]
        if any(_number(cell) is not None for cell in cells):
            continue
        values = ["" if cell is None else str(cell).strip() for cell in cells[1:]]
        if not any(values):
            continue
        header = "" if not cells or cells[0] is None else str(cells[0]).strip()
        columns.append({"column": _column_label(index),
                        "name": header or f"Column {_column_label(index)}", "values": values})
    return columns


def import_series(file_name: str, raw: bytes, sheet: str = "") -> dict:
    """Preview every numeric column in an uploaded table, oldest row first."""
    rows, sheets, used_sheet = _read_table(file_name, raw, sheet)
    rows = [row for row in rows if any(cell not in (None, "") for cell in row)]
    columns, warnings = _series_from_rows(rows)
    if not columns:
        raise TableImportError([
            "No column with at least two plain numbers was found. The first row is treated as a "
            "header, dates and percent-formatted text are not read as numbers, and a text column "
            "cannot be forecast."])
    return {"file_name": file_name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            "sheet": used_sheet, "sheets": sheets,
            "rows": len(rows), "columns": columns, "warnings": warnings,
            "text_columns": _text_columns(rows), "label_column": _label_column(rows)}


def decode_upload(encoded: str) -> bytes:
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise TableImportError(["The file did not reach the server intact. Try selecting it again."]) from error
