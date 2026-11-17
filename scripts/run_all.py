"""Run the measurements on the converted SEC data and write small CSV results.

    python scripts/run_all.py <quant-lab root> [step ...]

Steps: lag, revisions, lookahead (default: all). Inputs are <root>/parquet/sub/*.parquet and
<root>/pit/facts/*.parquet (built by scripts/build_store.py). Outputs go to <root>/results/.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pitfund import filings, lookahead, revisions, store  # noqa: E402


def main() -> None:
    root = Path(sys.argv[1])
    steps = sys.argv[2:] or ["lag", "revisions", "lookahead"]
    out = root / "results"
    out.mkdir(exist_ok=True)
    con = store.connect(temp_dir=str(root / "tmp_duckdb"))
    store.facts_view(con, root / "pit")
    n_quarters = len(list((root / "pit" / "facts").glob("*.parquet")))
    t = time.time()
    filings.load_filings(con, root / "parquet")
    print("filings", round(time.time() - t, 1), flush=True)
    if "lag" in steps:
        filings.lag_summary(con).to_csv(out / "lag_by_year_form_status.csv", index=False)
        filings.lag_summary(con, by="form, afs").to_csv(out / "lag_by_form_status.csv", index=False)
        filings.fixed_lag_exposure(con).to_csv(out / "fixed_lag_exposure.csv", index=False)
        con.execute(
            "SELECT form, afs, lag_days, count(*) AS n FROM filing_lag GROUP BY ALL ORDER BY ALL"
        ).df().to_csv(out / "lag_histogram.csv", index=False)
        print("lag", round(time.time() - t, 1), flush=True)
    if "revisions" in steps:
        if not revisions.build(con, out_dir=root / "pit" / f"fact_history_{n_quarters}q", budget_s=100):
            print("revisions: partial, run again", flush=True)
            return
        print("revisions built", round(time.time() - t, 1), flush=True)
        revisions.summary(con, by="tag").to_csv(out / "revisions_by_tag.csv", index=False)
        revisions.summary(con, by="year(first_accepted) AS year, first_form").to_csv(
            out / "revisions_by_year_form.csv", index=False
        )
        revisions.size_classes(con, by="tag").to_csv(out / "revision_sizes_by_tag.csv", index=False)
        src = revisions.size_classes(con, by="change_form")
        src.to_csv(out / "revision_sizes_by_source.csv", index=False)
        print("revisions", round(time.time() - t, 1), flush=True)
    if "lookahead" in steps:
        lookahead.build(con)
        print("panel built", round(time.time() - t, 1), flush=True)
        lookahead.compare(con).to_csv(out / "lookahead_monthly.csv", index=False)
        print("lookahead", round(time.time() - t, 1), flush=True)


if __name__ == "__main__":
    main()
