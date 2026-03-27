"""Holzer-style robustness checks built from the final DDD notebook logic.

This script intentionally does not require a literal wage variable. It uses the
same industry-based low-wage proxy already used in
`notebooks/SignificanceHolzerStyle.ipynb`, then layers on robustness checks that
are closer to Holzer et al.'s style:

- with/without COVID and stringency controls
- sample-split sensitivity (all ages, prime-age, no-college, prime-age no-college)
- separate subgroup 2x2 DiD models
- subgroup event studies for low-wage and other-wage groups

Outputs are written to `data/outputs/holzer_style_robustness/` by default.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(REPO_ROOT / ".private" / "mpl_cache"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


FEDERAL_EXPIRATION_DATE = pd.Timestamp("2021-09-01")
HOLZER_JUNE_START = pd.Timestamp("2021-06-01")
HOLZER_JUNE_END = pd.Timestamp("2021-06-30")
LOW_WAGE_INDUSTRIES = list(range(8560, 8700)) + list(range(4670, 5800))
UNEMPLOYED_CODES = {20, 21, 22}
EMPLOYMENT_OUTCOME_CODES = {
    "any_employed": {10, 12},
    "at_work_only": {10},
}
EMPSTAT_LABELS = {
    0: "NIU",
    1: "Armed Forces",
    10: "At work",
    12: "Has job, not at work last week",
    20: "Unemployed",
    21: "Unemployed, experienced worker",
    22: "Unemployed, new worker",
    30: "Not in labor force",
    31: "NILF, housework",
    32: "NILF, unable to work",
    33: "NILF, school",
    34: "NILF, other",
    35: "NILF, unpaid, lt 15 hours",
    36: "NILF, retired",
}

# IPUMS CPS EDUC codes: bachelor's begins at 111. Treat codes below that as
# "no college degree" for Holzer-style sample splits.
NO_COLLEGE_MAX_CODE = 110

STATE_ABBR_TO_FIPS = {
    "AL": 1,
    "AK": 2,
    "AZ": 4,
    "AR": 5,
    "CA": 6,
    "CO": 8,
    "CT": 9,
    "DE": 10,
    "DC": 11,
    "FL": 12,
    "GA": 13,
    "HI": 15,
    "ID": 16,
    "IL": 17,
    "IN": 18,
    "IA": 19,
    "KS": 20,
    "KY": 21,
    "LA": 22,
    "ME": 23,
    "MD": 24,
    "MA": 25,
    "MI": 26,
    "MN": 27,
    "MS": 28,
    "MO": 29,
    "MT": 30,
    "NE": 31,
    "NV": 32,
    "NH": 33,
    "NJ": 34,
    "NM": 35,
    "NY": 36,
    "NC": 37,
    "ND": 38,
    "OH": 39,
    "OK": 40,
    "OR": 41,
    "PA": 42,
    "RI": 44,
    "SC": 45,
    "SD": 46,
    "TN": 47,
    "TX": 48,
    "UT": 49,
    "VT": 50,
    "VA": 51,
    "WA": 53,
    "WV": 54,
    "WI": 55,
    "WY": 56,
}


@dataclass(frozen=True)
class SampleSpec:
    name: str
    description: str


SAMPLE_SPECS = [
    SampleSpec("all_ages", "All ages available in CPS extract"),
    SampleSpec("prime_age", "Prime-age workers (25-54)"),
    SampleSpec("no_college", "Workers without a bachelor's degree"),
    SampleSpec("prime_age_no_college", "Prime-age workers without a bachelor's degree"),
]

CONTROL_SPECS = ["none", "covid", "covid_stringency"]
TREATMENT_MODES = ["june_only", "all_early_exits"]
EMPLOYMENT_MODES = ["any_employed", "at_work_only"]


def parse_args() -> argparse.Namespace:
    repo_root = REPO_ROOT
    default_data = repo_root / "data" / "raw"
    default_output = repo_root / "data" / "outputs" / "holzer_style_robustness"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cps-path", default=str(default_data / "cps_00006.csv"))
    parser.add_argument(
        "--policy-path",
        default=str(default_data / "Policy Milestones - State.csv"),
    )
    parser.add_argument(
        "--covid-path",
        default=str(default_data / "COVID - State - Daily.csv"),
    )
    parser.add_argument(
        "--oxcgrt-path",
        default=str(default_data / "OxCGRT_US_latest.csv"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_output),
        help="Directory for CSV, PNG, and markdown outputs.",
    )
    parser.add_argument(
        "--analysis-year",
        type=int,
        default=2021,
        help="Main treatment year.",
    )
    parser.add_argument(
        "--placebo-year",
        type=int,
        default=2018,
        help="Placebo year to run through the same grid.",
    )
    parser.add_argument(
        "--policy-month",
        type=int,
        default=7,
        help="Post-period starts in this calendar month.",
    )
    parser.add_argument(
        "--treatment-mode",
        choices=TREATMENT_MODES + ["both"],
        default="both",
        help="Use a single treatment set or run both for sensitivity.",
    )
    parser.add_argument(
        "--employment-mode",
        choices=EMPLOYMENT_MODES + ["both"],
        default="both",
        help="Use a single employment-transition definition or run both.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Only validate inputs and build one sample panel. Skip regressions.",
    )
    return parser.parse_args()


def define_low_wage(industry_code: float) -> float:
    if pd.isna(industry_code):
        return np.nan
    industry_code = int(industry_code)
    if industry_code in LOW_WAGE_INDUSTRIES:
        return 1.0
    if industry_code > 0:
        return 0.0
    return np.nan


def apply_sample_filter(panel: pd.DataFrame, sample_name: str) -> pd.DataFrame:
    if sample_name == "all_ages":
        mask = pd.Series(True, index=panel.index)
    elif sample_name == "prime_age":
        mask = panel["AGE"].between(25, 54)
    elif sample_name == "no_college":
        mask = panel["EDUC"] <= NO_COLLEGE_MAX_CODE
    elif sample_name == "prime_age_no_college":
        mask = panel["AGE"].between(25, 54) & (panel["EDUC"] <= NO_COLLEGE_MAX_CODE)
    else:
        raise ValueError(f"Unknown sample spec: {sample_name}")
    return panel.loc[mask].copy()


def load_treatment_states(policy_path: Path, mode: str) -> set[int]:
    policy_df = pd.read_csv(policy_path)
    policy_df["date"] = pd.to_datetime(policy_df["date"], errors="coerce")
    policy_df = policy_df.dropna(subset=["date"])

    mask = policy_df["policy_description"].str.contains(
        r"end(?:s|ed) emergency employment benefits",
        case=False,
        na=False,
        regex=True,
    ) & (policy_df["date"] < FEDERAL_EXPIRATION_DATE)

    if mode == "june_only":
        mask &= policy_df["date"].between(HOLZER_JUNE_START, HOLZER_JUNE_END)

    treat_df = policy_df.loc[mask, ["statefips", "date"]].copy()
    treat_df.sort_values(["statefips", "date"], inplace=True)
    treat_df.drop_duplicates(subset=["statefips"], keep="first", inplace=True)
    return set(treat_df["statefips"].astype(int).tolist())


def load_cps(cps_path: Path) -> pd.DataFrame:
    usecols = [
        "YEAR",
        "MONTH",
        "STATEFIP",
        "CPSIDP",
        "EMPSTAT",
        "IND",
        "AGE",
        "EDUC",
        "LNKFW1MWT",
    ]
    df = pd.read_csv(cps_path, usecols=usecols)
    numeric_cols = ["YEAR", "MONTH", "STATEFIP", "EMPSTAT", "IND", "AGE", "EDUC", "LNKFW1MWT"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["CPSIDP"] = df["CPSIDP"].astype(str)
    return df


def summarize_empstat_distribution(cps_df: pd.DataFrame, output_dir: Path) -> None:
    rows = []
    years = sorted(cps_df["YEAR"].dropna().unique().astype(int).tolist())

    for year in [None] + years:
        year_df = cps_df if year is None else cps_df[cps_df["YEAR"] == year]
        counts = year_df["EMPSTAT"].dropna().astype(int).value_counts().sort_index()
        for empstat, count in counts.items():
            rows.append(
                {
                    "year": "all" if year is None else int(year),
                    "empstat": int(empstat),
                    "label": EMPSTAT_LABELS.get(int(empstat), "Unknown"),
                    "count": int(count),
                }
            )

    pd.DataFrame(rows).to_csv(output_dir / "empstat_distribution.csv", index=False)


def prepare_monthly_covid(covid_path: Path) -> pd.DataFrame:
    covid_df = pd.read_csv(covid_path, na_values=".")
    covid_df["new_case_count"] = pd.to_numeric(covid_df["new_case_count"], errors="coerce").fillna(0)
    monthly_covid = (
        covid_df.groupby(["statefips", "year", "month"], as_index=False)["new_case_count"]
        .sum()
        .rename(
            columns={
                "statefips": "STATEFIP",
                "year": "YEAR",
                "month": "MONTH",
                "new_case_count": "monthly_cases",
            }
        )
    )
    monthly_covid["log_monthly_cases"] = np.log1p(monthly_covid["monthly_cases"])
    return monthly_covid


def prepare_monthly_stringency(oxcgrt_path: Path) -> pd.DataFrame:
    usecols = ["CountryCode", "Jurisdiction", "RegionCode", "Date", "StringencyIndex"]
    ox_df = pd.read_csv(oxcgrt_path, low_memory=False, usecols=usecols)
    ox_df = ox_df[
        (ox_df["CountryCode"] == "USA")
        & (ox_df["Jurisdiction"] == "STATE_WIDE")
        & ox_df["RegionCode"].notna()
    ].copy()
    ox_df["STATE_ABBR"] = ox_df["RegionCode"].str.split("_").str[-1]
    ox_df["STATEFIP"] = ox_df["STATE_ABBR"].map(STATE_ABBR_TO_FIPS)
    ox_df["Date"] = pd.to_datetime(ox_df["Date"], format="%Y%m%d", errors="coerce")
    ox_df["StringencyIndex"] = pd.to_numeric(ox_df["StringencyIndex"], errors="coerce")
    ox_df = ox_df.dropna(subset=["STATEFIP", "Date", "StringencyIndex"])
    ox_df["YEAR"] = ox_df["Date"].dt.year
    ox_df["MONTH"] = ox_df["Date"].dt.month
    monthly_stringency = (
        ox_df.groupby(["STATEFIP", "YEAR", "MONTH"], as_index=False)["StringencyIndex"]
        .mean()
        .rename(columns={"StringencyIndex": "avg_stringency"})
    )
    monthly_stringency["STATEFIP"] = monthly_stringency["STATEFIP"].astype(int)
    return monthly_stringency


def build_transition_panel(
    cps_df: pd.DataFrame,
    year: int,
    treat_fips: set[int],
    control_fips: set[int],
    policy_month: int,
    employment_mode: str,
) -> pd.DataFrame:
    included_states = set(treat_fips).union(control_fips)
    df_year = cps_df[(cps_df["YEAR"] == year) & (cps_df["STATEFIP"].isin(included_states))].copy()
    df_year["LowWage"] = df_year["IND"].apply(define_low_wage)
    df_year["TreatState"] = df_year["STATEFIP"].isin(treat_fips).astype(int)

    df_year.sort_values(["CPSIDP", "YEAR", "MONTH"], inplace=True)
    df_year["status_next_month"] = df_year.groupby("CPSIDP")["EMPSTAT"].shift(-1)

    employed_codes = EMPLOYMENT_OUTCOME_CODES[employment_mode]
    unemployed_df = df_year[df_year["EMPSTAT"].isin(UNEMPLOYED_CODES)].copy()
    unemployed_df["found_job"] = unemployed_df["status_next_month"].isin(employed_codes).astype(int)
    unemployed_df["Post"] = unemployed_df["MONTH"].between(policy_month, policy_month + 1).astype(int)

    panel = unemployed_df[unemployed_df["MONTH"].between(2, 8)].copy()
    panel = panel.dropna(subset=["found_job", "LNKFW1MWT", "LowWage", "AGE", "EDUC"])
    panel = panel[panel["LNKFW1MWT"] > 0].copy()
    panel["LowWage"] = panel["LowWage"].astype(int)
    panel["STATEFIP"] = panel["STATEFIP"].astype(int)
    panel["MONTH"] = panel["MONTH"].astype(int)
    panel["YEAR"] = panel["YEAR"].astype(int)
    return panel


def merge_controls(
    panel: pd.DataFrame,
    monthly_covid: pd.DataFrame,
    monthly_stringency: pd.DataFrame,
    control_spec: str,
) -> tuple[pd.DataFrame, list[str]]:
    merged = panel.copy()
    control_vars: list[str] = []

    if control_spec in {"covid", "covid_stringency"}:
        merged = merged.merge(monthly_covid, on=["STATEFIP", "YEAR", "MONTH"], how="left")
        merged["log_monthly_cases"] = merged["log_monthly_cases"].fillna(0)
        control_vars.append("log_monthly_cases")

    if control_spec == "covid_stringency":
        merged = merged.merge(monthly_stringency, on=["STATEFIP", "YEAR", "MONTH"], how="left")
        merged["avg_stringency"] = merged["avg_stringency"].fillna(0)
        control_vars.append("avg_stringency")

    return merged, control_vars


def fit_weighted_model(formula: str, df: pd.DataFrame):
    model = smf.wls(formula=formula, data=df, weights=df["LNKFW1MWT"])
    return model.fit(cov_type="cluster", cov_kwds={"groups": df["STATEFIP"]})


def run_ddd(panel: pd.DataFrame, control_vars: list[str]):
    formula_parts = ["found_job ~ TreatState * Post * LowWage", "C(STATEFIP)", "C(MONTH)"]
    if "avg_stringency" in control_vars:
        formula_parts.insert(1, "avg_stringency")
    if "log_monthly_cases" in control_vars:
        formula_parts.insert(1, "log_monthly_cases")
    formula = " + ".join(formula_parts)
    return fit_weighted_model(formula, panel)


def run_subgroup_did(panel: pd.DataFrame, control_vars: list[str], low_wage_value: int):
    subgroup = panel[panel["LowWage"] == low_wage_value].copy()
    formula_parts = ["found_job ~ TreatState * Post", "C(STATEFIP)", "C(MONTH)"]
    if "avg_stringency" in control_vars:
        formula_parts.insert(1, "avg_stringency")
    if "log_monthly_cases" in control_vars:
        formula_parts.insert(1, "log_monthly_cases")
    formula = " + ".join(formula_parts)
    return fit_weighted_model(formula, subgroup), subgroup


def run_subgroup_event_study(panel: pd.DataFrame, control_vars: list[str], low_wage_value: int):
    subgroup = panel[panel["LowWage"] == low_wage_value].copy()
    formula_parts = [
        "found_job ~ C(TreatState) * C(MONTH, Treatment(reference=6))",
        "C(STATEFIP)",
    ]
    if "avg_stringency" in control_vars:
        formula_parts.insert(1, "avg_stringency")
    if "log_monthly_cases" in control_vars:
        formula_parts.insert(1, "log_monthly_cases")
    formula = " + ".join(formula_parts)
    results = fit_weighted_model(formula, subgroup)
    return results, extract_event_study(results, subgroup_name="low_wage" if low_wage_value else "other_wage")


def run_ddd_event_study(panel: pd.DataFrame, control_vars: list[str]):
    formula_parts = [
        "found_job ~ C(TreatState) * C(MONTH, Treatment(reference=6)) * LowWage",
        "C(STATEFIP)",
    ]
    if "avg_stringency" in control_vars:
        formula_parts.insert(1, "avg_stringency")
    if "log_monthly_cases" in control_vars:
        formula_parts.insert(1, "log_monthly_cases")
    formula = " + ".join(formula_parts)
    results = fit_weighted_model(formula, panel)
    return results, extract_ddd_event_study(results)


def extract_ddd_event_study(results, policy_month: int = 7) -> pd.DataFrame:
    pattern = re.compile(
        r"C\(TreatState\)\[T\.1\]:C\(MONTH, Treatment\(reference=6\)\)\[T\.(\d+)\]:LowWage$",
        re.IGNORECASE,
    )
    rows = []
    for param_name in results.params.index:
        match = pattern.search(param_name)
        if not match:
            continue
        month = int(match.group(1))
        rows.append(
            {
                "subgroup": "ddd",
                "month": month,
                "coef": results.params[param_name],
                "stderr": results.bse[param_name],
                "pval": results.pvalues[param_name],
            }
        )
    event_df = pd.DataFrame(rows).sort_values("month")
    if 6 not in event_df["month"].values:
        event_df = pd.concat(
            [
                event_df,
                pd.DataFrame([{"subgroup": "ddd", "month": 6, "coef": 0.0, "stderr": 0.0, "pval": 1.0}]),
            ],
            ignore_index=True,
        ).sort_values("month")
    pretrend_mask = (event_df["month"] < policy_month) & (event_df["month"] != 6)
    pretrend_ok = bool((event_df.loc[pretrend_mask, "pval"] > 0.10).all())
    event_df["pretrend_ok"] = pretrend_ok
    return event_df.reset_index(drop=True)


def compute_cell_means(panel: pd.DataFrame) -> pd.DataFrame:
    return (
        panel.groupby(["TreatState", "Post", "LowWage"], as_index=False)["found_job"]
        .agg(mean="mean", size="size")
        .sort_values(["TreatState", "Post", "LowWage"])
    )


def extract_event_study(results, subgroup_name: str, policy_month: int = 7) -> pd.DataFrame:
    pattern = re.compile(
        r"C\(TreatState\)\[T\.1\]:C\(MONTH, Treatment\(reference=6\)\)\[T\.(\d+)\]$",
        re.IGNORECASE,
    )
    rows = []
    for param_name in results.params.index:
        match = pattern.search(param_name)
        if not match:
            continue
        month = int(match.group(1))
        rows.append(
            {
                "subgroup": subgroup_name,
                "month": month,
                "coef": results.params[param_name],
                "stderr": results.bse[param_name],
                "pval": results.pvalues[param_name],
            }
        )

    event_df = pd.DataFrame(rows).sort_values("month")
    if 6 not in event_df["month"].values:
        event_df = pd.concat(
            [
                event_df,
                pd.DataFrame(
                    [{"subgroup": subgroup_name, "month": 6, "coef": 0.0, "stderr": 0.0, "pval": 1.0}]
                ),
            ],
            ignore_index=True,
        ).sort_values("month")

    pretrend_mask = (event_df["month"] < policy_month) & (event_df["month"] != 6)
    pretrend_ok = bool((event_df.loc[pretrend_mask, "pval"] > 0.10).all())
    event_df["pretrend_ok"] = pretrend_ok
    return event_df.reset_index(drop=True)


def plot_event_study(event_df: pd.DataFrame, output_path: Path, title: str) -> None:
    plot_df = event_df.copy()
    plot_df["ci_low"] = plot_df["coef"] - 1.96 * plot_df["stderr"]
    plot_df["ci_high"] = plot_df["coef"] + 1.96 * plot_df["stderr"]

    plt.figure(figsize=(9, 5))
    plt.axhline(0, color="black", linewidth=1)
    plt.axvline(6.5, color="gray", linestyle="--", linewidth=1)
    plt.fill_between(plot_df["month"], plot_df["ci_low"], plot_df["ci_high"], alpha=0.25, color="steelblue")
    plt.plot(plot_df["month"], plot_df["coef"], marker="o", color="navy")
    plt.title(title)
    plt.xlabel("Calendar month")
    plt.ylabel("TreatState x Month coefficient")
    plt.xticks(sorted(plot_df["month"].unique()))
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def write_diagnostic_bundle(
    output_dir: Path,
    panel: pd.DataFrame,
    control_vars: list[str],
    year: int,
    sample_name: str,
    treatment_mode: str,
    employment_mode: str,
    bundle_name: str,
) -> list[dict]:
    bundle_dir = output_dir / bundle_name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    slug = f"{year}_{sample_name}_{treatment_mode}_{employment_mode}"

    compute_cell_means(panel).to_csv(bundle_dir / f"{slug}_cell_means.csv", index=False)

    subgroup_rows = []
    for low_wage_value, subgroup_label in [(0, "other_wage"), (1, "low_wage")]:
        did_res, subgroup_panel = run_subgroup_did(panel, control_vars, low_wage_value)
        subgroup_rows.append(
            {
                "year": year,
                "sample": sample_name,
                "treatment_mode": treatment_mode,
                "employment_mode": employment_mode,
                "control_spec": "covid_stringency",
                "bundle": bundle_name,
                "subgroup": subgroup_label,
                "obs": int(len(subgroup_panel)),
                "coef": float(did_res.params.get("TreatState:Post", np.nan)),
                "stderr": float(did_res.bse.get("TreatState:Post", np.nan)),
                "pval": float(did_res.pvalues.get("TreatState:Post", np.nan)),
            }
        )

        _, event_df = run_subgroup_event_study(panel, control_vars, low_wage_value)
        event_df.to_csv(bundle_dir / f"{slug}_{subgroup_label}_event_study.csv", index=False)
        plot_event_study(
            event_df,
            bundle_dir / f"{slug}_{subgroup_label}_event_study.png",
            title=f"{subgroup_label.replace('_', ' ').title()} Event Study ({year}, {sample_name})",
        )

    _, ddd_event_df = run_ddd_event_study(panel, control_vars)
    ddd_event_df.to_csv(bundle_dir / f"{slug}_ddd_event_study.csv", index=False)
    plot_event_study(
        ddd_event_df,
        bundle_dir / f"{slug}_ddd_event_study.png",
        title=f"DDD Event Study ({year}, {sample_name})",
    )
    pd.DataFrame(subgroup_rows).to_csv(bundle_dir / f"{slug}_subgroup_did.csv", index=False)
    return subgroup_rows


def save_markdown_summary(
    output_dir: Path,
    ddd_rows: list[dict],
    subgroup_rows: list[dict],
    metadata: dict,
) -> None:
    ddd_df = pd.DataFrame(ddd_rows)
    subgroup_df = pd.DataFrame(subgroup_rows)
    placebo_flags = ddd_df[
        (ddd_df["year"] == metadata["placebo_year"]) & (ddd_df["pval"] < 0.10)
    ].copy()

    lines = [
        "# Holzer-Style Robustness Summary",
        "",
        "Generated by `scripts/holzer_style_robustness.py`.",
        "",
        "## Metadata",
        "",
        f"- Treatment modes run: `{', '.join(metadata['treatment_modes'])}`",
        f"- Employment modes run: `{', '.join(metadata['employment_modes'])}`",
        f"- Analysis year: `{metadata['analysis_year']}`",
        f"- Placebo year: `{metadata['placebo_year']}`",
        "",
        "## DDD Grid",
        "",
    ]

    if not ddd_df.empty:
        lines.append("```text")
        lines.append(ddd_df.to_string(index=False))
        lines.append("```")
    else:
        lines.append("No DDD results generated.")

    lines.extend(["", "## Subgroup DiD", ""])
    if not subgroup_df.empty:
        lines.append("```text")
        lines.append(subgroup_df.to_string(index=False))
        lines.append("```")
    else:
        lines.append("No subgroup DiD results generated.")

    lines.extend(["", "## Placebo Flags", ""])
    if not placebo_flags.empty:
        lines.append("```text")
        lines.append(placebo_flags.to_string(index=False))
        lines.append("```")
    else:
        lines.append("No placebo specifications crossed p < 0.10.")

    (output_dir / "summary.md").write_text("\n".join(lines) + "\n")


def run_smoke_test(
    cps_df: pd.DataFrame,
    treat_fips: set[int],
    monthly_covid: pd.DataFrame,
    monthly_stringency: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    control_fips = set(cps_df.loc[cps_df["YEAR"] == args.analysis_year, "STATEFIP"].dropna().astype(int)) - treat_fips
    employment_mode = EMPLOYMENT_MODES[0] if args.employment_mode == "both" else args.employment_mode
    panel = build_transition_panel(
        cps_df,
        args.analysis_year,
        treat_fips,
        control_fips,
        args.policy_month,
        employment_mode,
    )
    panel = apply_sample_filter(panel, "all_ages")
    merged, control_vars = merge_controls(panel, monthly_covid, monthly_stringency, "covid_stringency")

    summary = {
        "analysis_year": args.analysis_year,
        "treatment_mode": args.treatment_mode,
        "employment_mode": employment_mode,
        "treat_state_count": len(treat_fips),
        "control_state_count": len(control_fips),
        "panel_rows": len(panel),
        "panel_rows_with_controls": len(merged),
        "control_vars": control_vars,
        "columns_available": sorted(merged.columns.tolist()),
    }
    print(json.dumps(summary, indent=2))


def main() -> None:
    args = parse_args()
    cps_path = Path(args.cps_path).expanduser()
    policy_path = Path(args.policy_path).expanduser()
    covid_path = Path(args.covid_path).expanduser()
    oxcgrt_path = Path(args.oxcgrt_path).expanduser()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cps_df = load_cps(cps_path)
    monthly_covid = prepare_monthly_covid(covid_path)
    monthly_stringency = prepare_monthly_stringency(oxcgrt_path)
    summarize_empstat_distribution(cps_df, output_dir)

    treatment_modes = TREATMENT_MODES if args.treatment_mode == "both" else [args.treatment_mode]
    employment_modes = EMPLOYMENT_MODES if args.employment_mode == "both" else [args.employment_mode]

    treatment_state_rows = []
    for treatment_mode in treatment_modes:
        treat_fips = sorted(load_treatment_states(policy_path, treatment_mode))
        if not treat_fips:
            raise ValueError(f"No treatment states found under treatment mode: {treatment_mode}")
        treatment_state_rows.append(
            {
                "treatment_mode": treatment_mode,
                "treat_state_count": len(treat_fips),
                "treat_states": ",".join(str(x) for x in treat_fips),
            }
        )
    pd.DataFrame(treatment_state_rows).to_csv(output_dir / "treatment_state_sets.csv", index=False)

    if args.smoke_test:
        first_treat_fips = set(load_treatment_states(policy_path, treatment_modes[0]))
        run_smoke_test(cps_df, first_treat_fips, monthly_covid, monthly_stringency, args)
        return

    ddd_rows: list[dict] = []
    subgroup_rows: list[dict] = []
    available_states_by_year = {
        year: set(cps_df.loc[cps_df["YEAR"] == year, "STATEFIP"].dropna().astype(int))
        for year in [args.analysis_year, args.placebo_year]
    }

    for treatment_mode in treatment_modes:
        treat_fips = set(load_treatment_states(policy_path, treatment_mode))
        control_fips_by_year = {
            args.analysis_year: available_states_by_year[args.analysis_year] - treat_fips,
            args.placebo_year: available_states_by_year[args.placebo_year] - treat_fips,
        }

        for employment_mode in employment_modes:
            for year in [args.analysis_year, args.placebo_year]:
                base_panel = build_transition_panel(
                    cps_df,
                    year,
                    treat_fips,
                    control_fips_by_year[year],
                    args.policy_month,
                    employment_mode,
                )

                for sample_spec in SAMPLE_SPECS:
                    sample_panel = apply_sample_filter(base_panel, sample_spec.name)
                    if sample_panel.empty:
                        continue

                    for control_spec in CONTROL_SPECS:
                        merged_panel, control_vars = merge_controls(
                            sample_panel,
                            monthly_covid,
                            monthly_stringency,
                            control_spec,
                        )
                        if merged_panel.empty:
                            continue

                        ddd_res = run_ddd(merged_panel, control_vars)
                        term = "TreatState:Post:LowWage"
                        if term not in ddd_res.params:
                            continue

                        row = {
                            "year": year,
                            "sample": sample_spec.name,
                            "treatment_mode": treatment_mode,
                            "employment_mode": employment_mode,
                            "control_spec": control_spec,
                            "obs": int(len(merged_panel)),
                            "coef": float(ddd_res.params[term]),
                            "stderr": float(ddd_res.bse[term]),
                            "pval": float(ddd_res.pvalues[term]),
                        }
                        ddd_rows.append(row)

                        if (
                            year == args.analysis_year
                            and sample_spec.name == "all_ages"
                            and control_spec == "covid_stringency"
                        ):
                            subgroup_rows.extend(
                                write_diagnostic_bundle(
                                    output_dir=output_dir,
                                    panel=merged_panel,
                                    control_vars=control_vars,
                                    year=year,
                                    sample_name=sample_spec.name,
                                    treatment_mode=treatment_mode,
                                    employment_mode=employment_mode,
                                    bundle_name="analysis_diagnostics",
                                )
                            )

                        if (
                            year == args.placebo_year
                            and control_spec == "covid_stringency"
                            and row["pval"] < 0.10
                        ):
                            subgroup_rows.extend(
                                write_diagnostic_bundle(
                                    output_dir=output_dir,
                                    panel=merged_panel,
                                    control_vars=control_vars,
                                    year=year,
                                    sample_name=sample_spec.name,
                                    treatment_mode=treatment_mode,
                                    employment_mode=employment_mode,
                                    bundle_name="placebo_diagnostics",
                                )
                            )

    pd.DataFrame(ddd_rows).to_csv(output_dir / "ddd_robustness_grid.csv", index=False)
    pd.DataFrame(subgroup_rows).to_csv(output_dir / "subgroup_did_summary.csv", index=False)

    save_markdown_summary(
        output_dir,
        ddd_rows=ddd_rows,
        subgroup_rows=subgroup_rows,
        metadata={
            "treatment_modes": treatment_modes,
            "employment_modes": employment_modes,
            "analysis_year": args.analysis_year,
            "placebo_year": args.placebo_year,
        },
    )


if __name__ == "__main__":
    main()
