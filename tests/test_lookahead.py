from conftest import make_facts

from pitfund import lookahead


def _annual(cik, adsh, form, period, accepted, ddate, ni, at):
    base = dict(cik=cik, adsh=adsh, form=form, period=period, accepted=accepted, ddate=ddate, uom="USD")
    return [
        {**base, "tag": "NetIncomeLoss", "qtrs": 4, "value": ni},
        {**base, "tag": "Assets", "qtrs": 0, "value": at},
    ]


def _panel(con):
    return con.execute("SELECT method, d::VARCHAR AS d, cik, p::VARCHAR AS p, roa, public FROM panel").df()


def test_pit_waits_for_the_filing_and_ignores_later_restatement(con):
    make_facts(
        con,
        _annual(1, "k21", "10-K", "2021-12-31", "2022-03-01 16:00", "2021-12-31", 10.0, 100.0)
        + _annual(1, "k22", "10-K", "2022-12-31", "2023-03-15 16:00", "2022-12-31", 20.0, 100.0)
        # FY2022 restated in the FY2023 10-K
        + _annual(1, "k23", "10-K", "2023-12-31", "2024-03-01 16:00", "2022-12-31", 5.0, 100.0)
        + _annual(1, "k23", "10-K", "2023-12-31", "2024-03-01 16:00", "2023-12-31", 30.0, 100.0),
    )
    lookahead.build(con, start="2023-01-01", end="2023-05-01")
    p = _panel(con).set_index(["method", "d", "cik"])
    # January 2023: FY2022 not filed yet
    assert p.loc[("pit", "2023-01-31", 1), "p"] == "2021-12-31"
    jan0 = p.loc[("naive_0m", "2023-01-31", 1)]
    assert jan0.p == "2022-12-31" and not jan0.public and abs(jan0.roa - 0.05) < 1e-12
    # March 31: the original 10-K is out; PIT shows 0.20, the snapshot shows the restated 0.05
    assert abs(p.loc[("pit", "2023-03-31", 1), "roa"] - 0.20) < 1e-12
    assert abs(p.loc[("naive_3m", "2023-03-31", 1), "roa"] - 0.05) < 1e-12
    assert p.loc[("naive_6m", "2023-03-31", 1), "p"] == "2021-12-31"


def test_compare_counts(con):
    rows = []
    for cik in range(1, 11):
        rows += _annual(cik, f"a{cik}", "10-K", "2022-12-31", "2023-02-15", "2022-12-31", float(cik), 100.0)
    make_facts(con, rows)
    lookahead.build(con, start="2023-01-01", end="2023-04-01")
    c = lookahead.compare(con).set_index(["method", "d"])
    jan = c.loc[("naive_0m", "2023-01-31")]
    assert jan.n_naive == 10 and jan.n_pit == 0 and jan.share_not_public == 1.0
    mar = c.loc[("naive_0m", "2023-03-31")]
    assert mar.share_not_public == 0 and mar.share_quintile_differs == 0
    assert abs(mar.rank_corr - 1) < 1e-12
