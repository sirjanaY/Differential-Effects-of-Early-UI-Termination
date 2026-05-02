#!/usr/bin/env python3
"""County-level heterogeneity aside for the capstone.

This is intentionally an auxiliary analysis. It does not replace the main
state/CPS identification strategy. It uses county covariates from HDPulse only
to test whether county baseline conditions correlate with larger/smaller
Policy_DiD effects in the existing county panel.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


REPO_ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = REPO_ROOT / "twfe_panel_county_data.csv"
COVAR_PATH = REPO_ROOT / "data" / "processed" / "county_hdpulse_covariates_2019_2023.csv"
OUTPUT_DIR = REPO_ROOT / "data" / "outputs" / "county_aside"

COVARIATES = [
    "median_household_income_usd",
    "family_poverty_rate_pct",
    "unemployment_rate_pct",
    "economic_vulnerability_z",
]


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = pd.read_csv(PANEL_PATH)
    covars = pd.read_csv(COVAR_PATH, dtype={"FIPS": "string"})
    return panel, covars


def prep_panel(panel: pd.DataFrame, covars: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel = panel.dropna(subset=["date", "STATEFIP", "COUNTYFIP", "emp_incq1", "Policy_DiD"])

    # Keep 2021 to align with the main policy shock window.
    panel = panel[(panel["date"] >= "2021-01-01") & (panel["date"] <= "2021-12-31")].copy()
    panel["COUNTYFIP"] = pd.to_numeric(panel["COUNTYFIP"], errors="coerce").astype("Int64")
    panel = panel.dropna(subset=["COUNTYFIP"]).copy()
    panel["COUNTYFIP"] = panel["COUNTYFIP"].astype(int)
    panel["FIPS"] = panel["COUNTYFIP"].astype(str).str.zfill(5)
    panel["STATEFIP"] = pd.to_numeric(panel["STATEFIP"], errors="coerce").astype("Int64")
    panel = panel.dropna(subset=["STATEFIP"]).copy()
    panel["STATEFIP"] = panel["STATEFIP"].astype(int)
    panel["ym"] = panel["date"].dt.to_period("M").astype(str)

    keep = ["FIPS"] + COVARIATES
    merged = panel.merge(covars[keep], on="FIPS", how="left")

    # Standardize time-invariant covariates for interpretable interactions.
    for col in COVARIATES:
        x = pd.to_numeric(merged[col], errors="coerce")
        merged[col] = x
        std = x.std(ddof=0)
        zcol = col if col.endswith("_z") else f"{col}_z"
        merged[zcol] = (x - x.mean()) / std if std and np.isfinite(std) and std > 0 else np.nan

    return merged


def fit_clustered(formula: str, df: pd.DataFrame):
    model = smf.ols(formula=formula, data=df)
    return model.fit(cov_type="cluster", cov_kwds={"groups": df["STATEFIP"]})


def run_models(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    merge_rows = []

    base_formula = "emp_incq1 ~ Policy_DiD + covid_severity + C(COUNTYFIP) + C(ym)"
    base_df = df.dropna(subset=["emp_incq1", "Policy_DiD", "covid_severity"]).copy()
    base_fit = fit_clustered(base_formula, base_df)
    rows.append(
        {
            "model": "baseline_county_fe",
            "term": "Policy_DiD",
            "coef": float(base_fit.params.get("Policy_DiD", np.nan)),
            "stderr": float(base_fit.bse.get("Policy_DiD", np.nan)),
            "pval": float(base_fit.pvalues.get("Policy_DiD", np.nan)),
            "nobs": int(base_fit.nobs),
        }
    )

    for col in COVARIATES:
        zcol = col if col.endswith("_z") else f"{col}_z"
        sub = df.dropna(subset=["emp_incq1", "Policy_DiD", "covid_severity", zcol]).copy()
        merge_rows.append(
            {
                "covariate": col,
                "rows_available": int(len(sub)),
                "counties_available": int(sub["COUNTYFIP"].nunique()),
                "states_available": int(sub["STATEFIP"].nunique()),
            }
        )
        if sub.empty:
            continue

        formula = (
            f"emp_incq1 ~ Policy_DiD + Policy_DiD:{zcol} + covid_severity + C(COUNTYFIP) + C(ym)"
        )
        fit = fit_clustered(formula, sub)
        term = f"Policy_DiD:{zcol}"
        rows.append(
            {
                "model": f"heterogeneity_{col}",
                "term": term,
                "coef": float(fit.params.get(term, np.nan)),
                "stderr": float(fit.bse.get(term, np.nan)),
                "pval": float(fit.pvalues.get(term, np.nan)),
                "nobs": int(fit.nobs),
            }
        )

    return pd.DataFrame(rows), pd.DataFrame(merge_rows)


def write_summary(results: pd.DataFrame, merge_diag: pd.DataFrame, outdir: Path) -> None:
    lines = [
        "# County Aside: Heterogeneity Results",
        "",
        "This is an auxiliary county-level heterogeneity check.",
        "It does not replace the main CPS/state-level causal design.",
        "",
        "## Coverage",
        "",
        "```text",
        merge_diag.to_string(index=False),
        "```",
        "",
        "## Coefficients",
        "",
        "```text",
        results.to_string(index=False),
        "```",
        "",
        "## Notes",
        "",
        "- Sample restricted to 2021 monthly observations in the county panel.",
        "- Specification includes county fixed effects and year-month fixed effects.",
        "- Standard errors clustered at state level.",
        "- Interaction term is `Policy_DiD x standardized county covariate`.",
    ]
    (outdir / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel, covars = load_inputs()
    merged = prep_panel(panel, covars)
    results, merge_diag = run_models(merged)

    merged.to_csv(OUTPUT_DIR / "panel_with_county_covars_2021.csv", index=False)
    results.to_csv(OUTPUT_DIR / "heterogeneity_results.csv", index=False)
    merge_diag.to_csv(OUTPUT_DIR / "merge_diagnostics.csv", index=False)
    write_summary(results, merge_diag, OUTPUT_DIR)

    print(f"Wrote: {OUTPUT_DIR / 'heterogeneity_results.csv'}")
    print(f"Wrote: {OUTPUT_DIR / 'merge_diagnostics.csv'}")
    print(f"Wrote: {OUTPUT_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
