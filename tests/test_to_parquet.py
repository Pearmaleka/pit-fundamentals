import importlib.util
from pathlib import Path

import duckdb

spec = importlib.util.spec_from_file_location(
    "to_parquet", Path(__file__).resolve().parents[1] / "scripts" / "to_parquet.py"
)
to_parquet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(to_parquet)

HEADER = ["adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value", "footnote"]


def test_tab_inside_segments_is_rejoined(tmp_path):
    lines = [
        "\t".join(HEADER),
        "\t".join(["a1", "Assets", "us-gaap/2022", "20221231", "0", "USD", "", "", "5", ""]),
        # a segments value holding two literal tabs: 12 fields instead of 10
        "\t".join(["a2", "Loan", "us-gaap/2022", "20221231", "0", "USD", '"Id=1', "x", 'y;"', "", "7", "fn"]),
    ]
    src = tmp_path / "num.txt"
    src.write_text("\n".join(lines) + "\n")
    rows = duckdb.sql(to_parquet.select_sql(src.as_posix(), HEADER, "2022q4")).fetchall()
    assert rows[0][:2] == ("a1", "Assets") and rows[0][6] is None and rows[0][8] == "5"
    assert rows[1][6] == '"Id=1\tx\ty;"'
    assert rows[1][7:] == (None, "7", "fn", "2022q4")


def test_windows_line_endings(tmp_path):
    src = tmp_path / "sub.txt"
    src.write_bytes(b"adsh\tcik\r\nx\t1\r\n")
    assert duckdb.sql(to_parquet.select_sql(src.as_posix(), ["adsh", "cik"], "q")).fetchall() == [
        ("x", "1", "q")
    ]
