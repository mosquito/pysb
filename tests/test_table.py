import json

import pytest
from io import StringIO
from src.snak import Table, TableHeader, Colors


def test_table_initialization(unicode_support_toggle):
    header = TableHeader(value="Column1", format="<10", color=Colors.GREEN)
    table = Table(header)
    assert len(table.header) == 1
    assert table.header[0].value == "Column1"


def test_table_add_row():
    header1 = TableHeader(value="Column1", format="<10", color=Colors.GREEN)
    header2 = TableHeader(value="Column2", format="<10", color=Colors.RED)
    table = Table(header1, header2)
    table.add("Value1", "Value2")
    assert len(table.rows) == 1
    assert table.rows[0] == ("Value1", "Value2")


def test_table_add_row_invalid_length():
    header1 = TableHeader(value="Column1", format="<10", color=Colors.GREEN)
    header2 = TableHeader(value="Column2", format="<10", color=Colors.RED)
    table = Table(header1, header2)
    with pytest.raises(ValueError, match="Row length .* does not match header length .*"):
        table.add("Value1")  # Adding a row with fewer columns than the header


def test_table_write():
    header1 = TableHeader(value="Column1", format="<10", color=Colors.GREEN)
    header2 = TableHeader(value="Column2", format="<10", color=Colors.RED)
    table = Table(header1, header2)
    table.add("Value1", "Value2")
    table.add("Value3", "Value4")

    output = StringIO()
    table.write(output)
    result = output.getvalue()

    assert "Column1" in result
    assert "Column2" in result
    assert "Value1" in result
    assert "Value2" in result
    assert "Value3" in result
    assert "Value4" in result


def test_table_str():
    header1 = TableHeader(value="Column1", format="<10", color=Colors.GREEN)
    header2 = TableHeader(value="Column2", format="<10", color=Colors.RED)
    table = Table(header1, header2)
    table.add("Value1", "Value2")

    result = str(table)
    assert "Column1" in result
    assert "Column2" in result
    assert "Value1" in result
    assert "Value2" in result


def test_format_value():
    table = Table(TableHeader(value="Column1", format="<10", color=Colors.GREEN))
    table.add("foo")
    table.add(3.14)
    table.add(42)
    table.add(None)
    table.add(True)
    table.add(False)

    output = StringIO()
    table.write(output)
    result = output.getvalue()
    assert "foo" in result
    assert "3.14" in result
    assert "42" in result
    assert "None" in result
    assert "yes" in result
    assert "no" in result


def test_table_json_format():
    header1 = TableHeader(value="Column1", format="<10", color=Colors.GREEN)
    header2 = TableHeader(value="Column2", format="<10", color=Colors.RED)
    table = Table(header1, header2, format="json")
    table.add("Value1", "Value2")
    table.add("Value3", "Value4")

    output = StringIO()
    table.write(output)
    result = json.loads(output.getvalue())
    assert len(result) == 2
    assert result == [
        {"column1": "Value1", "column2": "Value2"},
        {"column1": "Value3", "column2": "Value4"}
    ]


def test_table_json_format_empty():
    header1 = TableHeader(value="Column1", format="<10", color=Colors.GREEN)
    header2 = TableHeader(value="Column2", format="<10", color=Colors.RED)
    table = Table(header1, header2, format="json")

    output = StringIO()
    table.write(output)
    assert output.getvalue() == "[]"


def test_table_csv_format():
    header1 = TableHeader(value="Column1", format="<10", color=Colors.GREEN)
    header2 = TableHeader(value="Column2", format="<10", color=Colors.RED)
    table = Table(header1, header2, format="csv")
    table.add("Value1", "Value2")
    table.add("Value3", "Value4")

    output = StringIO()
    table.write(output)
    result = output.getvalue()
    assert "Value1,Value2" in result
    assert "Value3,Value4" in result
