"""Build the point-in-time fact store and query it as of a date.

The store keeps one row per (filing, fact): the value a company reported for a tag, the period it
describes (``ddate``, ``qtrs``) and when the filing became public (``filed`` date and the EDGAR
``accepted`` timestamp, US Eastern time). Nothing is overwritten, so every earlier version of a
number stays available and ``as_of`` can answer "what did the market know at time t?".
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

# Consolidated, entity-level facts from the standard US-GAAP taxonomy: no dimensional breakdowns
# (``segments``), no co-registrant values (``coreg``), no company-specific extension tags.
FACT_SQL = """
SELECT
    TRY_CAST(s.cik AS INTEGER) AS cik,
    s.adsh,
    s.form,
    s.afs,
    TRY_CAST(s.sic AS INTEGER) AS sic,
    TRY_CAST(s.fy AS INTEGER) AS fy,
    s.fp,
    TRY_STRPTIME(s.period, '%Y%m%d')::DATE AS period,
    TRY_STRPTIME(s.filed, '%Y%m%d')::DATE AS filed,
    TRY_CAST(left(s.accepted, 19) AS TIMESTAMP) AS accepted,
    s.prevrpt = '1' AS prevrpt,
    n.tag,
    TRY_STRPTIME(n.ddate, '%Y%m%d')::DATE AS ddate,
    TRY_CAST(n.qtrs AS INTEGER) AS qtrs,
    n.uom,
    TRY_CAST(n.value AS DOUBLE) AS value,
    s.quarter
FROM read_parquet('{num}') AS n
JOIN read_parquet('{sub}') AS s USING (adsh)
WHERE n.segments IS NULL
  AND n.coreg IS NULL
  AND n.value IS NOT NULL
  AND n.version LIKE 'us-gaap/%'
"""

# Filings of US domestic issuers that carry periodic financial statements.
PERIODIC_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-KT/A", "10-QT", "10-QT/A")


def connect(memory_limit: str = "1500MB", threads: int = 2, temp_dir: str | None = None):
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET enable_progress_bar=false")
    if temp_dir:
        con.execute(f"SET temp_directory='{Path(temp_dir).as_posix()}'")
    return con


def build_facts(parquet_root: Path, out_root: Path, con, budget_s: float = float("inf")) -> list[str]:
    """Write ``out_root/facts/<quarter>.parquet`` for every quarter not yet built."""
    parquet_root, out_root = Path(parquet_root), Path(out_root)
    (out_root / "facts").mkdir(parents=True, exist_ok=True)
    done, start = [], time.time()
    for sub in sorted((parquet_root / "sub").glob("*.parquet")):
        q = sub.stem
        dest = out_root / "facts" / f"{q}.parquet"
        num = parquet_root / "num" / f"{q}.parquet"
        if dest.exists() or not num.exists():
            continue
        if time.time() - start > budget_s:
            break
        part = dest.with_suffix(".part")
        sql = FACT_SQL.format(num=num.as_posix(), sub=sub.as_posix())
        con.execute(f"COPY ({sql}) TO '{part.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        part.rename(dest)
        done.append(q)
    return done


def facts_view(con, out_root: Path, name: str = "facts") -> None:
    """Register all built quarters as one view."""
    glob = (Path(out_root) / "facts" / "*.parquet").as_posix()
    con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{glob}')")


def as_of(con, queries: str, facts: str = "facts") -> str:
    """SQL for the point-in-time value of each query row.

    ``queries`` names a table or view with columns (cik, tag, ddate, qtrs, uom, asof TIMESTAMP).
    Each row gets the value from the latest filing accepted at or before ``asof`` that reports
    that fact, plus the accession number and acceptance time of that filing. Rows with no such
    filing get NULLs.
    """
    return f"""
    SELECT q.*, f.value, f.adsh, f.accepted
    FROM {queries} AS q
    ASOF LEFT JOIN {facts} AS f
      ON q.cik = f.cik AND q.tag = f.tag AND q.ddate = f.ddate AND q.qtrs = f.qtrs
     AND q.uom = f.uom AND q.asof >= f.accepted
    """
