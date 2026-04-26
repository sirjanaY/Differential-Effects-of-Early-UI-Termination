from __future__ import annotations

import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "outputs" / "streamlit"

DDD_GRID = ROOT / "data" / "outputs" / "holzer_style_robustness" / "ddd_robustness_grid.csv"
STATE_SUBGROUP_DD = ROOT / "data" / "outputs" / "holzer_style_robustness" / "subgroup_did_summary.csv"
TREATMENT_SETS = ROOT / "data" / "outputs" / "holzer_style_robustness" / "treatment_state_sets.csv"
ROBUSTNESS_CHECKS = ROOT / "data" / "outputs" / "main_robustness_suite" / "robustness_checks.csv"
SLICE_DDD = ROOT / "data" / "outputs" / "main_robustness_suite" / "slice_ddd_corrected.csv"
SUBGROUP_SLICES = ROOT / "data" / "outputs" / "main_robustness_suite" / "subgroup_dd_slices.csv"
COUNTY_HETEROGENEITY = ROOT / "data" / "outputs" / "county_aside" / "heterogeneity_results.csv"
COUNTY_MERGE_DIAGNOSTICS = ROOT / "data" / "outputs" / "county_aside" / "merge_diagnostics.csv"
COUNTY_PANEL = ROOT / "data" / "outputs" / "county_aside" / "panel_with_county_covars_2021.csv"
ANALYSIS_DIAGNOSTICS = ROOT / "data" / "outputs" / "holzer_style_robustness" / "analysis_diagnostics"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_value(value: str):
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return ""
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except ValueError:
        return value


def serialize_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [{key: parse_value(value) for key, value in row.items()} for row in rows]


def ci_bounds(coef: float | int | None, stderr: float | int | None) -> tuple[float | None, float | None]:
    if coef is None or stderr is None:
        return None, None
    if not isinstance(coef, (int, float)) or not isinstance(stderr, (int, float)):
        return None, None
    if not math.isfinite(coef) or not math.isfinite(stderr):
        return None, None
    return coef - 1.96 * stderr, coef + 1.96 * stderr


def add_intervals(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    payload = []
    for row in rows:
        new_row = dict(row)
        low, high = ci_bounds(new_row.get("coef"), new_row.get("stderr"))
        new_row["ci_low"] = low
        new_row["ci_high"] = high
        payload.append(new_row)
    return payload


def build_forest_rows(subgroup_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    payload = []
    for index, row in enumerate(subgroup_rows, start=1):
        low, high = ci_bounds(row["coef"], row["stderr"])
        subgroup = str(row["subgroup"])
        if "Food/Retail" in subgroup or "industries" in subgroup:
            group = "industry"
        elif "workers" in subgroup or "age" in subgroup or "retirement" in subgroup:
            group = "age"
        else:
            group = "other"
        payload.append(
            {
                "panel": "main_subgroup_slices",
                "group": group,
                "subgroup": subgroup,
                "label": subgroup,
                "year": row["year"],
                "coef": row["coef"],
                "stderr": row["stderr"],
                "pval": row["pval"],
                "ci_low": low,
                "ci_high": high,
                "nobs": row["nobs"],
                "order": index,
                "note": row.get("note", ""),
            }
        )
    return payload


def build_event_study_rows() -> list[dict[str, object]]:
    specs = [
        ("june_only", "any_employed"),
        ("june_only", "at_work_only"),
        ("all_early_exits", "any_employed"),
        ("all_early_exits", "at_work_only"),
    ]
    series_map = {
        "ddd": "ddd_event_study",
        "low_wage": "low_wage_event_study",
        "other_wage": "other_wage_event_study",
    }
    payload: list[dict[str, object]] = []
    for treatment_mode, employment_mode in specs:
        for series_key, suffix in series_map.items():
            path = ANALYSIS_DIAGNOSTICS / f"2021_all_ages_{treatment_mode}_{employment_mode}_{suffix}.csv"
            rows = serialize_rows(read_csv(path))
            for row in rows:
                low, high = ci_bounds(row["coef"], row["stderr"])
                payload.append(
                    {
                        "year": 2021,
                        "sample": "all_ages",
                        "treatment_mode": treatment_mode,
                        "employment_mode": employment_mode,
                        "series_key": series_key,
                        "month": row["month"],
                        "coef": row["coef"],
                        "stderr": row["stderr"],
                        "pval": row["pval"],
                        "pretrend_ok": row["pretrend_ok"],
                        "ci_low": low,
                        "ci_high": high,
                    }
                )
    return payload


def build_county_panel_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    keep = [
        "date",
        "ym",
        "STATEFIP",
        "COUNTYFIP",
        "FIPS",
        "emp_incq1",
        "Policy_DiD",
        "covid_severity",
        "median_household_income_usd",
        "family_poverty_rate_pct",
        "unemployment_rate_pct",
        "economic_vulnerability_z",
        "median_household_income_usd_z",
        "family_poverty_rate_pct_z",
        "unemployment_rate_pct_z",
    ]
    payload = []
    for row in rows:
        payload.append({key: parse_value(row[key]) for key in keep})
    return payload


def main() -> None:
    ddd_grid = add_intervals(serialize_rows(read_csv(DDD_GRID)))
    state_subgroup_dd = add_intervals(serialize_rows(read_csv(STATE_SUBGROUP_DD)))
    robustness_checks = add_intervals(serialize_rows(read_csv(ROBUSTNESS_CHECKS)))
    slice_ddd = add_intervals(serialize_rows(read_csv(SLICE_DDD)))
    subgroup_slices = add_intervals(serialize_rows(read_csv(SUBGROUP_SLICES)))
    county_heterogeneity = add_intervals(serialize_rows(read_csv(COUNTY_HETEROGENEITY)))
    county_merge = serialize_rows(read_csv(COUNTY_MERGE_DIAGNOSTICS))
    county_panel = build_county_panel_rows(read_csv(COUNTY_PANEL))
    treatment_sets = serialize_rows(read_csv(TREATMENT_SETS))

    dataset = {
        "meta": {
            "title": "DDD Streamlit Dataset",
            "description": "Deployment-ready dataset for interactive state and county DDD views.",
            "source_note": "Combines main state-level DDD outputs, robustness tables, event-study series, and county-side auxiliary outputs.",
        },
        "state_ddd_grid": ddd_grid,
        "state_subgroup_dd": state_subgroup_dd,
        "main_robustness_checks": robustness_checks,
        "main_slice_ddd": slice_ddd,
        "main_subgroup_slices": subgroup_slices,
        "forest_plot_rows": build_forest_rows(subgroup_slices),
        "event_study_rows": build_event_study_rows(),
        "treatment_sets": treatment_sets,
        "county_heterogeneity": county_heterogeneity,
        "county_merge_diagnostics": county_merge,
        "county_panel_rows": county_panel,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "ddd_inter.json"
    out_path.write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
