"""CSV and Excel table import: what becomes a forecastable series, and what is refused."""
import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.services.table_import import TableImportError, import_series
from app.main import app


def workbook(sheets: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_csv_header_names_the_column_and_values_stay_in_order():
    result = import_series("sales.csv",
                           b"Quarter,Units\nQ1,120\nQ2,132\nQ3,141\nQ4,158\n")
    assert result["rows"] == 5
    column, = result["columns"]
    assert (column["name"], column["column"], column["points"]) == ("Units", "B", 4)
    assert column["values"] == [120.0, 132.0, 141.0, 158.0]
    assert (column["first_row"], column["last_row"], column["skipped_in_range"]) == (2, 5, 0)
    assert result["warnings"] == []


def test_each_numeric_column_is_offered_separately():
    result = import_series("two.csv", b"label,a,b\nx,1,10\ny,2,20\n")
    assert [column["name"] for column in result["columns"]] == ["a", "b"]


def test_a_register_keeps_its_text_names_so_rows_can_be_read_as_entries():
    # The driver card's variable register is laid out one entry per row, so the name column is the
    # only thing that makes the numbers mean anything; dropping it would fill the rows blind.
    result = import_series("variables.csv",
                           b"Variable,Value at t0,Growth rate per period\nprice,100,5\nvolume,40,8\n")
    assert result["label_column"] == {"name": "Variable", "values": ["price", "volume"]}
    assert [column["name"] for column in result["columns"]] == ["Value at t0", "Growth rate per period"]
    assert [column["values"] for column in result["columns"]] == [[100.0, 40.0], [5.0, 8.0]]


def test_a_period_column_is_returned_as_labels_with_its_header_for_the_caller_to_judge():
    result = import_series("sales.csv", b"Quarter,Units\nQ1,120\nQ2,132\nQ3,141\n")
    assert result["label_column"] == {"name": "Quarter", "values": ["Q1", "Q2", "Q3"]}


def test_text_columns_are_reported_so_a_unit_column_survives_the_import():
    # A unit is never a number, so it can only reach the driver card through the text columns;
    # values stay row-aligned, blank included, so a unit lands on its own variable.
    result = import_series("variables.csv",
                           b"Variable,Value at t0,Unit,Growth rate per period\n"
                           b"price,100,USD per course,5\nvolume,40,,8\nshare,0.2,fraction (0-1),2\n")
    assert [column["values"] for column in result["columns"]] == [[100.0, 40.0, 0.2], [5.0, 8.0, 2.0]]
    units = next(column for column in result["text_columns"] if column["name"] == "Unit")
    assert (units["column"], units["values"]) == ("C", ["USD per course", "", "fraction (0-1)"])
    assert [column["name"] for column in result["text_columns"]] == ["Variable", "Unit"]


def test_a_numeric_first_column_is_not_reported_as_labels():
    result = import_series("wide.csv", b"period,units\n1,120\n2,132\n")
    assert result["label_column"] is None


def test_a_title_row_above_the_header_does_not_eat_the_first_value():
    # Row 1 is a report title, row 2 the header: the first data row must still be data.
    result = import_series("titled.csv", b"Sales by quarter,,\nquarter,units\n2024 Q1,120\n2024 Q2,132\n")
    column, = result["columns"]
    assert column["values"] == [120.0, 132.0]
    assert column["first_row"] == 3


def test_grouped_thousands_and_currency_are_read_but_percent_is_refused():
    result = import_series("money.csv", b"quarter,revenue,share\nQ1,\"$1,234\",6%\nQ2,\"1,450\",7%\n")
    assert [column["name"] for column in result["columns"]] == ["revenue"]
    assert result["columns"][0]["values"] == [1234.0, 1450.0]


def test_a_blank_inside_the_span_is_reported_on_its_own_column():
    result = import_series("gap.csv", b"quarter,units\nQ1,120\nQ2,\nQ3,158\n")
    column, = result["columns"]
    assert column["values"] == [120.0, 158.0]
    # The count travels with the column so the UI can name the period gap it just read past.
    assert column["skipped_in_range"] == 1


def test_excel_dates_label_the_series_instead_of_becoming_serial_numbers():
    from datetime import datetime

    data = workbook({"History": [["month", "units"],
                                 [datetime(2024, 1, 1), 120],
                                 [datetime(2024, 2, 1), 132],
                                 [datetime(2024, 3, 1), 141]]})
    result = import_series("hist.xlsx", data)
    assert result["sheet"] == "History"
    column, = result["columns"]
    assert column["name"] == "units"
    assert column["values"] == [120.0, 132.0, 141.0]


def test_named_sheet_is_used_and_an_unknown_one_is_refused():
    data = workbook({"Notes": [["only text"], ["still text"]],
                     "Series": [["units"], [10], [20], [30]]})
    assert import_series("multi.xlsx", data, sheet="Series")["columns"][0]["values"] == [10.0, 20.0, 30.0]
    with pytest.raises(TableImportError, match="Sheet 'Missing' is not in this workbook"):
        import_series("multi.xlsx", data, sheet="Missing")


def test_files_that_cannot_yield_a_series_are_refused_with_a_reason():
    cases = {
        "unsupported .xls is not parsed": lambda: import_series("old.xls", b"\xd0\xcf\x11\xe0junk"),
        "empty file": lambda: import_series("empty.csv", b""),
        "text only": lambda: import_series("notes.csv", b"a,b\nhello,world\nbye,planet\n"),
        "one value only": lambda: import_series("one.csv", b"label,value\nfirst,7\nsecond,none\n"),
        "corrupt workbook": lambda: import_series("bad.xlsx", b"not a zip file"),
    }
    for reason, call in cases.items():
        with pytest.raises(TableImportError) as error:
            call()
        assert error.value.errors, reason


def test_more_than_the_stored_limit_keeps_the_earliest_periods():
    rows = "quarter,units\n" + "\n".join(f"Q{i},{i}" for i in range(1, 503))
    result = import_series("long.csv", rows.encode())
    column, = result["columns"]
    assert column["points"] == 500
    assert column["values"][-1] == 500.0
    assert "stored-series limit" in result["warnings"][0]


def test_import_endpoint_previews_an_uploaded_workbook_without_storing_anything():
    with TestClient(app) as client:
        response = client.post("/forecast/import-table", json={
            "file_name": r"C:\Users\ana\Documents\Q4 units.xlsx",
            "sheet": "",
            "data": base64.b64encode(workbook(
                {"Q4": [["units"], [120], [132], [141]]})).decode()})
    assert response.status_code == 200, response.text
    body = response.json()
    # The display name is the file itself, never a path the caller could push into storage.
    assert body["file_name"] == "Q4 units.xlsx"
    assert body["columns"][0]["values"] == [120.0, 132.0, 141.0]


def test_import_endpoint_reports_a_bad_file_as_a_validation_error():
    with TestClient(app) as client:
        response = client.post("/forecast/import-table",
                               json={"file_name": "notes.txt", "data": base64.b64encode(b"a\nb\nc").decode()})
    assert response.status_code == 422
    assert "at least two plain numbers" in response.json()["detail"]["errors"][0]
