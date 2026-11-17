"""Convert the SEC Financial Statement Data Sets zips to Parquet (sub and num).

    python scripts/to_parquet.py <root> [seconds]

Reads <root>/raw/sec_fsds/<year>q<quarter>.zip (from scripts/download_sec_fsds.py) and writes
<root>/parquet/{sub,num}/<quarter>.parquet. The optional time budget stops after the quarter
that exceeds it, so a long conversion can be split across runs.

One Parquet file per quarter and table; quarters already converted are skipped.
All columns are kept as text (empty fields become NULL); typed views are built downstream.

The files are tab-delimited without quoting, and a few rows carry literal tabs inside a text
field (e.g. num.segments in 2022q4). Each line is therefore read whole and split on tabs; when a
row has more fields than the header, the surplus is joined back into the free-text column
(`segments` if the table has one, otherwise the last column). Every repaired row is counted in
results/parse_log.csv, together with the line count of the source file.
"""

import csv
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import duckdb

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
RAW, OUT, LOG = ROOT / "raw" / "sec_fsds", ROOT / "parquet", ROOT / "results" / "parse_log.csv"
SEP = "\x01"  # a byte that never occurs in the files: makes read_csv return whole lines


def select_sql(path: str, cols: list[str], q: str) -> str:
    n = len(cols)
    free = cols.index("segments") if "segments" in cols else n - 1  # 0-based column taking the surplus
    exprs = []
    for i, c in enumerate(cols):
        if i < free:
            e = f"f[{i + 1}]"
        elif i == free:
            e = f"CASE WHEN len(f) > {n} THEN array_to_string(f[{i + 1}:len(f) - {n - 1 - i}], chr(9)) ELSE f[{i + 1}] END"
        else:
            e = f"CASE WHEN len(f) > {n} THEN f[len(f) - {n - 1 - i}] ELSE f[{i + 1}] END"
        exprs.append(f"nullif({e}, '') AS \"{c}\"")
    return (
        f"WITH l AS (SELECT string_split(rtrim(line, chr(13)), chr(9)) AS f FROM read_csv('{path}', "
        f"columns={{'line': 'VARCHAR'}}, delim='{SEP}', header=false, quote='', escape='', skip=1, "
        f"max_line_size=8000000, auto_detect=false)) "
        f"SELECT {', '.join(exprs)}, '{q}' AS quarter FROM l"
    )


def convert(zpath: Path, con, log: list) -> None:
    q = zpath.stem
    for table in ("sub", "num"):
        dest = OUT / table / f"{q}.parquet"
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(zpath) as z:
                z.extract(f"{table}.txt", tmp)
            src = f"{tmp}/{table}.txt"
            with open(src, encoding="utf-8", errors="replace") as fh:
                cols = fh.readline().rstrip("\r\n").split("\t")
            irregular = rows = 0
            with open(src, "rb") as fh:
                next(fh)
                for line in fh:
                    rows += 1
                    irregular += line.count(b"\t") != len(cols) - 1
            part = dest.with_suffix(".part")
            con.execute(f"COPY ({select_sql(src, cols, q)}) TO '{part}' (FORMAT parquet, COMPRESSION zstd)")
            written = con.execute(f"SELECT count(*) FROM read_parquet('{part}')").fetchone()[0]
            if written != rows:
                raise RuntimeError(f"{q} {table}: {rows} lines but {written} rows written")
            part.rename(dest)
            log.append(
                {
                    "quarter": q,
                    "table": table,
                    "rows": rows,
                    "irregular_rows": irregular,
                    "columns": len(cols),
                }
            )


def main() -> None:
    con = duckdb.connect()
    con.execute("SET memory_limit='1500MB'; SET threads=2; SET preserve_insertion_order=false")
    tmpdir = ROOT / "tmp_duckdb"
    con.execute(f"SET temp_directory='{tmpdir.as_posix()}'")
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else float("inf")  # seconds
    start, log = time.time(), []
    try:
        for zpath in sorted(RAW.glob("*.zip")):
            if zpath.stat().st_size == 0 or all(
                (OUT / t / f"{zpath.stem}.parquet").exists() for t in ("sub", "num")
            ):
                continue
            if time.time() - start > budget:
                break
            t = time.time()
            convert(zpath, con, log)
            print(zpath.stem, f"{time.time() - t:.1f}s", flush=True)
    finally:
        if log:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            new = not LOG.exists()
            with open(LOG, "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(log[0]))
                if new:
                    w.writeheader()
                w.writerows(log)


if __name__ == "__main__":
    main()
