from conftest import make_facts

from pitfund import revisions


def _row(cik, adsh, form, period, accepted, tag, ddate, value, qtrs=4):
    return dict(
        cik=cik,
        adsh=adsh,
        form=form,
        period=period,
        accepted=accepted,
        tag=tag,
        ddate=ddate,
        qtrs=qtrs,
        uom="USD",
        value=value,
    )


def test_first_report_and_change(con):
    make_facts(
        con,
        [
            # restated a year later by 10%
            _row(1, "k22", "10-K", "2022-12-31", "2023-03-01", "NetIncomeLoss", "2022-12-31", 100.0),
            _row(1, "k23", "10-K", "2023-12-31", "2024-03-01", "NetIncomeLoss", "2022-12-31", 110.0),
            _row(1, "k23", "10-K", "2023-12-31", "2024-03-01", "NetIncomeLoss", "2023-12-31", 50.0),
            # repeated unchanged
            _row(2, "j22", "10-K", "2022-12-31", "2023-02-01", "NetIncomeLoss", "2022-12-31", 7.0),
            _row(2, "j23", "10-K", "2023-12-31", "2024-02-01", "NetIncomeLoss", "2022-12-31", 7.0),
            # first seen only as a comparative: excluded
            _row(3, "m23", "10-K", "2023-12-31", "2024-02-01", "NetIncomeLoss", "2022-12-31", 9.0),
            # thousand-fold error fixed by an amendment
            _row(4, "a", "10-K", "2022-12-31", "2023-02-01", "Assets", "2022-12-31", 5e9, qtrs=0),
            _row(4, "a2", "10-K/A", "2022-12-31", "2023-04-01", "Assets", "2022-12-31", 5e6, qtrs=0),
        ],
    )
    revisions.build(con)
    h = con.execute("SELECT * FROM fact_history ORDER BY cik, ddate").df()
    assert set(zip(h.cik, h.ddate.astype(str), strict=True)) == {
        (1, "2022-12-31"),
        (1, "2023-12-31"),
        (2, "2022-12-31"),
        (4, "2022-12-31"),
    }
    r1 = h[(h.cik == 1) & (h.ddate.astype(str) == "2022-12-31")].iloc[0]
    assert r1.first_value == 100 and r1.final_value == 110 and r1.change_form == "10-K"
    assert r1.days_to_change == 366  # 2024 is a leap year
    s = revisions.size_classes(con, by="cik").set_index("cik")
    assert s.loc[1].set_index("size_class").loc[">=10%", "n"] == 1
    assert s.loc[4, "size_class"] == "scale x1000"
    summ = revisions.summary(con, by="tag").set_index("tag")
    assert summ.loc["NetIncomeLoss", "n_facts"] == 3
    assert abs(summ.loc["NetIncomeLoss", "share_changed_if_rereported"] - 0.5) < 1e-12


def test_conflicting_values_in_one_filing_are_dropped(con):
    make_facts(
        con,
        [
            _row(1, "k", "10-K", "2022-12-31", "2023-03-01", "NetIncomeLoss", "2022-12-31", 1.0),
            _row(1, "k", "10-K", "2022-12-31", "2023-03-01", "NetIncomeLoss", "2022-12-31", 2.0),
        ],
    )
    revisions.build(con)
    assert con.execute("SELECT count(*) FROM fact_history").fetchone()[0] == 0


def test_per_tag_files_match_single_pass(con, tmp_path):
    make_facts(
        con,
        [
            _row(1, "k22", "10-K", "2022-12-31", "2023-03-01", "NetIncomeLoss", "2022-12-31", 100.0),
            _row(1, "k23", "10-K", "2023-12-31", "2024-03-01", "NetIncomeLoss", "2022-12-31", 110.0),
            _row(1, "k22", "10-K", "2022-12-31", "2023-03-01", "Assets", "2022-12-31", 5.0, qtrs=0),
        ],
    )
    revisions.build(con)
    one = revisions.summary(con)
    assert revisions.build(con, out_dir=tmp_path)
    assert sorted(p.name for p in tmp_path.glob("*.parquet"))[:2] == [
        "Assets.parquet",
        "CashAndCashEquivalentsAtCarryingValue.parquet",
    ]
    assert revisions.summary(con).equals(one)
