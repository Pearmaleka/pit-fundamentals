import datetime as dt

import pandas as pd

from pitfund import filings


def _load(con, rows):
    df = pd.DataFrame(rows, columns=["adsh", "form", "afs", "period", "filed"])
    df["period"] = pd.to_datetime(df["period"]).dt.date
    df["filed"] = pd.to_datetime(df["filed"]).dt.date
    con.register("f", df)
    con.execute("CREATE OR REPLACE TABLE filings AS SELECT * FROM f")
    con.execute(filings.DEADLINE_SQL)
    return con.execute("SELECT adsh, lag_days, deadline, filed > deadline AS late FROM filing_lag").df()


def test_deadlines_by_status(con):
    out = _load(
        con,
        [
            ("a", "10-K", "1-LAF", "2023-12-31", "2024-02-29"),  # day 60: on time
            ("b", "10-K", "1-LAF", "2023-12-31", "2024-03-01"),  # day 61: late
            ("c", "10-K", "4-NON", "2023-12-31", "2024-03-29"),  # day 89: on time
            ("d", "10-Q", "2-ACC", "2024-03-31", "2024-05-13"),  # day 43 > 40: late
        ],
    ).set_index("adsh")
    assert out.loc["a", "lag_days"] == 60 and not out.loc["a", "late"]
    assert out.loc["b", "late"]
    assert not out.loc["c", "late"]
    assert out.loc["d", "late"]


def test_weekend_deadline_moves_to_monday(con):
    period = dt.date(2024, 7, 1)  # + 40 days = Saturday 2024-08-10
    assert (period + dt.timedelta(40)).weekday() == 5
    out = _load(con, [("a", "10-Q", "1-LAF", str(period), "2024-08-12")])
    assert out.loc[0, "deadline"].date() == dt.date(2024, 8, 12)
    assert not out.loc[0, "late"]


def test_amendments_and_unknown_status_excluded_from_lateness(con):
    out = _load(
        con,
        [
            ("a", "10-K/A", "1-LAF", "2023-12-31", "2024-06-01"),
            ("b", "10-K", None, "2023-12-31", "2024-06-01"),
        ],
    )
    assert list(out["adsh"]) == ["b"]
    assert pd.isna(out.loc[0, "deadline"])
