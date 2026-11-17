"""How often, and by how much, the first published value of a number is later changed.

A fact is identified by (cik, tag, ddate, qtrs, uom). Its first report is the earliest filing that
contains it; only facts whose first report is an original 10-K or 10-Q describing its own fiscal
period (``ddate`` equal to the filing's period) are kept, so the first value is the number the
company published for the period it had just closed. Every later filing that repeats the fact
(next year's comparative columns, amendments) is a later vintage.
"""

from __future__ import annotations

import time
from pathlib import Path

KEY_TAGS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "NetIncomeLoss",
    "OperatingIncomeLoss",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "NetCashProvidedByUsedInOperatingActivities",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
)

VINTAGES_SQL = """
CREATE OR REPLACE TEMP TABLE vintages AS
SELECT cik, tag, ddate, qtrs, uom, adsh,
       any_value(form) AS form, any_value(accepted) AS accepted, any_value(period) AS period,
       min(value) AS value, max(value) <> min(value) AS conflict
FROM {facts}
WHERE tag IN ({tags}) AND form IN ('10-K', '10-K/A', '10-Q', '10-Q/A') AND accepted IS NOT NULL
GROUP BY ALL
"""

FACT_HISTORY_SQL = """
CREATE OR REPLACE TEMP TABLE fact_history AS
WITH o AS (
    SELECT *,
        row_number() OVER w AS k,
        count(*) OVER (PARTITION BY cik, tag, ddate, qtrs, uom) AS n_vintages,
        first_value(value) OVER w AS first_value,
        first_value(form) OVER w AS first_form,
        first_value(period) OVER w AS first_period,
        first_value(accepted) OVER w AS first_accepted,
        bool_or(conflict) OVER (PARTITION BY cik, tag, ddate, qtrs, uom) AS any_conflict
    FROM vintages
    WINDOW w AS (PARTITION BY cik, tag, ddate, qtrs, uom ORDER BY accepted, adsh
                 ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
), keep AS (
    SELECT * FROM o
    WHERE first_form IN ('10-K', '10-Q') AND first_period = ddate AND NOT any_conflict
), changed AS (
    SELECT cik, tag, ddate, qtrs, uom,
        arg_min(form, accepted) AS change_form,
        min(accepted) AS change_accepted,
        arg_min(value, accepted) AS change_value
    FROM keep
    WHERE value <> first_value
    GROUP BY ALL
), final AS (
    SELECT cik, tag, ddate, qtrs, uom, any_value(first_value) AS first_value,
        arg_max(value, accepted) AS final_value, any_value(n_vintages) AS n_vintages,
        any_value(first_accepted) AS first_accepted, any_value(first_form) AS first_form
    FROM keep
    GROUP BY ALL
)
SELECT f.*, c.change_form, c.change_accepted, c.change_value,
    date_diff('day', f.first_accepted, c.change_accepted) AS days_to_change
FROM final f LEFT JOIN changed c USING (cik, tag, ddate, qtrs, uom)
"""

CLASSIFY = """
CASE
    WHEN change_value IS NULL THEN 'unchanged'
    WHEN first_value <> 0 AND abs(change_value / first_value) BETWEEN 990 AND 1010 THEN 'scale x1000'
    WHEN change_value <> 0 AND abs(first_value / change_value) BETWEEN 990 AND 1010 THEN 'scale x1000'
    WHEN sign(change_value) <> sign(first_value) AND first_value <> 0 AND change_value <> 0
        THEN 'sign change'
    WHEN abs(change_value - first_value) / greatest(abs(first_value), 1e-9) < 0.01 THEN '<1%'
    WHEN abs(change_value - first_value) / greatest(abs(first_value), 1e-9) < 0.10 THEN '1-10%'
    ELSE '>=10%'
END
"""


def build(con, facts: str = "facts", tags=KEY_TAGS, out_dir=None, budget_s: float = float("inf")) -> bool:
    """Create ``fact_history``. With ``out_dir``, work one tag at a time and keep the result in
    ``out_dir/<tag>.parquet`` so a long run can be split; returns True when every tag is done."""
    if out_dir is None:
        tag_list = ", ".join(f"'{t}'" for t in tags)
        con.execute(VINTAGES_SQL.format(facts=facts, tags=tag_list))
        con.execute(FACT_HISTORY_SQL)
        return True
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.time()
    for tag in tags:
        dest = out_dir / f"{tag}.parquet"
        if dest.exists():
            continue
        if time.time() - start > budget_s:
            return False
        con.execute(VINTAGES_SQL.format(facts=facts, tags=f"'{tag}'"))
        con.execute(FACT_HISTORY_SQL)
        part = dest.with_suffix(".part")
        con.execute(f"COPY fact_history TO '{part.as_posix()}' (FORMAT parquet)")
        part.rename(dest)
    con.execute("DROP TABLE IF EXISTS fact_history")
    con.execute(
        "CREATE OR REPLACE VIEW fact_history AS SELECT * FROM "
        f"read_parquet('{(out_dir / '*.parquet').as_posix()}')"
    )
    return True


def summary(con, by: str = "tag"):
    """Share of facts ever changed after first publication, and the size of the first change.

    Only facts with at least one later vintage can be revised, so shares are reported both over
    all facts and over facts that were re-reported.
    """
    return con.execute(
        f"""
        SELECT {by},
            count(*) AS n_facts,
            count(*) FILTER (WHERE n_vintages > 1) AS n_rereported,
            avg((change_value IS NOT NULL)::INT) AS share_changed,
            avg((change_value IS NOT NULL)::INT) FILTER (WHERE n_vintages > 1)
                AS share_changed_if_rereported,
            avg((change_form LIKE '%/A')::INT) FILTER (WHERE change_value IS NOT NULL)
                AS share_changes_via_amendment,
            median(days_to_change) AS median_days_to_change
        FROM fact_history
        GROUP BY ALL
        ORDER BY ALL
        """
    ).df()


def size_classes(con, by: str = "tag"):
    return con.execute(
        f"""
        SELECT {by}, {CLASSIFY} AS size_class, count(*) AS n
        FROM fact_history
        GROUP BY ALL
        ORDER BY ALL
        """
    ).df()
