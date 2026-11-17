import duckdb
import pandas as pd
import pytest


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("SET enable_progress_bar=false")
    yield c
    c.close()


def make_facts(con, rows):
    """rows: dicts with cik, adsh, form, period, accepted, tag, ddate, qtrs, uom, value."""
    df = pd.DataFrame(rows)
    for col in ("period", "ddate"):
        df[col] = pd.to_datetime(df[col]).dt.date
    df["accepted"] = pd.to_datetime(df["accepted"])
    con.register("facts_df", df)
    con.execute("CREATE OR REPLACE TABLE facts AS SELECT * FROM facts_df")
    filings = df.drop_duplicates("adsh")[["adsh", "cik", "form", "period", "accepted"]]
    con.register("filings_df", filings)
    con.execute("CREATE OR REPLACE TABLE filings AS SELECT * FROM filings_df")
