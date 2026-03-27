#!/usr/bin/env python3
"""Run corrected subgroup-slice DDD models with consistent timing logic."""

from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import main_claim_robustness_suite as core


OUT = Path("/Users/jomus/Code/capstone/data/outputs/main_robustness_suite")


def apply_slice(df: pd.DataFrame, name: str) -> pd.DataFrame:
    if name == "all_ages":
        return df.copy()
    if name == "prime_age":
        return df[df["AGE"].between(25, 54)].copy()
    if name == "no_college":
        return df[df["EDUC"] <= 110].copy()
    if name == "prime_age_no_college":
        return df[df["AGE"].between(25, 54) & (df["EDUC"] <= 110)].copy()
    if name == "young_18_24":
        return df[df["AGE"].between(18, 24)].copy()
    if name == "older_55_plus":
        return df[df["AGE"] >= 55].copy()
    raise ValueError(name)


def run() -> pd.DataFrame:
    cps = core.load_cps(core.CPS_PATH)
    cps, _ = core.attach_income_if_valid(cps, core.CPS_INCOME_PATH)
    trans = core.add_low_wage_defs(core.add_transitions(cps, adjacent_only=True))
    treat_dates = core.load_treatment_dates(core.POLICY_PATH)
    m_covid = core.prepare_monthly_covid(core.COVID_PATH)
    m_str = core.prepare_monthly_stringency(core.OXCGRT_PATH)

    slice_names = [
        "all_ages",
        "prime_age",
        "no_college",
        "prime_age_no_college",
        "young_18_24",
        "older_55_plus",
    ]

    rows: list[dict] = []
    june_states = set(treat_dates.loc[treat_dates["treat_month"] == 6, "STATEFIP"].tolist())

    for s in slice_names:
        sub = apply_slice(trans[trans["YEAR"] == 2021].copy(), s)
        # corrected state-specific
        p_state = core.build_panel(
            sub, treat_dates, m_covid, m_str, 2021, "state_specific", "LowWage_ind"
        )
        r_state = core.fit_main(p_state)
        rows.append(
            {
                "slice": s,
                "spec": "state_specific_corrected",
                "coef": r_state.coef,
                "stderr": r_state.stderr,
                "pval": r_state.pval,
                "nobs": r_state.nobs,
            }
        )

        # holzer-aligned june vs maintainers
        p_h = core.build_panel(
            sub, treat_dates, m_covid, m_str, 2021, "common_july", "LowWage_ind"
        )
        avail_states = set(p_h["STATEFIP"].dropna().astype(int).unique().tolist())
        maintain_states = avail_states - set(treat_dates["STATEFIP"].tolist())
        p_h = p_h[p_h["STATEFIP"].isin(june_states.union(maintain_states))].copy()
        p_h["TreatState"] = p_h["STATEFIP"].isin(june_states).astype(int)
        p_h["Post"] = p_h["MONTH"].between(7, 8).astype(int)
        r_h = core.fit_main(p_h)
        rows.append(
            {
                "slice": s,
                "spec": "holzer_june_vs_maintainers",
                "coef": r_h.coef,
                "stderr": r_h.stderr,
                "pval": r_h.pval,
                "nobs": r_h.nobs,
            }
        )

    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    out = run()
    out.to_csv(OUT / "slice_ddd_corrected.csv", index=False)
    md = [
        "# Corrected Slice DDD",
        "",
        "```text",
        out.to_string(index=False),
        "```",
    ]
    (OUT / "slice_ddd_corrected.md").write_text("\n".join(md) + "\n")
    print(f"Wrote {OUT / 'slice_ddd_corrected.csv'}")
    print(f"Wrote {OUT / 'slice_ddd_corrected.md'}")


if __name__ == "__main__":
    main()
