# County Aside: Heterogeneity Results

This is an auxiliary county-level heterogeneity check.
It does not replace the main CPS/state-level causal design.

## Coverage

```text
                  covariate  rows_available  counties_available  states_available
median_household_income_usd            9024                 752                51
    family_poverty_rate_pct            9024                 752                51
      unemployment_rate_pct            9024                 752                51
   economic_vulnerability_z            9024                 752                51
```

## Coefficients

```text
                                    model                                     term      coef   stderr     pval  nobs
                       baseline_county_fe                               Policy_DiD -0.020063 0.011964 0.093552  9036
heterogeneity_median_household_income_usd Policy_DiD:median_household_income_usd_z  0.001676 0.010320 0.870956  9024
    heterogeneity_family_poverty_rate_pct     Policy_DiD:family_poverty_rate_pct_z -0.000527 0.012546 0.966494  9024
      heterogeneity_unemployment_rate_pct       Policy_DiD:unemployment_rate_pct_z  0.001164 0.013064 0.928992  9024
   heterogeneity_economic_vulnerability_z      Policy_DiD:economic_vulnerability_z -0.000600 0.011641 0.958870  9024
```

## Notes

- Sample restricted to 2021 monthly observations in the county panel.
- Specification includes county fixed effects and year-month fixed effects.
- Standard errors clustered at state level.
- Interaction term is `Policy_DiD x standardized county covariate`.
