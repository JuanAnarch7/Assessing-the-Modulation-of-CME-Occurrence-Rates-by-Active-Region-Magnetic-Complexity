# Solar Active Regions ↔ CME Correlation Analysis

This repository contains the correlation-analysis stage of a pipeline that
studies the statistical relationship between solar **Active Region (AR)**
characteristics and **Coronal Mass Ejection (CME)** subpopulations, across
Solar Cycles 23, 24, and 25 (1996–2026).

The full methodology is summarized in the workflow diagram
(`Diagrama_Ars-CMEs.png`) and is organized into six stages:

## Pipeline overview

```
1. Data Acquisition        → Retrieve CME catalog (CDAW) and AR data (NOAA SRS)
2. Data Preprocessing      → Clean, standardize, and compile raw reports
3. Feature Engineering     → Define CME subpopulations and derive AR variables
4. Monthly Aggregation     → Build the monthly master dataset
5. Correlation Analysis    → Spearman correlations (full period / cycle /
                              phase / lag)
6. End                     → Consolidated outputs (CSV, heatmaps, plots)
```

### 1. Data Acquisition
- **CME catalog**: retrieved from the CDAW (Coordinated Data Analysis
  Workshop) CME catalog.
- **Active Region data**: retrieved from NOAA Solar Region Summary (SRS)
  daily reports.

### 2. Data Preprocessing
- CME catalog: incomplete records removed, dates standardized, CME variables
  prepared.
- AR data: an automated script downloads, parses, compiles, and cleans daily
  NOAA SRS reports into a single unified dataset.

### 3. Feature Engineering
- **CME subpopulations** are defined: full population, speed-filtered
  subsets (slow / moderate / fast / extreme), angular-width subsets
  (normal / partial halo / halo), and a filtered subset.
- **AR-derived variables** are generated: total active regions, lifetime and
  classification, magnetic complexity, count of high-complexity regions
  (β/βγ/βγδ), and additional derived metrics (large / small / ephemeral
  region counts, complexity-weighted area).
- Both sets are merged into the **Master Dataset**.

### 4. Monthly Aggregation
The master dataset is aggregated into monthly counts for every AR variable
and every CME subpopulation, producing the **Monthly Analysis Dataset**
(`master_monthly.csv`) — the common input consumed by all three scripts in
this repository.

### 5. Correlation Analysis
For each CME subpopulation, three complementary analyses are run in a loop:
1. **Spearman rank correlation** over the full observation period and over
   each individual solar cycle (SC 23 / 24 / 25).
2. **Solar-cycle phase analysis**: the same correlations repeated separately
   for the rising phase, maximum, and declining phase of each cycle.
3. **Lag analysis**: Spearman correlation between each AR variable (lagged
   1–12 months) and each CME subpopulation, to evaluate how the
   relationship evolves with time delay.

---

## Scripts in this repository

All three scripts read the same input file, `master_monthly.csv`, expected
to sit in the same directory as the script (`BASE_DIR`), with a `yearmonth`
column plus the AR/CME variable columns listed in `VARIABLES` and
`SUBPOPULATIONS` inside each script.

> **Note on column names**: The internal data columns (e.g. `n_total`,
> `n_alta_complejidad`, `count_cmes_all`, `count_cmes_halo`, …) were **kept
> unchanged** during translation, since they must match the actual column
> names in `master_monthly.csv`. Only comments, docstrings, console
> messages, and plot labels/titles were translated to English.

### 1. `correlation_matrix_periods.py`
Corresponds to step **5.1** of the diagram (full period + per solar cycle).

- Computes a Spearman correlation matrix (AR variables × CME subpopulations)
  for the full observation period (1996–2026) and for each of Solar Cycles
  23, 24, and 25.
- **Outputs** (in `correlation_matrices/`):
  - One CSV per period with the correlation matrix.
  - One heatmap PNG per period.
  - One grouped bar chart per period (correlation by variable).
  - An optional consolidated Excel workbook (`correlation_matrices_periods.xlsx`)
    if `openpyxl` is installed.

### 2. `correlation_matrix_solar_cycle_phases.py`
Corresponds to step **5.2** of the diagram (rising / maximum / declining
phase of each cycle).

- Computes Spearman correlation matrices for 8 sub-periods: the rising,
  maximum, and declining phases of Cycles 23 and 24, and the rising phase
  and maximum of Cycle 25 (still ongoing).
- In addition to the correlation coefficient (ρ) and p-value, it computes a
  **95% confidence interval** for each ρ via **moving-block bootstrap**
  (block length = 12 months, 2000 resamples, deterministically seeded per
  period/variable/subpopulation pair for reproducibility).
- **Outputs** (in `correlation_matrices_phases/`):
  - One CSV per phase containing ρ, p-value, and CI bounds for every
    variable–subpopulation pair.
  - One heatmap PNG per phase (higher resolution, 600 dpi, LaTeX-style
    symbol labels for compact publication figures).

### 3. `correlation_lag_variables.py`
Corresponds to step **5.3** of the diagram (lag analysis, −1 to −12 months).

- For each solar-cycle phase and for lags of 1 to 12 months, computes the
  Spearman correlation between each **lagged** AR variable and each CME
  subpopulation (i.e., "does last month's AR activity predict this month's
  CME activity?").
- **Outputs** (in `correlation_lag_outputs/`):
  - A long-format CSV per phase with every period/lag/variable/subpopulation
    combination (`*_lagged_correlations.csv`), plus one CSV per individual
    lag.
  - A faceted heatmap grid per phase — one mini-heatmap per AR variable,
    showing subpopulation × lag without averaging (`*_variable_facets_heatmap.png`).
  - A two-panel summary figure per phase: a mean-correlation heatmap
    (averaged across lags) plus a scatter/line plot showing how correlation
    evolves with lag for each variable (`*_lag_summary.png`).
  - A global summary heatmap (`period_lag_sensitivity_summary.png`) showing
    mean absolute correlation by lag across all phases/cycles.
  - Two consolidated CSVs: `all_periods_lagged_correlations.csv` (every row)
    and `period_lag_summary.csv` (mean ρ and mean |ρ| per period/lag).

---

## Requirements

```
pandas
numpy
scipy
matplotlib
openpyxl   # optional, only needed for the Excel export in
           # correlation_matrix_periods.py
```

Install with:
```bash
pip install pandas numpy scipy matplotlib openpyxl
```

## Usage

Place `master_monthly.csv` in the same folder as the scripts, then run each
stage independently:

```bash
python correlation_matrix_periods.py
python correlation_matrix_solar_cycle_phases.py
python correlation_lag_variables.py
```

Each script creates its own output folder (`correlation_matrices/`,
`correlation_matrices_phases/`, `correlation_lag_outputs/`) and prints a
`Saved: <path>` line for every file it writes.

## Expected input schema (`master_monthly.csv`)

| Column | Description |
|---|---|
| `yearmonth` | Month identifier, `YYYY-MM` |
| `n_total` | Number of active regions |
| `n_alta_complejidad` | Number of high-complexity (β/βγ/βγδ) regions |
| `complexity_area_sum` | Complexity-weighted area proxy |
| `n_large` | Number of large regions |
| `n_small` | Number of medium/small regions |
| `n_ephemeral` | Number of ephemeral regions |
| `count_cmes_all` | Total CME count |
| `count_cmes_normal` / `_partial_halo` / `_halo` | CME counts by angular width |
| `count_cmes_slow` / `_moderate` / `_fast` / `_extreme` | CME counts by speed class |
| `count_cmes_filtered` | Filtered CME subset count |

## Reproducibility notes

- All Spearman correlations use `scipy.stats.spearmanr`.
- The bootstrap confidence intervals in `correlation_matrix_solar_cycle_phases.py`
  use a fixed global seed (`SEED = 42`) combined deterministically with the
  period, variable, and subpopulation names, so results are identical across
  runs.
- Pairs with fewer than 3 valid (non-NaN) monthly observations are skipped
  and reported as `NaN`.
