# Solar Active Regions ↔ CME Correlation Analysis


This folder implements **stage 5** of the project pipeline: the statistical
analysis of the relationship between solar Active Region (AR) variables and
CME subpopulations, using the monthly master dataset produced by the
[`data/`](../data) folder.

It does not acquire or preprocess any raw data itself — it only consumes
`master_monthly.csv` (see [`data/README.md`](../data/README.md) for how that
file is built) and runs three complementary correlation analyses on it.

## Input

All three scripts expect `master_monthly.csv` in the same directory as the
script (`BASE_DIR`). Copy or symlink it here from `data/`, or edit the
`CSV_PATH` constant at the top of each script to point elsewhere.

Expected columns:

| Column | Description |
|---|---|
| `yearmonth` | Month identifier, `YYYY-MM` |
| `n_total` | Number of active regions |
| `n_alta_complejidad` | Number of high-complexity (β/βγ/βγδ) regions |
| `complexity_area_sum` | Complexity-weighted area proxy |
| `n_large` / `n_small` / `n_ephemeral` | Region counts by lifetime class |
| `count_cmes_all` | Total CME count |
| `count_cmes_normal` / `_partial_halo` / `_halo` | CME counts by angular width |
| `count_cmes_slow` / `_moderate` / `_fast` / `_extreme` | CME counts by speed class |
| `count_cmes_filtered` | Filtered CME subset count |

> **Note on column names:** internal data columns (`n_total`,
> `n_alta_complejidad`, `count_cmes_all`, `count_cmes_halo`, …) are kept as
> defined in `master_monthly.csv` — they are referenced literally inside the
> scripts and must not be renamed without updating the `VARIABLES` /
> `SUBPOPULATIONS` lists at the top of each file.

## What "Correlation Analysis" covers

For each CME subpopulation, three complementary analyses are run:

1. **Full-period / per-cycle correlation** — Spearman rank correlation over
   the entire observation window (1996–2026) and separately over Solar
   Cycles 23, 24, and 25.
2. **Solar-cycle phase analysis** — the same correlations repeated
   separately for the rising phase, maximum, and declining phase of each
   cycle, with bootstrap confidence intervals.
3. **Lag analysis** — Spearman correlation between each AR variable
   (lagged 1–12 months) and each CME subpopulation, to see whether AR
   activity leads CME activity by some number of months.

## Scripts

### 1. `correlation_matrix_periods.py`

Full period + per-solar-cycle correlation matrices.

- Computes a Spearman correlation matrix (AR variables × CME subpopulations)
  for the full observation period (1996–2026) and for each of Solar Cycles
  23, 24, and 25.
- **Outputs** (in `correlation_matrices/`):
  - One CSV per period with the correlation matrix.
  - One heatmap PNG per period.
  - One grouped bar chart per period (correlation by variable).
  - An optional consolidated Excel workbook
    (`correlation_matrices_periods.xlsx`) if `openpyxl` is installed.

```bash
python correlation_matrix_periods.py
```

### 2. `correlation_matrix_solar_cycle_phases.py`

Correlation matrices per solar-cycle phase (rising / maximum / declining).

- Computes Spearman correlation matrices for 8 sub-periods: the rising,
  maximum, and declining phases of Cycles 23 and 24, and the rising phase
  and maximum of Cycle 25 (still ongoing).
- In addition to ρ and the p-value, computes a **95% confidence interval**
  for each ρ via **moving-block bootstrap** (block length = 12 months, 2000
  resamples, deterministically seeded per period/variable/subpopulation
  triple for reproducibility).
- **Outputs** (in `correlation_matrices_phases/`):
  - One CSV per phase with ρ, p-value, and CI bounds for every
    variable–subpopulation pair.
  - One heatmap PNG per phase (600 dpi, LaTeX-style symbol labels, suited
    for publication figures).

```bash
python correlation_matrix_solar_cycle_phases.py
```

### 3. `correlation_lag_variables.py`

Lag analysis (1–12 months) per solar-cycle phase.

- For each phase and each lag from 1 to 12 months, computes the Spearman
  correlation between each **lagged** AR variable and each CME
  subpopulation.
- **Outputs** (in `correlation_lag_outputs/`):
  - A long-format CSV per phase with every
    period/lag/variable/subpopulation combination
    (`*_lagged_correlations.csv`), plus one CSV per individual lag.
  - A faceted heatmap grid per phase — one mini-heatmap per AR variable,
    showing subpopulation × lag without averaging
    (`*_variable_facets_heatmap.png`).
  - A two-panel summary figure per phase: a mean-correlation heatmap
    (averaged across lags) plus a scatter/line plot of correlation vs. lag
    for each variable (`*_lag_summary.png`).
  - A global summary heatmap (`period_lag_sensitivity_summary.png`) of mean
    absolute correlation by lag across all phases/cycles.
  - Two consolidated CSVs: `all_periods_lagged_correlations.csv` (every
    row) and `period_lag_summary.csv` (mean ρ and mean |ρ| per period/lag).

```bash
python correlation_lag_variables.py
```

## Requirements

```
pandas
numpy
scipy
matplotlib
openpyxl   # optional, only for the Excel export in correlation_matrix_periods.py
```

```bash
pip install pandas numpy scipy matplotlib openpyxl
```

## Usage

```bash
# Make sure master_monthly.csv is in this folder (copy from ../data/ or
# adjust CSV_PATH in each script)
python correlation_matrix_periods.py
python correlation_matrix_solar_cycle_phases.py
python correlation_lag_variables.py
```

Each script creates its own output folder (`correlation_matrices/`,
`correlation_matrices_phases/`, `correlation_lag_outputs/`) and prints a
`Saved: <path>` line for every file it writes. The scripts are independent
of one another and can be run in any order.

## Reproducibility notes

- All correlations use `scipy.stats.spearmanr`.
- The bootstrap confidence intervals in
  `correlation_matrix_solar_cycle_phases.py` use a fixed global seed
  (`SEED = 42`) combined deterministically with the period, variable, and
  subpopulation names, so results are identical across runs.
- Any variable/subpopulation pair with fewer than 3 valid (non-NaN) monthly
  observations in a given period is skipped and reported as `NaN` rather
  than raising an error.
- Solar Cycle 25's declining phase is not yet defined, since the cycle is
  still ongoing as of the latest data (Feb 2026); only its rising phase and
  maximum are included in the phase and lag analyses.
