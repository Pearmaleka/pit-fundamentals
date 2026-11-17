"""Turn the CSVs in results/ into headline numbers (results/headline.json) and figures (docs/figures).

    python scripts/make_report.py [results dir]

Years with censored data are left out of the headline averages: fiscal periods ending before
2011 (most small companies were not yet filing XBRL) and after 2024 (late filers and later
revisions not yet observed).
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results"
FIG = ROOT / "docs" / "figures"
YEARS = (2011, 2024)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]  # fixed categorical order
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dd"
STATUS = {
    "1-LAF": "Large accelerated",
    "2-ACC": "Accelerated",
    "4-NON": "Non-accelerated",
    "5-SML": "Smaller reporting",
}
DEADLINE = {
    ("10-K", "1-LAF"): 60,
    ("10-K", "2-ACC"): 75,
    ("10-K", "4-NON"): 90,
    ("10-K", "5-SML"): 90,
    ("10-Q", "1-LAF"): 40,
    ("10-Q", "2-ACC"): 40,
    ("10-Q", "4-NON"): 45,
    ("10-Q", "5-SML"): 45,
}


def style(ax, title, ylabel=None, xlabel=None):
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    if ylabel:
        ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    if xlabel:
        ax.set_xlabel(xlabel, color=MUTED, fontsize=9)


def weighted(df, cols, w="n"):
    return (df[cols].mul(df[w], axis=0).sum() / df[w].sum()).to_dict()


def lag_section(h):
    by = pd.read_csv(RES / "lag_by_form_status.csv").dropna(subset=["afs"])
    h["lag_by_form_status"] = by.round(4).to_dict("records")
    exp = pd.read_csv(RES / "fixed_lag_exposure.csv")
    exp = exp[exp.period_year.between(*YEARS)]
    cols = [c for c in exp.columns if c.startswith("after_")]
    h["unpublished_after_L_days"] = {
        form: {k: round(v, 4) for k, v in weighted(g, cols).items()} for form, g in exp.groupby("form")
    }
    hist = pd.read_csv(RES / "lag_histogram.csv").dropna(subset=["afs"])
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, form in zip(axes, ("10-K", "10-Q"), strict=True):
        for i, (afs, label) in enumerate(STATUS.items()):
            g = hist[(hist.form == form) & (hist.afs == afs)].sort_values("lag_days")
            cdf = g.n.cumsum() / g.n.sum()
            ax.step(g.lag_days, cdf, where="post", color=SERIES[i], lw=2, label=label)
            ax.axvline(DEADLINE[(form, afs)], color=SERIES[i], lw=0.8, ls=":")
        ax.set_xlim(0, 130 if form == "10-K" else 80)
        style(ax, f"{form}: days from period end to filing", xlabel="days after fiscal period end")
    axes[0].set_ylabel("share of filings filed", color=MUTED, fontsize=9)
    axes[1].legend(frameon=False, fontsize=8, loc="lower right")
    fig.text(
        0.01,
        -0.02,
        "Dotted lines: SEC deadline for each filer status. Filings for periods ending 2009-2026.",
        fontsize=8,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(FIG / "filing_lag.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    exp_all = pd.read_csv(RES / "fixed_lag_exposure.csv")
    exp_all = exp_all[exp_all.period_year.between(*YEARS)]
    fig, ax = plt.subplots(figsize=(7, 3.4))
    lines = [
        ("10-K", "after_60d", "10-K, 60-day rule"),
        ("10-K", "after_90d", "10-K, 90-day rule"),
        ("10-Q", "after_45d", "10-Q, 45-day rule"),
    ]
    for i, (form, col, label) in enumerate(lines):
        g = exp_all[exp_all.form == form]
        ax.plot(g.period_year, 100 * g[col], color=SERIES[i], lw=2, marker="o", ms=4)
        ax.annotate(
            label,
            (g.period_year.iloc[-1], 100 * g[col].iloc[-1]),
            xytext=(6, [0, 5, -5][i]),
            textcoords="offset points",
            va="center",
            fontsize=8,
            color=INK,
        )
    ax.set_ylim(0, None)
    ax.set_xlim(YEARS[0] - 0.5, YEARS[1] + 3.5)
    style(
        ax,
        "Filings not yet public when a fixed reporting lag says they are",
        "% of filings",
        "fiscal year of the period end",
    )
    fig.tight_layout()
    fig.savefig(FIG / "fixed_lag_exposure.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def revisions_section(h):
    tags = pd.read_csv(RES / "revisions_by_tag.csv")
    sizes = pd.read_csv(RES / "revision_sizes_by_tag.csv")
    piv = sizes.pivot(index="tag", columns="size_class", values="n").fillna(0)
    share = piv.div(piv.sum(axis=1), axis=0)
    share["large"] = share[[">=10%", "sign change", "scale x1000"]].sum(axis=1)
    out = tags.set_index("tag").join(share[["large"]]).reset_index()
    h["revisions_by_tag"] = out.round(4).to_dict("records")
    src = pd.read_csv(RES / "revision_sizes_by_source.csv").dropna(subset=["change_form"])
    h["revisions_from_amendments"] = round(src[src.change_form.str.endswith("/A")].n.sum() / src.n.sum(), 4)
    tot = piv.sum()
    h["revisions_overall"] = {
        "facts": int(tot.sum()),
        "changed": round(1 - tot["unchanged"] / tot.sum(), 4),
        "large": round(tot[[">=10%", "sign change", "scale x1000"]].sum() / tot.sum(), 4),
    }
    yr = pd.read_csv(RES / "revisions_by_year_form.csv")
    h["revisions_by_year_form"] = yr.round(4).to_dict("records")

    order = share.sort_values("unchanged").index
    fig, ax = plt.subplots(figsize=(8, 4.2))
    left = pd.Series(0.0, index=order)
    for i, (cls, label) in enumerate(
        [
            ("<1%", "under 1%"),
            ("1-10%", "1-10%"),
            (">=10%", "10% or more"),
            ("sign change", "sign change"),
            ("scale x1000", "x1000 scale error"),
        ]
    ):
        v = 100 * share.loc[order, cls]
        ax.barh(
            range(len(order)),
            v,
            left=left,
            color=SERIES[i],
            height=0.7,
            label=label,
            edgecolor="white",
            linewidth=1,
        )
        left += v
    ax.set_yticks(range(len(order)), [t if len(t) < 34 else t[:31] + "..." for t in order], fontsize=8)
    ax.invert_yaxis()
    ax.grid(axis="x", color=GRID, lw=0.8)
    style(
        ax, "Share of first-published values later changed, by size of the first change", xlabel="% of facts"
    )
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, fontsize=8, ncol=5, loc="upper center", bbox_to_anchor=(0.4, -0.13))
    fig.tight_layout()
    fig.savefig(FIG / "revisions_by_tag.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def lookahead_section(h):
    d = pd.read_csv(RES / "lookahead_monthly.csv", parse_dates=["d"])
    x = d[d.d.dt.year.between(2012, YEARS[1])]
    cols = [
        "n_naive",
        "n_pit",
        "share_not_public",
        "share_other_year",
        "share_same_year_value_differs",
        "share_quintile_differs",
        "share_extreme_not_confirmed",
        "rank_corr",
    ]
    h["lookahead_2012_2024"] = x.groupby("method")[cols].mean().round(4).to_dict("index")
    h["lookahead_by_month_of_year"] = (
        x.assign(month=x.d.dt.month)
        .groupby(["method", "month"])[["share_not_public", "share_quintile_differs"]]
        .mean()
        .round(4)
        .reset_index()
        .to_dict("records")
    )
    labels = {"naive_0m": "stamped at period end", "naive_3m": "3-month lag", "naive_6m": "6-month lag"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for i, (m, label) in enumerate(labels.items()):
        g = x[x.method == m].set_index("d")
        roll = g[["share_not_public", "share_quintile_differs"]].rolling(12).mean()
        axes[0].plot(roll.index, 100 * roll.share_not_public, color=SERIES[i], lw=2, label=label)
        axes[1].plot(roll.index, 100 * roll.share_quintile_differs, color=SERIES[i], lw=2, label=label)
    style(axes[0], "Signals built from a 10-K not yet filed", "% of firms (12-month average)")
    style(axes[1], "Firms in a different ROA quintile than point-in-time", "% of firms (12-month average)")
    axes[0].set_ylim(0, None)
    axes[1].set_ylim(0, None)
    axes[1].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "lookahead.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    h = {}
    parse = pd.read_csv(RES / "parse_log.csv")
    h["rows_repaired_tab_in_field"] = int(parse.irregular_rows.sum())
    lag_section(h)
    revisions_section(h)
    lookahead_section(h)
    (RES / "headline.json").write_text(json.dumps(h, indent=1, default=float))
    print(
        json.dumps(
            {
                k: h[k]
                for k in (
                    "unpublished_after_L_days",
                    "revisions_overall",
                    "revisions_from_amendments",
                    "lookahead_2012_2024",
                )
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
