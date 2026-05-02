#!/usr/bin/env python3
"""Run a focused 7-check robustness suite for the main DDD claim.

Checks:
1) Adjacent-month transition enforcement
2) State-specific treatment timing
3) Staggered-adoption proxy (stacked cohort DiD)
4) State-specific linear trends
5) Alternative low-wage definitions (industry vs income proxy)
6) Randomization-inference p-value (state-level reassignment)
7) Multi-year placebo (2018, 2019) + placebo policy date
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
OUT = REPO / "data" / "outputs" / "main_robustness_suite"

CPS_PATH = RAW / "cps_00006.csv"
CPS_INCOME_PATH = RAW / "cps_income_extension.csv"
POLICY_PATH = RAW / "Policy Milestones - State.csv"
COVID_PATH = RAW / "COVID - State - Daily.csv"
OXCGRT_PATH = RAW / "OxCGRT_US_latest.csv"

LOW_WAGE_INDUSTRIES = set(list(range(8560, 8700)) + list(range(4670, 5800)))
LOW_WAGE_INDUSTRIES_ALT = set(list(range(8560, 8700)))
UNEMPLOYED_CODES = {20, 21, 22}
EMPLOYED_CODES = {10, 12}
FEDERAL_EXPIRATION_DATE = pd.Timestamp("2021-09-01")

STATE_ABBR_TO_FIPS = {
    "AL": 1, "AK": 2, "AZ": 4, "AR": 5, "CA": 6, "CO": 8, "CT": 9, "DE": 10, "DC": 11,
    "FL": 12, "GA": 13, "HI": 15, "ID": 16, "IL": 17, "IN": 18, "IA": 19, "KS": 20, "KY": 21,
    "LA": 22, "ME": 23, "MD": 24, "MA": 25, "MI": 26, "MN": 27, "MS": 28, "MO": 29, "MT": 30,
    "NE": 31, "NV": 32, "NH": 33, "NJ": 34, "NM": 35, "NY": 36, "NC": 37, "ND": 38, "OH": 39,
    "OK": 40, "OR": 41, "PA": 42, "RI": 44, "SC": 45, "SD": 46, "TN": 47, "TX": 48, "UT": 49,
    "VT": 50, "VA": 51, "WA": 53, "WV": 54, "WI": 55, "WY": 56,
}


@dataclass
class FitResult:
    coef: float
    stderr: float
    pval: float
    nobs: int


def prepare_monthly_covid(covid_path: Path) -> pd.DataFrame:
    covid_df = pd.read_csv(covid_path, na_values=".")
    covid_df["new_case_count"] = pd.to_numeric(covid_df["new_case_count"], errors="coerce").fillna(0)
    out = (
        covid_df.groupby(["statefips", "year", "month"], as_index=False)["new_case_count"]
        .sum()
        .rename(columns={"statefips": "STATEFIP", "year": "YEAR", "month": "MONTH"})
    )
    out["log_monthly_cases"] = np.log1p(out["new_case_count"])
    return out[["STATEFIP", "YEAR", "MONTH", "log_monthly_cases"]]


def prepare_monthly_stringency(path: Path) -> pd.DataFrame:
    usecols = ["CountryCode", "Jurisdiction", "RegionCode", "Date", "StringencyIndex"]
    ox = pd.read_csv(path, usecols=usecols, low_memory=False)
    ox = ox[
        (ox["CountryCode"] == "USA")
        & (ox["Jurisdiction"] == "STATE_WIDE")
        & ox["RegionCode"].notna()
    ].copy()
    ox["STATE_ABBR"] = ox["RegionCode"].str.split("_").str[-1]
    ox["STATEFIP"] = ox["STATE_ABBR"].map(STATE_ABBR_TO_FIPS)
    ox["Date"] = pd.to_datetime(ox["Date"], format="%Y%m%d", errors="coerce")
    ox["StringencyIndex"] = pd.to_numeric(ox["StringencyIndex"], errors="coerce")
    ox = ox.dropna(subset=["STATEFIP", "Date", "StringencyIndex"])
    ox["YEAR"] = ox["Date"].dt.year
    ox["MONTH"] = ox["Date"].dt.month
    out = (
        ox.groupby(["STATEFIP", "YEAR", "MONTH"], as_index=False)["StringencyIndex"]
        .mean()
        .rename(columns={"StringencyIndex": "avg_stringency"})
    )
    out["STATEFIP"] = out["STATEFIP"].astype(int)
    return out


def load_treatment_dates(policy_path: Path) -> pd.DataFrame:
    policy = pd.read_csv(policy_path)
    policy["date"] = pd.to_datetime(policy["date"], errors="coerce")
    policy = policy.dropna(subset=["date"])
    mask = policy["policy_description"].str.contains(
        r"end(?:s|ed) emergency employment benefits", case=False, na=False, regex=True
    ) & (policy["date"] < FEDERAL_EXPIRATION_DATE)
    t = policy.loc[mask, ["statefips", "date"]].copy()
    t = t.sort_values(["statefips", "date"]).drop_duplicates("statefips", keep="first")
    t["treat_month"] = t["date"].dt.month.astype(int)
    return t.rename(columns={"statefips": "STATEFIP"})[["STATEFIP", "date", "treat_month"]]


def load_cps(path: Path) -> pd.DataFrame:
    use = ["YEAR", "MONTH", "STATEFIP", "CPSIDP", "EMPSTAT", "IND", "AGE", "EDUC", "LNKFW1MWT"]
    df = pd.read_csv(path, usecols=use, low_memory=False)
    for c in ["YEAR", "MONTH", "STATEFIP", "EMPSTAT", "IND", "AGE", "EDUC", "LNKFW1MWT"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["CPSIDP"] = df["CPSIDP"].astype(str)
    df = df[df["YEAR"].between(2018, 2021)].copy()
    df["INCWAGE"] = np.nan
    df["INCTOT"] = np.nan
    return df


def attach_income_if_valid(base: pd.DataFrame, income_path: Path) -> tuple[pd.DataFrame, bool]:
    if not income_path.exists():
        return base, False
    use = ["YEAR", "MONTH", "STATEFIP", "CPSIDP", "INCWAGE", "INCTOT", "LNKFW1MWT"]
    ext = pd.read_csv(income_path, usecols=use, low_memory=False)
    for c in ["YEAR", "MONTH", "STATEFIP", "INCWAGE", "INCTOT", "LNKFW1MWT"]:
        ext[c] = pd.to_numeric(ext[c], errors="coerce")
    ext["CPSIDP"] = ext["CPSIDP"].astype(str)
    ext = ext[ext["YEAR"].between(2018, 2021)].copy()
    # Require valid linked monthly weights in the same policy window.
    if ext["LNKFW1MWT"].notna().mean() < 0.5:
        return base, False
    ext = ext[["YEAR", "MONTH", "STATEFIP", "CPSIDP", "INCWAGE", "INCTOT"]].drop_duplicates()
    merged = base.merge(ext, on=["YEAR", "MONTH", "STATEFIP", "CPSIDP"], how="left", suffixes=("", "_ext"))
    for col in ["INCWAGE", "INCTOT"]:
        alt = f"{col}_ext"
        if alt in merged.columns:
            merged[col] = merged[alt]
            merged = merged.drop(columns=[alt])
    return merged, True


def add_transitions(df: pd.DataFrame, adjacent_only: bool) -> pd.DataFrame:
    d = df.sort_values(["CPSIDP", "YEAR", "MONTH"]).copy()
    d["period"] = d["YEAR"] * 12 + d["MONTH"]
    d["next_period"] = d.groupby("CPSIDP")["period"].shift(-1)
    d["next_empstat"] = d.groupby("CPSIDP")["EMPSTAT"].shift(-1)
    if adjacent_only:
        d = d[(d["next_period"] - d["period"]) == 1].copy()
    d = d[d["EMPSTAT"].isin(UNEMPLOYED_CODES)].copy()
    d["found_job"] = d["next_empstat"].isin(EMPLOYED_CODES).astype(int)
    return d


def add_low_wage_defs(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["LowWage_ind"] = d["IND"].isin(list(LOW_WAGE_INDUSTRIES)).astype(int)
    d["LowWage_ind_alt"] = d["IND"].isin(list(LOW_WAGE_INDUSTRIES_ALT)).astype(int)
    # Income-proxy threshold from pre-period 2021 months 2-6 where positive income is observed.
    ref = d[(d["YEAR"] == 2021) & (d["MONTH"].between(2, 6)) & (d["INCWAGE"] > 0)]["INCWAGE"]
    thr = float(ref.quantile(0.33)) if len(ref) else np.nan
    if math.isfinite(thr):
        d["LowWage_inc"] = (d["INCWAGE"] <= thr).astype(int)
    else:
        d["LowWage_inc"] = np.nan
    return d


def build_panel(
    trans: pd.DataFrame,
    treatment_dates: pd.DataFrame,
    monthly_covid: pd.DataFrame,
    monthly_stringency: pd.DataFrame,
    year: int,
    post_mode: str,
    low_wage_col: str,
    placebo_policy_month: int | None = None,
) -> pd.DataFrame:
    d = trans[trans["YEAR"] == year].copy()
    d = d[d["MONTH"].between(2, 8)].copy()
    d = d.merge(treatment_dates, on="STATEFIP", how="left")
    d["TreatState"] = d["date"].notna().astype(int)

    if post_mode == "common_july":
        cut = 7 if placebo_policy_month is None else placebo_policy_month
        d["Post"] = d["MONTH"].between(cut, min(cut + 1, 12)).astype(int)
    elif post_mode == "state_specific":
        # Canonical staggered post coding:
        # treated states switch on at own treatment month; never-treated remain 0.
        d["Post"] = np.where(d["TreatState"] == 1, (d["MONTH"] >= d["treat_month"]), 0).astype(int)
    else:
        raise ValueError(post_mode)

    d = d.dropna(subset=["found_job", "LNKFW1MWT", low_wage_col, "STATEFIP", "MONTH"]).copy()
    d = d[d["LNKFW1MWT"] > 0].copy()
    d = d.merge(monthly_covid, on=["STATEFIP", "YEAR", "MONTH"], how="left")
    d = d.merge(monthly_stringency, on=["STATEFIP", "YEAR", "MONTH"], how="left")
    d["log_monthly_cases"] = d["log_monthly_cases"].fillna(0)
    d["avg_stringency"] = d["avg_stringency"].fillna(0)
    d["LowWage"] = d[low_wage_col].astype(int)
    d["t"] = d["MONTH"] - d["MONTH"].min()
    return d


def fit_main(df: pd.DataFrame, with_state_trends: bool = False) -> FitResult:
    if df.empty or df["MONTH"].nunique() < 2 or df["STATEFIP"].nunique() < 2:
        return FitResult(np.nan, np.nan, np.nan, 0)
    parts = [
        "found_job ~ TreatState * Post * LowWage",
        "log_monthly_cases",
        "avg_stringency",
        "C(STATEFIP)",
        "C(MONTH)",
    ]
    if with_state_trends:
        parts.append("C(STATEFIP):t")
    fit = smf.wls(" + ".join(parts), data=df, weights=df["LNKFW1MWT"]).fit(
        cov_type="cluster", cov_kwds={"groups": df["STATEFIP"]}
    )
    term = "TreatState:Post:LowWage"
    return FitResult(
        coef=float(fit.params.get(term, np.nan)),
        stderr=float(fit.bse.get(term, np.nan)),
        pval=float(fit.pvalues.get(term, np.nan)),
        nobs=int(fit.nobs),
    )


def randomization_inference(df: pd.DataFrame, draws: int = 250, seed: int = 42) -> float:
    rng = np.random.default_rng(seed)
    states = np.sort(df["STATEFIP"].unique())
    treated_states = set(df.loc[df["TreatState"] == 1, "STATEFIP"].unique())
    n_treat = len(treated_states)
    if n_treat == 0:
        return np.nan
    obs = abs(fit_main(df).coef)
    sim = []
    for _ in range(draws):
        fake = set(rng.choice(states, size=n_treat, replace=False).tolist())
        d = df.copy()
        d["TreatState"] = d["STATEFIP"].isin(fake).astype(int)
        sim.append(abs(fit_main(d).coef))
    sim = np.array(sim)
    return float((np.sum(sim >= obs) + 1) / (len(sim) + 1))


def stacked_cohort_proxy(df: pd.DataFrame) -> FitResult:
    # Proxy for staggered-adoption robustness:
    # average cohort-specific 2x2 DiD interactions against not-yet-treated controls.
    treated = df[df["TreatState"] == 1][["STATEFIP", "treat_month"]].drop_duplicates()
    rows = []
    weights = []
    for m in sorted(treated["treat_month"].dropna().astype(int).unique().tolist()):
        cohort_states = set(treated.loc[treated["treat_month"] == m, "STATEFIP"].tolist())
        control_states = set(
            treated.loc[treated["treat_month"] > m, "STATEFIP"].tolist()
        ).union(set(df.loc[df["TreatState"] == 0, "STATEFIP"].unique().tolist()))
        sub = df[df["STATEFIP"].isin(cohort_states.union(control_states))].copy()
        if sub.empty or not control_states:
            continue
        sub["CohortTreat"] = sub["STATEFIP"].isin(cohort_states).astype(int)
        sub["CohortPost"] = sub["MONTH"].between(m, min(m + 1, 12)).astype(int)
        fit = smf.wls(
            "found_job ~ CohortTreat*CohortPost*LowWage + log_monthly_cases + avg_stringency + C(STATEFIP)+C(MONTH)",
            data=sub,
            weights=sub["LNKFW1MWT"],
        ).fit(cov_type="cluster", cov_kwds={"groups": sub["STATEFIP"]})
        term = "CohortTreat:CohortPost:LowWage"
        if term in fit.params:
            rows.append((float(fit.params[term]), float(fit.bse[term]), float(fit.pvalues[term]), int(fit.nobs)))
            weights.append(int(fit.nobs))
    if not rows:
        return FitResult(np.nan, np.nan, np.nan, 0)
    w = np.array(weights, dtype=float)
    coef = float(np.average([r[0] for r in rows], weights=w))
    stderr = float(np.average([r[1] for r in rows], weights=w))
    pval = float(np.average([r[2] for r in rows], weights=w))
    nobs = int(np.sum(weights))
    return FitResult(coef, stderr, pval, nobs)


def add_row(rows: list[dict], check: str, variant: str, r: FitResult, extra: str = "") -> None:
    rows.append(
        {
            "check": check,
            "variant": variant,
            "coef": r.coef,
            "stderr": r.stderr,
            "pval": r.pval,
            "nobs": r.nobs,
            "note": extra,
        }
    )


def run_subgroup_dd_slices(final_panel: pd.DataFrame, year: int) -> pd.DataFrame:
    """Supplemental subgroup DD table (teammate-requested view).

    Note: This is DD within slices, not pooled DDD.
    """
    subgroups = {
        "Food/Retail (low-wage industries)": final_panel[final_panel["LowWage"] == 1],
        "Other industries": final_panel[final_panel["LowWage"] == 0],
        "Young workers (14-25)": final_panel[final_panel["AGE"].between(14, 25)],
        "Prime age (26-54)": final_panel[final_panel["AGE"].between(26, 54)],
        "Near-retirement (55+)": final_panel[final_panel["AGE"] >= 55],
    }
    out_rows = []
    formula = "found_job ~ TreatState * Post + log_monthly_cases + avg_stringency + C(STATEFIP) + C(MONTH)"
    for label, subset in subgroups.items():
        subset = subset.copy()
        if len(subset) < 100 or subset["TreatState"].nunique() < 2 or subset["Post"].nunique() < 2:
            out_rows.append(
                {
                    "year": year,
                    "subgroup": label,
                    "nobs": int(len(subset)),
                    "coef": np.nan,
                    "stderr": np.nan,
                    "pval": np.nan,
                    "note": "insufficient variation",
                }
            )
            continue
        try:
            fit = smf.wls(formula, data=subset, weights=subset["LNKFW1MWT"]).fit(
                cov_type="cluster", cov_kwds={"groups": subset["STATEFIP"]}
            )
            term = "TreatState:Post"
            out_rows.append(
                {
                    "year": year,
                    "subgroup": label,
                    "nobs": int(fit.nobs),
                    "coef": float(fit.params.get(term, np.nan)),
                    "stderr": float(fit.bse.get(term, np.nan)),
                    "pval": float(fit.pvalues.get(term, np.nan)),
                    "note": "",
                }
            )
        except Exception as exc:  # pragma: no cover - diagnostic path
            out_rows.append(
                {
                    "year": year,
                    "subgroup": label,
                    "nobs": int(len(subset)),
                    "coef": np.nan,
                    "stderr": np.nan,
                    "pval": np.nan,
                    "note": f"error: {exc}",
                }
            )
    return pd.DataFrame(out_rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cps = load_cps(CPS_PATH)
    cps, income_ok = attach_income_if_valid(cps, CPS_INCOME_PATH)
    treat_dates = load_treatment_dates(POLICY_PATH)
    m_covid = prepare_monthly_covid(COVID_PATH)
    m_str = prepare_monthly_stringency(OXCGRT_PATH)

    trans_noadj = add_low_wage_defs(add_transitions(cps, adjacent_only=False))
    trans_adj = add_low_wage_defs(add_transitions(cps, adjacent_only=True))

    rows: list[dict] = []

    # 1) Adjacent month enforcement
    p_noadj = build_panel(trans_noadj, treat_dates, m_covid, m_str, 2021, "common_july", "LowWage_ind")
    p_adj = build_panel(trans_adj, treat_dates, m_covid, m_str, 2021, "common_july", "LowWage_ind")
    add_row(rows, "1_adjacent_transition", "no_adjacency_filter", fit_main(p_noadj))
    add_row(rows, "1_adjacent_transition", "adjacent_only", fit_main(p_adj))

    # 2) State-specific treatment timing
    p_state = build_panel(trans_adj, treat_dates, m_covid, m_str, 2021, "state_specific", "LowWage_ind")
    add_row(rows, "2_state_specific_timing", "state_specific_post", fit_main(p_state))
    # Holzer-aligned cohort check: June opt-outs vs states that maintained through September.
    june_states = set(treat_dates.loc[treat_dates["treat_month"] == 6, "STATEFIP"].tolist())
    early_states = set(treat_dates["STATEFIP"].tolist())
    avail_states = set(p_state["STATEFIP"].dropna().astype(int).unique().tolist())
    maintain_states = avail_states - early_states
    p_holzer = build_panel(trans_adj, treat_dates, m_covid, m_str, 2021, "common_july", "LowWage_ind")
    p_holzer = p_holzer[p_holzer["STATEFIP"].isin(june_states.union(maintain_states))].copy()
    p_holzer["TreatState"] = p_holzer["STATEFIP"].isin(june_states).astype(int)
    p_holzer["Post"] = p_holzer["MONTH"].between(7, 8).astype(int)
    add_row(rows, "2_state_specific_timing", "holzer_june_vs_maintainers", fit_main(p_holzer))

    # 3) Staggered-adoption proxy
    add_row(rows, "3_staggered_proxy", "stacked_cohort_proxy", stacked_cohort_proxy(p_state))

    # 4) State-specific linear trends
    add_row(rows, "4_state_trends", "with_state_linear_trends", fit_main(p_state, with_state_trends=True))

    # 5) Alternative low-wage definitions
    p_ind_alt = build_panel(trans_adj, treat_dates, m_covid, m_str, 2021, "state_specific", "LowWage_ind_alt")
    add_row(rows, "5_low_wage_definition", "industry_proxy", fit_main(p_state))
    add_row(rows, "5_low_wage_definition", "industry_proxy_alt", fit_main(p_ind_alt))
    if income_ok:
        p_inc = build_panel(trans_adj, treat_dates, m_covid, m_str, 2021, "state_specific", "LowWage_inc")
        add_row(rows, "5_low_wage_definition", "income_proxy_incwage_q33", fit_main(p_inc))
    else:
        add_row(
            rows,
            "5_low_wage_definition",
            "income_proxy_incwage_q33",
            FitResult(np.nan, np.nan, np.nan, 0),
            extra="pending: income extract lacks valid 2018-2021 linked monthly weights",
        )

    # 6) Randomization inference
    ri_p = randomization_inference(p_state, draws=250, seed=42)
    add_row(
        rows,
        "6_randomization_inference",
        "state_reassignment_250draws",
        fit_main(p_state),
        extra=f"ri_p={ri_p:.4f}",
    )

    # 7) Placebo years and placebo policy month
    p_2018 = build_panel(trans_adj, treat_dates, m_covid, m_str, 2018, "common_july", "LowWage_ind")
    p_2019 = build_panel(trans_adj, treat_dates, m_covid, m_str, 2019, "common_july", "LowWage_ind")
    p_2021_placebo_date = build_panel(
        trans_adj, treat_dates, m_covid, m_str, 2021, "common_july", "LowWage_ind", placebo_policy_month=5
    )
    add_row(rows, "7_placebo", "year_2018", fit_main(p_2018))
    add_row(rows, "7_placebo", "year_2019", fit_main(p_2019))
    add_row(rows, "7_placebo", "fake_policy_month_may_2021", fit_main(p_2021_placebo_date))

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "robustness_checks.csv", index=False)
    subgroup_dd = run_subgroup_dd_slices(p_state, year=2021)
    subgroup_dd.to_csv(OUT / "subgroup_dd_slices.csv", index=False)

    lines = [
        "# Main Claim Robustness Suite",
        "",
        "Generated by `scripts/main_claim_robustness_suite.py`.",
        "",
        "## Results",
        "",
        "```text",
        out.to_string(index=False),
        "```",
        "",
        "## Subgroup DD Slices (Supplemental)",
        "",
        "```text",
        subgroup_dd.to_string(index=False),
        "```",
        "",
        "## Interpretation Guide",
        "",
        "- Main term is `TreatState x Post x LowWage`.",
        "- More stable inference means direction/significance persists across checks.",
        "- Placebo rows should ideally be near zero and not significant.",
    ]
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")

    print(f"Wrote {OUT / 'robustness_checks.csv'}")
    print(f"Wrote {OUT / 'summary.md'}")


if __name__ == "__main__":
    main()
