const LABELS = {
  wageTier: {
    all: "All wage tiers",
    low_wage: "Low wage",
    other_wage: "Other wage",
  },
  ageBand: {
    all: "All ages",
    "18_24": "Ages 18-24",
    "25_34": "Ages 25-34",
    "35_54": "Ages 35-54",
    "55_plus": "Ages 55+",
  },
  sex: {
    all: "All workers",
    men: "Men",
    women: "Women",
  },
  educationBand: {
    all: "All education levels",
    hs_or_less: "High school or less",
    some_college: "Some college",
    bachelors_plus: "Bachelor's+",
  },
  raceBand: {
    all: "All race / ethnicity groups",
    white_non_hispanic: "White, non-Hispanic",
    black_non_hispanic: "Black, non-Hispanic",
    hispanic: "Hispanic",
    other_non_hispanic: "Other, non-Hispanic",
  },
  treatmentMode: {
    june_only: "June-only exits",
    all_early_exits: "All early exits",
  },
  employmentMode: {
    any_employed: "Any employed",
    at_work_only: "At work only",
  },
  sample: {
    all_ages: "All ages",
    prime_age: "Prime age",
    no_college: "No college",
    prime_age_no_college: "Prime age + no college",
    young_18_24: "Young 18-24",
    older_55_plus: "Older 55+",
  },
};

const state = {
  wageTier: "low_wage",
  ageBand: "all",
  sex: "all",
  educationBand: "all",
  raceBand: "all",
  treatmentMode: "june_only",
  employmentMode: "any_employed",
  sample: "all_ages",
};

const bundle = await fetch("./data/policy_demo_bundle.json").then((response) => response.json());

const controls = {
  wageTier: document.querySelector("#wageTier"),
  ageBand: document.querySelector("#ageBand"),
  sex: document.querySelector("#sex"),
  educationBand: document.querySelector("#educationBand"),
  raceBand: document.querySelector("#raceBand"),
  treatmentMode: document.querySelector("#treatmentMode"),
  employmentMode: document.querySelector("#employmentMode"),
  sample: document.querySelector("#sample"),
};

const treatmentSets = Object.fromEntries(
  bundle.treatment_sets.map((row) => [row.treatment_mode, new Set(row.states.map((item) => item.fips))]),
);

populateControls();
bindControls();
render();

function populateControls() {
  setOptions(controls.wageTier, Object.keys(LABELS.wageTier), LABELS.wageTier);
  setOptions(controls.ageBand, Object.keys(LABELS.ageBand), LABELS.ageBand);
  setOptions(controls.sex, Object.keys(LABELS.sex), LABELS.sex);
  setOptions(controls.educationBand, Object.keys(LABELS.educationBand), LABELS.educationBand);
  setOptions(controls.raceBand, Object.keys(LABELS.raceBand), LABELS.raceBand);
  setOptions(controls.treatmentMode, Object.keys(LABELS.treatmentMode), LABELS.treatmentMode);
  setOptions(controls.employmentMode, Object.keys(LABELS.employmentMode), LABELS.employmentMode);

  const samples = [...new Set(bundle.ddd_grid.map((row) => row.sample))].filter((key) => key in LABELS.sample);
  setOptions(controls.sample, samples, LABELS.sample);
}

function setOptions(select, keys, labelMap) {
  select.innerHTML = "";
  keys.forEach((key) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = labelMap[key] || key;
    option.selected = state[select.id] === key;
    select.append(option);
  });
}

function bindControls() {
  Object.values(controls).forEach((control) => {
    control.addEventListener("change", (event) => {
      state[event.target.id] = event.target.value;
      render();
    });
  });
}

function render() {
  const filteredRows = getFilteredRows();
  const monthlySeries = buildMonthlySeries(filteredRows);
  const contrast = buildContrast(filteredRows);
  const footprint = buildFootprint(filteredRows);
  const benchmark = getCurrentBenchmark();

  renderPrompt(filteredRows, benchmark);
  renderScenario(filteredRows, contrast, benchmark);
  renderMonthlyChart(monthlySeries);
  renderContrastChart(contrast);
  renderFootprintChart(footprint);
  renderEventChart();
}

function getFilteredRows() {
  const activeSet = treatmentSets[state.treatmentMode];
  return bundle.profile_rows
    .map((row) => ({
      ...row,
      treated_now: activeSet.has(row.statefip),
    }))
    .filter((row) => matchesFilters(row) && matchesSample(row));
}

function matchesFilters(row) {
  if (state.wageTier !== "all") {
    const wantsLow = state.wageTier === "low_wage";
    if ((row.low_wage === 1) !== wantsLow) return false;
  }
  if (state.ageBand !== "all" && row.age_band !== state.ageBand) return false;
  if (state.sex !== "all" && row.sex !== state.sex) return false;
  if (state.educationBand !== "all" && row.education_band !== state.educationBand) return false;
  if (state.raceBand !== "all" && row.race_band !== state.raceBand) return false;
  return true;
}

function matchesSample(row) {
  switch (state.sample) {
    case "all_ages":
      return true;
    case "prime_age":
      return row.age_band === "25_34" || row.age_band === "35_54";
    case "no_college":
      return row.education_band !== "bachelors_plus";
    case "prime_age_no_college":
      return (row.age_band === "25_34" || row.age_band === "35_54") && row.education_band !== "bachelors_plus";
    case "young_18_24":
      return row.age_band === "18_24";
    case "older_55_plus":
      return row.age_band === "55_plus";
    default:
      return true;
  }
}

function buildMonthlySeries(rows) {
  const monthly = [];
  for (let month = 1; month <= 12; month += 1) {
    const monthRows = rows.filter((row) => row.month === month);
    monthly.push({
      month,
      treated_rate: weightedRate(monthRows.filter((row) => row.treated_now)),
      control_rate: weightedRate(monthRows.filter((row) => !row.treated_now)),
      treated_weight: sumWeight(monthRows.filter((row) => row.treated_now)),
      control_weight: sumWeight(monthRows.filter((row) => !row.treated_now)),
    });
  }
  return monthly;
}

function buildContrast(rows) {
  return [
    {
      label: "Control pre",
      rate: weightedRate(rows.filter((row) => !row.treated_now && row.post === 0)),
      weight: sumWeight(rows.filter((row) => !row.treated_now && row.post === 0)),
      className: "bar-control",
    },
    {
      label: "Control post",
      rate: weightedRate(rows.filter((row) => !row.treated_now && row.post === 1)),
      weight: sumWeight(rows.filter((row) => !row.treated_now && row.post === 1)),
      className: "bar-control",
    },
    {
      label: "Treated pre",
      rate: weightedRate(rows.filter((row) => row.treated_now && row.post === 0)),
      weight: sumWeight(rows.filter((row) => row.treated_now && row.post === 0)),
      className: "bar-treated",
    },
    {
      label: "Treated post",
      rate: weightedRate(rows.filter((row) => row.treated_now && row.post === 1)),
      weight: sumWeight(rows.filter((row) => row.treated_now && row.post === 1)),
      className: "bar-treated",
    },
  ];
}

function buildFootprint(rows) {
  const total = sumWeight(rows);
  return [
    {
      label: "Control pre",
      value: share(sumWeight(rows.filter((row) => !row.treated_now && row.post === 0)), total),
      className: "bar-neutral",
    },
    {
      label: "Control post",
      value: share(sumWeight(rows.filter((row) => !row.treated_now && row.post === 1)), total),
      className: "bar-control",
    },
    {
      label: "Treated pre",
      value: share(sumWeight(rows.filter((row) => row.treated_now && row.post === 0)), total),
      className: "bar-neutral",
    },
    {
      label: "Treated post",
      value: share(sumWeight(rows.filter((row) => row.treated_now && row.post === 1)), total),
      className: "bar-treated",
    },
  ];
}

function renderPrompt(filteredRows, benchmark) {
  const node = document.querySelector("#profilePrompt");
  const totalWeight = sumWeight(filteredRows);
  const treatedShare = share(sumWeight(filteredRows.filter((row) => row.treated_now)), totalWeight);
  const benchmarkText = benchmark
    ? `The saved robustness frame below is ${LABELS.employmentMode[state.employmentMode].toLowerCase()} inside ${LABELS.sample[state.sample].toLowerCase()}.`
    : "The saved robustness frame is unavailable for this exact combination, so the page stays anchored on the live cohort view.";

  node.textContent =
    `You are presenting ${buildHumanProfile()} under ${LABELS.treatmentMode[state.treatmentMode].toLowerCase()}. ` +
    `This filtered cohort carries ${formatWeight(totalWeight)} weighted observations, with ${formatPercent(treatedShare)} of the weight assigned to treated states. ${benchmarkText}`;
}

function renderScenario(filteredRows, contrast, benchmark) {
  const titleNode = document.querySelector("#scenarioTitle");
  const summaryNode = document.querySelector("#scenarioSummary");
  const statsNode = document.querySelector("#spotlightStats");

  titleNode.textContent = buildScenarioTitle();
  summaryNode.textContent =
    `The main view tracks weighted monthly job-finding rates for this profile, split by the currently selected treatment set. ` +
    `Use the builder to change one characteristic at a time so the treated and control paths visibly separate or reconverge. ` +
    (benchmark
      ? `The lower benchmark stays aligned to ${LABELS.sample[state.sample].toLowerCase()} and the ${LABELS.employmentMode[state.employmentMode].toLowerCase()} outcome definition.`
      : `The benchmark panel below remains descriptive because there is no matching saved model row for this exact setup.`);

  const currentTreatment = bundle.treatment_sets.find((row) => row.treatment_mode === state.treatmentMode);
  const weightedTotal = sumWeight(filteredRows);
  const treatedShare = share(sumWeight(filteredRows.filter((row) => row.treated_now)), weightedTotal);
  const postShare = share(sumWeight(filteredRows.filter((row) => row.post === 1)), weightedTotal);
  const activeMonths = new Set(filteredRows.map((row) => row.month)).size;

  const stats = [
    {
      label: "Weighted cohort",
      value: formatWeight(weightedTotal),
      meta: `${filteredRows.length.toLocaleString()} respondent rows after the current profile and slice filters.`,
    },
    {
      label: "Treatment map",
      value: `${currentTreatment?.treat_state_count ?? 0} states`,
      meta: `${LABELS.treatmentMode[state.treatmentMode]} is the live treated set for the charts.`,
    },
    {
      label: "Treated share",
      value: formatPercent(treatedShare),
      meta: `Share of this weighted cohort currently landing inside the treated-state group.`,
    },
    {
      label: "Coverage window",
      value: `${activeMonths} months`,
      meta: `${formatPercent(postShare)} of the weighted cohort sits in the post period for the current scenario.`,
    },
  ];

  statsNode.innerHTML = stats
    .map(
      (item) => `
        <div class="spotlight-stat fade-in">
          <p class="spotlight-stat-label">${item.label}</p>
          <p class="spotlight-stat-value">${item.value}</p>
          <p class="spotlight-stat-meta">${item.meta}</p>
        </div>
      `,
    )
    .join("");
}

function buildScenarioTitle() {
  return `${buildHumanProfile()} under ${LABELS.treatmentMode[state.treatmentMode].toLowerCase()}`;
}

function buildHumanProfile() {
  const parts = [];
  if (state.wageTier !== "all") parts.push(LABELS.wageTier[state.wageTier].toLowerCase());
  if (state.sex !== "all") parts.push(LABELS.sex[state.sex].toLowerCase());
  if (state.ageBand !== "all") parts.push(LABELS.ageBand[state.ageBand].toLowerCase().replace("ages ", "ages "));
  if (state.educationBand !== "all") parts.push(LABELS.educationBand[state.educationBand].toLowerCase());
  if (state.raceBand !== "all") parts.push(LABELS.raceBand[state.raceBand].toLowerCase());

  if (!parts.length) {
    return "the full worker pool";
  }

  if (parts.length === 1) {
    return `${parts[0]} workers`;
  }

  return `${parts.slice(0, -1).join(", ")} ${parts.at(-1)} workers`;
}

function renderMonthlyChart(rows) {
  const node = document.querySelector("#monthlyChart");
  const values = rows.flatMap((row) => [row.treated_rate ?? 0, row.control_rate ?? 0]).filter((value) => value != null);

  if (!values.length) {
    node.innerHTML = emptyState("No monthly profile rows match the current builder settings.");
    return;
  }

  node.innerHTML =
    svgLineComparison(rows, {
      yMin: 0,
      yMax: Math.max(0.05, ...values) * 1.15,
      leftLabel: "Control",
      rightLabel: "Treated",
    }) +
    legendMarkup([
      ["accent", "Control states"],
      ["signal", "Treated states"],
      ["secondary", "Post period"],
    ]);
}

function renderContrastChart(rows) {
  const node = document.querySelector("#contrastChart");
  const maxValue = Math.max(0.05, ...rows.map((row) => row.rate ?? 0));
  node.innerHTML = svgBarChart(rows.map((row) => ({ ...row, value: row.rate ?? 0 })), 0, maxValue * 1.15, "Weighted rate");
}

function renderFootprintChart(rows) {
  const node = document.querySelector("#footprintChart");
  node.innerHTML = svgBarChart(rows, 0, 1, "Share of weighted cohort");
}

function renderEventChart() {
  const node = document.querySelector("#eventChart");
  const activeKey = state.wageTier === "other_wage" ? "other_wage" : "low_wage";
  const primary = bundle.event_studies[activeKey];
  const secondary =
    state.wageTier === "all"
      ? bundle.event_studies.other_wage
      : state.wageTier === "low_wage"
        ? bundle.event_studies.other_wage
        : bundle.event_studies.low_wage;

  node.innerHTML =
    svgEventStudy(primary, secondary, {
      primaryLabel: state.wageTier === "other_wage" ? "Other wage" : "Low wage",
      secondaryLabel:
        state.wageTier === "all"
          ? "Other wage"
          : state.wageTier === "low_wage"
            ? "Other wage"
            : "Low wage",
    }) +
    legendMarkup([
      ["signal", state.wageTier === "other_wage" ? "Other wage" : "Low wage"],
      ["secondary", state.wageTier === "all" ? "Comparison wage tier" : "Reference wage tier"],
    ]);
}

function getCurrentBenchmark() {
  return bundle.ddd_grid.find(
    (row) =>
      row.sample === state.sample &&
      row.treatment_mode === state.treatmentMode &&
      row.employment_mode === state.employmentMode &&
      row.control_spec === "covid_stringency",
  );
}

function weightedRate(rows) {
  const totalWeight = sumWeight(rows);
  if (!totalWeight) return null;
  const successWeight = rows.reduce((sum, row) => sum + row.weight * row.found_job, 0);
  return successWeight / totalWeight;
}

function sumWeight(rows) {
  return rows.reduce((sum, row) => sum + row.weight, 0);
}

function share(value, total) {
  if (!total) return 0;
  return value / total;
}

function safeDiff(a, b) {
  if (a == null || b == null) return null;
  return a - b;
}

function formatSigned(value) {
  if (value == null || Number.isNaN(value)) return "n/a";
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}`;
}

function formatPercent(value) {
  if (value == null || Number.isNaN(value)) return "n/a";
  return `${(value * 100).toFixed(1)}%`;
}

function formatWeight(value) {
  if (!value) return "0";
  return Math.round(value).toLocaleString();
}

function legendMarkup(items) {
  return `<div class="legend">${items
    .map(
      ([tone, label]) =>
        `<span class="legend-item"><span class="legend-swatch ${tone}"></span>${label}</span>`,
    )
    .join("")}</div>`;
}

function emptyState(message) {
  return `<div class="empty-state">${message}</div>`;
}

function svgLineComparison(rows, config) {
  const width = 920;
  const height = 340;
  const margin = { top: 24, right: 26, bottom: 42, left: 52 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const x = (month) => margin.left + ((month - 1) / 11) * innerWidth;
  const y = (value) =>
    margin.top + innerHeight - ((value - config.yMin) / (config.yMax - config.yMin || 1)) * innerHeight;

  const gridValues = [0, 0.05, 0.1, 0.15, 0.2].filter((value) => value <= config.yMax);
  const treatedPath = linePath(rows, "treated_rate", x, y);
  const controlPath = linePath(rows, "control_rate", x, y);

  return `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg" role="img" aria-label="Monthly weighted job-finding rates">
      <rect x="${x(6.5)}" y="${margin.top}" width="${innerWidth / 2}" height="${innerHeight}" class="area-post"></rect>
      ${gridValues
        .map(
          (value) => `
            <line x1="${margin.left}" y1="${y(value)}" x2="${width - margin.right}" y2="${y(value)}" class="grid-line"></line>
            <text x="${margin.left - 10}" y="${y(value) + 4}" class="axis-text" text-anchor="end">${formatPercent(value)}</text>
          `,
        )
        .join("")}
      <line x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}" class="axis-line"></line>
      ${Array.from({ length: 12 }, (_, index) => index + 1)
        .map(
          (month) => `
            <text x="${x(month)}" y="${height - 14}" class="axis-text" text-anchor="middle">${month}</text>
          `,
        )
        .join("")}
      <path d="${controlPath}" class="line-control"></path>
      <path d="${treatedPath}" class="line-treated"></path>
      ${rows
        .map(
          (row) => `
            ${row.control_rate == null ? "" : `<circle cx="${x(row.month)}" cy="${y(row.control_rate)}" r="4" class="dot-control"></circle>`}
            ${row.treated_rate == null ? "" : `<circle cx="${x(row.month)}" cy="${y(row.treated_rate)}" r="4" class="dot-treated"></circle>`}
          `,
        )
        .join("")}
      <text x="${x(10.7)}" y="${margin.top + 18}" class="axis-text" text-anchor="end">post period</text>
    </svg>
  `;
}

function linePath(rows, key, x, y) {
  return rows
    .filter((row) => row[key] != null)
    .map((row, index) => `${index === 0 ? "M" : "L"} ${x(row.month)} ${y(row[key])}`)
    .join(" ");
}

function svgBarChart(rows, minValue, maxValue, yLabel) {
  const width = 520;
  const height = 260;
  const margin = { top: 18, right: 20, bottom: 52, left: 50 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const barWidth = innerWidth / rows.length - 16;
  const x = (index) => margin.left + index * (innerWidth / rows.length) + 10;
  const y = (value) =>
    margin.top + innerHeight - ((value - minValue) / (maxValue - minValue || 1)) * innerHeight;

  const grid = [0, maxValue / 2, maxValue].filter((value, index, arr) => value >= minValue && arr.indexOf(value) === index);

  return `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg" role="img" aria-label="${yLabel}">
      ${grid
        .map(
          (value) => `
            <line x1="${margin.left}" y1="${y(value)}" x2="${width - margin.right}" y2="${y(value)}" class="grid-line"></line>
            <text x="${margin.left - 10}" y="${y(value) + 4}" class="axis-text" text-anchor="end">${
              maxValue <= 1 ? formatPercent(value) : value.toFixed(2)
            }</text>
          `,
        )
        .join("")}
      ${rows
        .map((row, index) => {
          const barHeight = innerHeight - (y(row.value) - margin.top);
          return `
            <rect x="${x(index)}" y="${y(row.value)}" width="${barWidth}" height="${barHeight}" class="${row.className}"></rect>
            <text x="${x(index) + barWidth / 2}" y="${height - 18}" class="axis-text" text-anchor="middle">${row.label}</text>
          `;
        })
        .join("")}
    </svg>
  `;
}

function svgEventStudy(primaryRows, secondaryRows, labels) {
  const width = 920;
  const height = 320;
  const margin = { top: 24, right: 24, bottom: 42, left: 52 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const allValues = [...primaryRows, ...secondaryRows].map((row) => row.coef);
  const maxAbs = Math.max(0.06, ...allValues.map((value) => Math.abs(value)));
  const x = (month) => margin.left + ((month - 2) / 10) * innerWidth;
  const y = (value) => margin.top + innerHeight - ((value + maxAbs) / (maxAbs * 2 || 1)) * innerHeight;

  return `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg" role="img" aria-label="Saved event study benchmark">
      <line x1="${margin.left}" y1="${y(0)}" x2="${width - margin.right}" y2="${y(0)}" class="axis-line"></line>
      ${[-maxAbs, 0, maxAbs]
        .map(
          (value) => `
            <text x="${margin.left - 10}" y="${y(value) + 4}" class="axis-text" text-anchor="end">${formatSigned(value)}</text>
          `,
        )
        .join("")}
      ${primaryRows
        .map(
          (row, index) => `
            ${
              index === 0
                ? ""
                : `<line x1="${x(primaryRows[index - 1].month)}" y1="${y(primaryRows[index - 1].coef)}" x2="${x(row.month)}" y2="${y(row.coef)}" class="line-treated"></line>`
            }
          `,
        )
        .join("")}
      ${secondaryRows
        .map(
          (row, index) => `
            ${
              index === 0
                ? ""
                : `<line x1="${x(secondaryRows[index - 1].month)}" y1="${y(secondaryRows[index - 1].coef)}" x2="${x(row.month)}" y2="${y(row.coef)}" class="line-secondary"></line>`
            }
          `,
        )
        .join("")}
      ${primaryRows
        .map(
          (row) => `<circle cx="${x(row.month)}" cy="${y(row.coef)}" r="4" class="dot-treated"></circle>`,
        )
        .join("")}
      ${secondaryRows
        .map(
          (row) => `<circle cx="${x(row.month)}" cy="${y(row.coef)}" r="3" class="dot-control"></circle>`,
        )
        .join("")}
      ${primaryRows
        .map(
          (row) => `<text x="${x(row.month)}" y="${height - 14}" class="axis-text" text-anchor="middle">${row.month}</text>`,
        )
        .join("")}
      <text x="${width - margin.right}" y="${margin.top}" class="axis-text" text-anchor="end">${labels.primaryLabel}</text>
      <text x="${width - margin.right}" y="${margin.top + 18}" class="axis-text" text-anchor="end">${labels.secondaryLabel}</text>
    </svg>
  `;
}
