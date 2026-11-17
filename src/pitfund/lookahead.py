"""What a backtest sees under common shortcuts, compared with what was actually known.

The signal is return on assets, ROA = net income (fiscal year, ``qtrs`` = 4) / total assets at
fiscal year end, from annual reports. At every month end ``d`` four versions are built for each
company:

* ``pit``: the latest fiscal year whose 10-K had been accepted by EDGAR before the end of ``d``,
  with the values as they stood at ``d`` (later restatements ignored).
* ``naive_<L>m`` for L = 0, 3, 6: the latest fiscal year ending at least L months before ``d``,
  with the values from the most recent filing in the data (the "final" vintage), which is what a
  database snapshot downloaded today contains. L = 0 stamps a number with its period end; L = 3
  and L = 6 are the usual reporting-lag rules of thumb.

All versions ignore fiscal years ending more than 18 months before ``d``.
"""

from __future__ import annotations

ANNUAL_SQL = """
CREATE OR REPLACE TEMP TABLE fiscal_years AS
SELECT DISTINCT cik, period AS p FROM filings WHERE form = '10-K' AND period IS NOT NULL;

CREATE OR REPLACE TEMP TABLE annual_vintages AS
SELECT f.cik, y.p, f.tag, f.adsh, any_value(f.accepted) AS accepted, min(f.value) AS value
FROM {facts} AS f
JOIN fiscal_years AS y ON f.cik = y.cik AND f.ddate = y.p
WHERE f.uom = 'USD'
  AND f.form IN ('10-K', '10-K/A', '10-Q', '10-Q/A')
  AND f.accepted IS NOT NULL
  AND ((f.tag = 'NetIncomeLoss' AND f.qtrs = 4) OR (f.tag = 'Assets' AND f.qtrs = 0))
GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE annual_periods AS
WITH t AS (
    SELECT cik, p, tag, min(accepted) AS first_accepted, arg_max(value, accepted) AS final_value
    FROM annual_vintages GROUP BY ALL
)
SELECT cik, p,
    max(first_accepted) AS avail,
    max(final_value) FILTER (WHERE tag = 'NetIncomeLoss') AS ni_final,
    max(final_value) FILTER (WHERE tag = 'Assets') AS at_final
FROM t
GROUP BY ALL
HAVING count(*) = 2;
"""

PANEL_SQL = """
CREATE OR REPLACE TEMP TABLE month_ends AS
SELECT CAST(last_day(m) AS DATE) AS d, CAST(last_day(m) AS DATE) + INTERVAL 1 DAY AS cut
FROM range(DATE '{start}', DATE '{end}', INTERVAL 1 MONTH) AS r(m);

CREATE OR REPLACE TEMP TABLE candidates AS
SELECT m.d, m.cut, a.*
FROM month_ends AS m
JOIN annual_periods AS a ON a.p <= m.d AND a.p > m.d - INTERVAL 18 MONTH;

CREATE OR REPLACE TEMP TABLE pit_choice AS
SELECT d, any_value(cut) AS cut, cik, max(p) AS p
FROM candidates WHERE avail < cut GROUP BY d, cik;

CREATE OR REPLACE TEMP TABLE panel AS
WITH pit_vals AS (
    SELECT c.d, c.cik, c.p,
        arg_max(v.value, v.accepted) FILTER (WHERE v.tag = 'NetIncomeLoss') AS ni,
        arg_max(v.value, v.accepted) FILTER (WHERE v.tag = 'Assets') AS assets
    FROM pit_choice AS c
    JOIN annual_vintages AS v ON v.cik = c.cik AND v.p = c.p AND v.accepted < c.cut
    GROUP BY c.d, c.cik, c.p
), naive AS (
    SELECT L, c.d, c.cik, max(c.p) AS p
    FROM candidates AS c, (SELECT unnest([0, 3, 6]) AS L)
    WHERE c.p <= c.d - to_months(L)
    GROUP BY ALL
)
SELECT 'pit' AS method, d, cik, p, ni / assets AS roa, TRUE AS public
FROM pit_vals WHERE assets > 0
UNION ALL
SELECT 'naive_' || n.L || 'm', n.d, n.cik, n.p, a.ni_final / a.at_final, a.avail < c.cut
FROM naive AS n
JOIN annual_periods AS a ON a.cik = n.cik AND a.p = n.p
JOIN month_ends AS c ON c.d = n.d
WHERE a.at_final > 0;
"""

COMPARE_SQL = """
WITH q AS (
    SELECT *,
        ntile(5) OVER (PARTITION BY method, d ORDER BY roa) AS quintile,
        percent_rank() OVER (PARTITION BY method, d ORDER BY roa) AS prank
    FROM panel
), m AS (SELECT * FROM q WHERE method <> 'pit'),
   p AS (SELECT * FROM q WHERE method = 'pit'),
   pc AS (SELECT d, count(*) AS n_pit FROM p GROUP BY d)
SELECT m.method, m.d,
    count(*) AS n_naive,
    coalesce(any_value(pc.n_pit), 0) AS n_pit,
    avg((NOT m.public)::INT) AS share_not_public,
    count(p.cik) AS n_both,
    avg((m.p <> p.p)::INT) FILTER (WHERE p.cik IS NOT NULL) AS share_other_year,
    avg((m.p = p.p AND abs(m.roa - p.roa) > 1e-9)::INT) FILTER (WHERE p.cik IS NOT NULL)
        AS share_same_year_value_differs,
    avg((m.quintile <> p.quintile)::INT) FILTER (WHERE p.cik IS NOT NULL) AS share_quintile_differs,
    avg((p.cik IS NULL OR p.quintile <> m.quintile)::INT) FILTER (WHERE m.quintile IN (1, 5))
        AS share_extreme_not_confirmed,
    corr(m.prank, p.prank) AS rank_corr
FROM m LEFT JOIN p ON p.d = m.d AND p.cik = m.cik
LEFT JOIN pc ON pc.d = m.d
GROUP BY m.method, m.d
ORDER BY m.method, m.d
"""


def build(con, facts: str = "facts", start: str = "2010-01-01", end: str = "2026-10-01") -> None:
    con.execute(ANNUAL_SQL.format(facts=facts))
    con.execute(PANEL_SQL.format(start=start, end=end))


def compare(con):
    """One row per (naive method, month end) with coverage and disagreement statistics."""
    return con.execute(COMPARE_SQL).df()
