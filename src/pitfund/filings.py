"""Filing calendar: when each periodic report became public, and how that compares with the
SEC deadline for the filer's category.

Deadlines (Exchange Act Forms 10-K and 10-Q, General Instructions), counted in calendar days
after the end of the fiscal period:

=========================  ======  ======
filer status (``afs``)     10-K    10-Q
=========================  ======  ======
1-LAF large accelerated      60      40
2-ACC accelerated            75      40
3-SRA small rep. acc.        75      40
4-NON non-accelerated        90      45
5-SML smaller reporting      90      45
=========================  ======  ======

A deadline that falls on a Saturday or Sunday moves to the next Monday; federal holidays are
ignored, so a few filings counted as one day late were on time. Form 12b-25 (NT 10-K / NT 10-Q)
extends the deadline by 15 and 5 calendar days; the data sets do not say who filed one, so lateness
is reported both against the deadline and against the deadline plus the extension.
"""

from __future__ import annotations

from pathlib import Path

PERIODIC = ("10-K", "10-K/A", "10-Q", "10-Q/A")

FILINGS_SQL = """
SELECT
    adsh,
    TRY_CAST(cik AS INTEGER) AS cik,
    form,
    afs,
    TRY_CAST(sic AS INTEGER) AS sic,
    TRY_STRPTIME(period, '%Y%m%d')::DATE AS period,
    TRY_CAST(fy AS INTEGER) AS fy,
    fp,
    TRY_STRPTIME(filed, '%Y%m%d')::DATE AS filed,
    TRY_CAST(left(accepted, 19) AS TIMESTAMP) AS accepted,
    quarter
FROM read_parquet('{sub}')
WHERE form IN ('10-K', '10-K/A', '10-Q', '10-Q/A')
QUALIFY row_number() OVER (PARTITION BY adsh ORDER BY quarter) = 1
"""

DEADLINE_SQL = """
CREATE OR REPLACE TEMP TABLE filing_lag AS
WITH d AS (
    SELECT *,
        CASE
            WHEN form = '10-K' AND afs = '1-LAF' THEN 60
            WHEN form = '10-K' AND afs IN ('2-ACC', '3-SRA') THEN 75
            WHEN form = '10-K' AND afs IN ('4-NON', '5-SML') THEN 90
            WHEN form = '10-Q' AND afs IN ('1-LAF', '2-ACC', '3-SRA') THEN 40
            WHEN form = '10-Q' AND afs IN ('4-NON', '5-SML') THEN 45
        END AS deadline_days,
        CASE WHEN form = '10-K' THEN 15 ELSE 5 END AS extension_days
    FROM filings
    WHERE form IN ('10-K', '10-Q') AND period IS NOT NULL AND filed IS NOT NULL
), r AS (
    SELECT *, period + deadline_days AS raw_deadline FROM d
)
SELECT *,
    (filed - period) AS lag_days,
    CASE dayofweek(raw_deadline)
        WHEN 6 THEN raw_deadline + 2
        WHEN 0 THEN raw_deadline + 1
        ELSE raw_deadline
    END AS deadline,
    year(period) AS period_year
FROM r
WHERE (filed - period) BETWEEN 0 AND 730
"""


def load_filings(con, parquet_root: Path) -> None:
    sub = (Path(parquet_root) / "sub" / "*.parquet").as_posix()
    con.execute(f"CREATE OR REPLACE TEMP TABLE filings AS {FILINGS_SQL.format(sub=sub)}")
    con.execute(DEADLINE_SQL)


def lag_summary(con, by: str = "period_year, form, afs"):
    """Distribution of the filing lag and deadline misses, grouped by ``by``."""
    return con.execute(
        f"""
        SELECT {by},
            count(*) AS n,
            quantile_cont(lag_days, 0.1) AS lag_p10,
            median(lag_days) AS lag_median,
            quantile_cont(lag_days, 0.9) AS lag_p90,
            avg((filed > deadline)::INT) FILTER (WHERE deadline IS NOT NULL) AS share_late,
            avg((filed > deadline + extension_days)::INT) FILTER (WHERE deadline IS NOT NULL)
                AS share_late_after_extension
        FROM filing_lag
        GROUP BY ALL
        ORDER BY ALL
        """
    ).df()


def fixed_lag_exposure(con, lags_days=(30, 45, 60, 75, 90, 120, 180)):
    """Share of original filings still unpublished ``L`` days after the period end.

    A backtest that treats a fiscal period as known ``L`` days after it ends uses these numbers
    before anyone could see them.
    """
    cols = ", ".join(f"avg((lag_days > {L})::INT) AS after_{L}d" for L in lags_days)
    return con.execute(
        f"SELECT period_year, form, count(*) AS n, {cols} FROM filing_lag GROUP BY ALL ORDER BY ALL"
    ).df()
