# XAI — Model Explainability & Robustness Analysis  
## Differential Effects of Early UI Termination

This section provides a structured explanation of the model’s results through robustness checks, causal validation, and subgroup analysis.

The goal is not only to report a statistical effect, but to demonstrate that the finding is **stable, causally valid, and interpretable across multiple dimensions**.

---

## Overview of Explainability Framework

In causal inference, a single coefficient is not sufficient to establish credibility. Instead, we evaluate the result across five dimensions:

- Global robustness across model specifications  
- Sensitivity to individual states  
- Subgroup heterogeneity  
- Validity of identifying assumptions  
- Potential influence of external economic factors  

Each figure below corresponds to one of these validation layers.

---

## 1. Treatment Structure Across States

![Treatment Map](images/figure_1_treatment_map.png)

This map illustrates the geographic distribution of treatment across U.S. states.

States that implemented early UI termination policies are shown as treated, while others serve as controls.

This variation is the foundation of the causal identification strategy. Without clear separation between treated and control states, the DDD design would not be valid.

---

## 2. Parallel Trends Validation — Event Study

![Event Study](images/figure_6_event_study_DDD_State_Event_Study_(2021,_LowWage_vs_Other-Wage).png)

A key requirement for causal inference is the **parallel trends assumption**, which states that treated and control groups should follow similar trends before the policy change.

This event study evaluates that assumption.

Before July 2021, trends between groups are flat and statistically indistinguishable. After the policy is implemented, a clear divergence emerges.

This pattern supports a causal interpretation: the change aligns precisely with the policy timing rather than pre-existing trends.

---

## 3. Main Policy Effect

![Main Effect](images/est_policy_workerGroup.png)

This figure presents the estimated effect of early UI termination on employment outcomes across worker groups.

The results show a consistent negative effect on low-wage workers relative to higher-wage workers.

Importantly, the estimate remains stable across specifications, suggesting that the result is not sensitive to modeling choices but reflects a real underlying relationship.

---

## 4. Leave-One-Out Robustness — Sensitivity to States

![LOO Robustness](images/LOO_Robustness_Check.png)

To test whether the result is driven by any single state, a leave-one-out robustness analysis is conducted.

The model is repeatedly re-estimated, excluding one treatment state at a time.

Across all iterations:
- The effect remains negative  
- The magnitude is stable  
- No single state drives the result  

This confirms that the findings are not dependent on outliers or regional bias.

---

## 5. Heterogeneous Effects — Wage Group Differences

![Heterogeneity](images/lowVshigh_afterPolicy.png)

This figure compares the post-policy outcomes between low-wage and high-wage workers.

A clear divergence emerges after implementation:
- Low-wage workers experience a stronger negative effect  
- High-wage workers show relatively stable or improved outcomes  

This indicates that the policy impact is **not uniform**, but concentrated among economically vulnerable workers.

---

## Summary of Findings

Across all robustness and validation checks, a consistent pattern emerges:

- The effect is robust across multiple specifications  
- It is not driven by any single state  
- The parallel trends assumption holds  
- The impact is concentrated among low-wage workers  
- Results are not explained by pre-existing differences or external variation  

Together, these findings strengthen the credibility of the causal interpretation.

---

## Key Insight

Instead of relying on a single regression output, this analysis builds a layered validation system around the model.

Each figure answers a different question:

- Is the result real?  
- Is it stable?  
- Who is affected?  
- Can the model assumptions be trusted?  
- Could external factors explain the result?  

The consistency across all layers is what makes the final result reliable and interpretable.

---
