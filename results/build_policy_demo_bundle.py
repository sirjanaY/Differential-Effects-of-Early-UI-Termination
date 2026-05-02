from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DATA = ROOT / "web" / "data"

HOLZER_PANEL = ROOT / "holzer_style_panel.csv"
SUBGROUP_DID = ROOT / "data" / "outputs" / "holzer_style_robustness" / "subgroup_did_summary.csv"
DDD_GRID = ROOT / "data" / "outputs" / "holzer_style_robustness" / "ddd_robustness_grid.csv"
LOW_WAGE_EVENT = ROOT / "data" / "outputs" / "holzer_style_robustness" / "low_wage_event_study_2021.csv"
OTHER_WAGE_EVENT = ROOT / "data" / "outputs" / "holzer_style_robustness" / "other_wage_event_study_2021.csv"
TREATMENT_SETS = ROOT / "data" / "outputs" / "holzer_style_robustness" / "treatment_state_sets.csv"
CELL_MEANS_JUNE = (
    ROOT
    / "data"
    / "outputs"
    / "holzer_style_robustness"
    / "analysis_diagnostics"
    / "2021_all_ages_june_only_any_employed_cell_means.csv"
)
CELL_MEANS_ALL = (
    ROOT
    / "data"
    / "outputs"
    / "holzer_style_robustness"
    / "analysis_diagnostics"
    / "2021_all_ages_all_early_exits_any_employed_cell_means.csv"
)
SLICE_DDD = ROOT / "data" / "outputs" / "main_robustness_suite" / "slice_ddd_corrected.csv"


STATE_NAMES = {
    1: "Alabama",
    2: "Alaska",
    4: "Arizona",
    5: "Arkansas",
    6: "California",
    8: "Colorado",
    9: "Connecticut",
    10: "Delaware",
    11: "District of Columbia",
    12: "Florida",
    13: "Georgia",
    15: "Hawaii",
    16: "Idaho",
    17: "Illinois",
    18: "Indiana",
    19: "Iowa",
    20: "Kansas",
    21: "Kentucky",
    22: "Louisiana",
    23: "Maine",
    24: "Maryland",
    25: "Massachusetts",
    26: "Michigan",
    27: "Minnesota",
    28: "Mississippi",
    29: "Missouri",
    30: "Montana",
    31: "Nebraska",
    32: "Nevada",
    33: "New Hampshire",
    34: "New Jersey",
    35: "New Mexico",
    36: "New York",
    37: "North Carolina",
    38: "North Dakota",
    39: "Ohio",
    40: "Oklahoma",
    41: "Oregon",
    42: "Pennsylvania",
    44: "Rhode Island",
    45: "South Carolina",
    46: "South Dakota",
    47: "Tennessee",
    48: "Texas",
    49: "Utah",
    50: "Vermont",
    51: "Virginia",
    53: "Washington",
    54: "West Virginia",
    55: "Wisconsin",
    56: "Wyoming",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def to_float(value: str) -> float | None:
    if value in {"", ".", None}:
        return None
    return float(value)


def build_monthly_rates(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[int, str, int], dict[str, float]] = defaultdict(
        lambda: {"sum": 0.0, "count": 0.0}
    )
    for row in rows:
        month = int(row["MONTH"])
        subgroup = "low_wage" if int(row["LowWage"]) == 1 else "other_wage"
        treated = int(row["TreatState"])
        key = (month, subgroup, treated)
        grouped[key]["sum"] += float(row["found_job"])
        grouped[key]["count"] += 1.0

    monthly = []
    for subgroup in ("low_wage", "other_wage"):
        for month in range(1, 13):
            control = grouped[(month, subgroup, 0)]
            treated = grouped[(month, subgroup, 1)]
            monthly.append(
                {
                    "month": month,
                    "subgroup": subgroup,
                    "control_rate": round(control["sum"] / control["count"], 4) if control["count"] else None,
                    "treated_rate": round(treated["sum"] / treated["count"], 4) if treated["count"] else None,
                    "control_n": int(control["count"]),
                    "treated_n": int(treated["count"]),
                }
            )
    return monthly


def age_band(age: int) -> str:
    if age <= 24:
        return "18_24"
    if age <= 34:
        return "25_34"
    if age <= 54:
        return "35_54"
    return "55_plus"


def education_band(code: int) -> str:
    if code <= 73:
        return "hs_or_less"
    if code < 111:
        return "some_college"
    return "bachelors_plus"


def race_band(race: int, hispan: int) -> str:
    if hispan != 0:
        return "hispanic"
    if race == 100:
        return "white_non_hispanic"
    if race == 200:
        return "black_non_hispanic"
    return "other_non_hispanic"


def build_profile_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    payload = []
    for row in rows:
        age = int(float(row["AGE"]))
        educ = int(float(row["EDUC"]))
        race = int(float(row["RACE"]))
        hispan = int(float(row["HISPAN"]))
        payload.append(
            {
                "statefip": int(float(row["STATEFIP"])),
                "month": int(row["MONTH"]),
                "post": int(row["Post"]),
                "found_job": int(row["found_job"]),
                "low_wage": int(row["LowWage"]),
                "sex": "men" if int(row["SEX"]) == 1 else "women",
                "age_band": age_band(age),
                "education_band": education_band(educ),
                "race_band": race_band(race, hispan),
                "weight": float(row["WTFINL"]),
            }
        )
    return payload


def build_treatment_sets(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    payload = []
    for row in rows:
        states = [int(part) for part in row["treat_states"].split(",")]
        payload.append(
            {
                "treatment_mode": row["treatment_mode"],
                "treat_state_count": int(row["treat_state_count"]),
                "states": [{"fips": fips, "name": STATE_NAMES.get(fips, str(fips))} for fips in states],
            }
        )
    return payload


def build_cell_means(path: Path, treatment_mode: str) -> list[dict[str, object]]:
    rows = read_csv(path)
    payload = []
    for row in rows:
        payload.append(
            {
                "treatment_mode": treatment_mode,
                "treated": bool(int(row["TreatState"])),
                "post": bool(int(row["Post"])),
                "subgroup": "low_wage" if int(row["LowWage"]) == 1 else "other_wage",
                "mean": float(row["mean"]),
                "size": int(row["size"]),
            }
        )
    return payload


def serialize_numeric_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    payload = []
    for row in rows:
        parsed: dict[str, object] = {}
        for key, value in row.items():
            if value is None:
                parsed[key] = value
                continue
            value = value.strip()
            if value == "":
                parsed[key] = value
                continue
            try:
                number = float(value)
                parsed[key] = int(number) if number.is_integer() else number
            except ValueError:
                parsed[key] = value
        payload.append(parsed)
    return payload


def main() -> None:
    holzer_rows = read_csv(HOLZER_PANEL)
    subgroup_rows = read_csv(SUBGROUP_DID)
    ddd_rows = read_csv(DDD_GRID)
    low_event_rows = read_csv(LOW_WAGE_EVENT)
    other_event_rows = read_csv(OTHER_WAGE_EVENT)
    treatment_rows = read_csv(TREATMENT_SETS)
    slice_rows = read_csv(SLICE_DDD)

    bundle = {
        "meta": {
            "title": "Benefit Exit Lab",
            "subtitle": "A localhost policy explorer for the 2021 early termination shock.",
            "source_note": "Built from repo-local CPS-derived panels and saved robustness outputs.",
        },
        "monthly_rates": build_monthly_rates(holzer_rows),
        "profile_rows": build_profile_rows(holzer_rows),
        "subgroup_did": serialize_numeric_rows(subgroup_rows),
        "ddd_grid": serialize_numeric_rows(ddd_rows),
        "event_studies": {
            "low_wage": serialize_numeric_rows(low_event_rows),
            "other_wage": serialize_numeric_rows(other_event_rows),
        },
        "treatment_sets": build_treatment_sets(treatment_rows),
        "cell_means": build_cell_means(CELL_MEANS_JUNE, "june_only")
        + build_cell_means(CELL_MEANS_ALL, "all_early_exits"),
        "slice_ddd": serialize_numeric_rows(slice_rows),
    }

    WEB_DATA.mkdir(parents=True, exist_ok=True)
    output_path = WEB_DATA / "policy_demo_bundle.json"
    output_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
