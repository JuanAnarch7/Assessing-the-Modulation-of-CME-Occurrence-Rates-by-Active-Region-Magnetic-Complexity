# Master monthly dataset

This folder joins the monthly CME counts, active-region features, flare activity and sunspot number into `master_monthly.csv`, the input of the statistical analysis.

## Contents

| Path | Type | Description |
|---|---|---|
| `master_dataset_builder.py` | script | Builds the master dataset from the other folders |
| `master_monthly.csv` | output | One row per calendar month |

> **Do not run the current builder yet.** It is being rewritten (see below). The committed `master_monthly.csv` was produced from the previous inputs (CDAW download of 2026-02-28, old `Lecture.py`, old AR features) and is kept because `../../Correlation analysis/` reads it. The new active-region features use renamed columns (`n_regions`, `n_long_lived`, …), so running the old builder on them would produce a master file the analysis scripts cannot read.

## Inputs (after the rewrite)

| Input | Folder |
|---|---|
| `datos_procesados_TAG.csv`, `lasco_monthly_coverage_TAG.csv` | `../cme/` |
| `ar_features_monthly.csv` | `../active_regions/` |
| `flares_monthly.csv` | `../flares/` (in preparation) |
| `SN_m_tot_V2.0.txt` | `../sunspot_number/` |

## Planned changes

1. Merge the LASCO monthly coverage: CME counts set to `NaN` when coverage < 0.5; coverage-normalised counts (`count_cmes_*_norm`) for the other months; raw counts kept for count models with `log(coverage)` as offset.
2. CME counts also without `poor` / `very_poor` events.
3. New active-region features (areas, δ, daily means, SRS coverage) with the renamed columns.
4. Flare features (counts by class on the classic GOES scale, flare index, δ-region flares, eruptive/confined counts, GOES coverage).
5. 13-month smoothed sunspot number (SN13) as the cycle trend.
6. `END_MONTH` set automatically to the last month covered by all sources.

## `master_dataset_builder.py` — Monthly Resolution

Combines the three preceding sources — CMEs, sunspot numbers, and AR features — into a single monthly master dataset.

**What it does (current version):**

1. **Loads sunspot numbers** (`load_sunspots`): reads the whitespace-separated SILSO text file, builds a `yearmonth` (YYYY-MM) column, filters to the configured year range, and replaces the SILSO missing-data marker (`-1`) with `NaN`.
2. **Loads and filters CMEs** (`load_cmes`): reads the CME table and builds monthly count columns:
   - By angular width: normal (20°–120°), partial halo (>120°–<360°), full halo (360°).
   - By speed: slow (0–600 km/s), moderate (600–1000 km/s), fast (1000–1500 km/s), extreme (≥1500 km/s).
   - A combined filter (`count_cmes_filtered`): speed ≥ `MIN_SPEED` and `MIN_WIDTH` ≤ width ≤ `MAX_WIDTH`.
   - All monthly counts are reindexed to the full date range, and months without events are set to `0`.
3. **Loads AR features** (`load_ar_features`): reads `ar_features_monthly.csv` and normalizes the period column to `yearmonth` in `YYYY-MM` format.
4. **Builds the master dataset** (`build_master`): left-joins the three sources onto a complete monthly index spanning `YEAR_START`–`YEAR_END`, keeps months missing in a source as `NaN`, and trims to `END_MONTH`.
5. **Runs diagnostics** (`print_diagnostics`): `NaN` counts per column, `frac_*` columns in `[0, 1]`, `n_large + n_small + n_ephemeral == n_total`, descriptive statistics.
6. **Saves** the result to `master_monthly.csv`.

> **Pending update.** Step 2 still fills every month without events with `0`, including the months without LASCO observations. The update will merge `lasco_monthly_coverage_TAG.csv`, set the CME counts to `NaN` when `coverage < 0.5`, add coverage-normalised counts (`count_cmes_*_norm` = count / coverage) for the remaining months, keep the raw counts for count models (with `log(coverage)` as offset), and add the new AR variables (total spot area, δ-region area, δ flag). Until then, the 1998–1999 interruptions appear as months with 0 CMEs.

**Output dataset — `master_monthly.csv` (one row per calendar month):**

| Column | Source | Description |
|---|---|---|
| `yearmonth` | — | Period (YYYY-MM) |
| `sunspot_number` | Sunspots | SILSO v2 monthly sunspot number |
| `count_cmes_all` | CMEs | Total CMEs that month (no filter) |
| `count_cmes_normal` | CMEs | CMEs with width 20°–120° |
| `count_cmes_partial_halo` | CMEs | CMEs with width >120°–<360° |
| `count_cmes_halo` | CMEs | CMEs with width == 360° (full halo) |
| `count_cmes_slow` | CMEs | CMEs with speed 0–600 km/s |
| `count_cmes_moderate` | CMEs | CMEs with speed 600–1000 km/s |
| `count_cmes_fast` | CMEs | CMEs with speed 1000–1500 km/s |
| `count_cmes_extreme` | CMEs | CMEs with speed ≥ 1500 km/s |
| `count_cmes_filtered` | CMEs | CMEs meeting the combined speed AND width filter |
| `n_total` | AR Features | Active regions in the month (region-months) |
| `n_high_complexity` | AR Features | ARs with peak complexity ≥ 4 (βγ, γ, γδ, βγδ). The committed CSV names this column `n_alta_complejidad` |
| `complexity_area_sum` | AR Features | Sum of `complexity × area` across all daily observations |
| `n_large` | AR Features | ARs visible ≥ 7 days |
| `n_small` | AR Features | ARs visible 2–6 days |
| `n_ephemeral` | AR Features | ARs visible ≤ 1 day |

**Configuration:**

| Constant | Description | Default |
|---|---|---|
| `CME_FILE` | Path to the processed CME table | `../cme/datos_procesados_2026_07_31.csv` |
| `SUNSPOT_FILE` | Path to the SILSO sunspot-number file | `../sunspot_number/SN_m_tot_V2.0.txt` |
| `AR_FILE` | Path to the AR features CSV | `../active_regions/ar_features_monthly.csv` |
| `OUTPUT_FILE` | Output master CSV path | `master_monthly.csv` (this folder) |
| `YEAR_START` / `YEAR_END` | Date range for the master index | `1996` / `2026` |
| `END_MONTH` | Final cutoff month for the output | `2026-02` |
| `MIN_SPEED` | Minimum CME speed (km/s) for `count_cmes_filtered` | `750` |
| `MIN_WIDTH` / `MAX_WIDTH` | Angular width range (degrees) for `count_cmes_filtered` | `120` / `360` |

The script reads its configuration from these constants (no CLI arguments). To use a new catalog, set `CME_FILE` to `datos_procesados_TAG.csv` and `END_MONTH` to the last month covered by **all** sources (CDAW, SRS and SILSO).
