# Master monthly dataset

This folder joins the monthly CME counts, active-region features, flare activity and sunspot number into `master_monthly.csv`, the input of the statistical analysis.

## Contents

| Path | Type | Description |
|---|---|---|
| `master_dataset_builder.py` | script | Builds the master dataset from the other folders of `Data/` |
| `master_monthly.csv` | output | One row per calendar month (1996-01 → 2026-07, 367 months, 103 columns) |
| `master_monthly_columns.csv` | output | Data dictionary: column, source folder, unit, description |

## Quick start

```bash
python Data/master/master_dataset_builder.py                 # defaults: --cme-tag 2026_07_31 --start 1996-01
python Data/master/master_dataset_builder.py --end 2026-06   # force a different last month
```

## Inputs

| Input | Folder | Produced by |
|---|---|---|
| `datos_procesados_TAG.csv`, `lasco_monthly_coverage_TAG.csv` | `../cme/` | `Lecture.py` |
| `ar_features_monthly.csv` | `../active_regions/` | `ar_features_builder.py` |
| `flares_monthly.csv` | `../flares/` | `flares_builder.py` |
| `SN_m_tot_V2.0.csv` (or `.txt`) | `../sunspot_number/` | SILSO (download) |

## Processing steps

1. **CME counts.** Monthly counts of CDAW events by angular width (narrow < 20°, normal 20°–120°, partial halo > 120°–< 360°, full halo 360°), by linear speed (slow 0–600, moderate 600–1000, fast 1000–1500, extreme ≥ 1500 km/s), all CMEs, and the filtered subpopulation (speed ≥ 750 km/s and width 120°–360°). Definitions are identical to the previous master (narrow CMEs are new). Each count is also given for events of normal CDAW quality only (`_hq`, excluding "Poor" and "Very Poor").
2. **LASCO coverage.** Months with coverage < 0.5 (1998-07, 1998-08, 1998-09, 1999-01: no observations) get `NaN` in every CME count. For partially observed months (37 months with 0.5 ≤ coverage < 1), `*_norm` = count / coverage gives the coverage-corrected rate. Raw counts are kept for count models, which should use `log(lasco_coverage)` as offset.
3. **Sunspot number.** SILSO monthly mean, its standard deviation and provisional flag; `sn13` = 13-month smoothed value (SILSO formula, computed on the full SILSO series, so it is defined from 1996-01; the last 6 months of the SILSO file have no `sn13`).
4. **Solar cycle and phases.** `solar_cycle` changes at the SN13 minima (1996-08, 2008-12, 2019-12; when the minimum value repeats, the last month at the minimum is taken). Two phase definitions:
   - `phase_sn13`: maximum = first to last month with SN13 ≥ 0.8 × the cycle maximum; rising before, declining after;
   - `phase_repo`: the hand-set limits used by the previous analysis scripts (cycle 25 maximum ending 2025-12; no declining phase for cycle 25).
5. **Active-region and flare features** are merged as produced by their builders (`n_usable_days` is renamed `srs_usable_days`, `scale_published` is renamed `goes_scale_published`).
6. **End month.** The last month covered by all sources (here: CDAW 2026-07, SRS 2026-07, flares 2026-07, SILSO 2026-09 → 2026-07), unless `--end` is given.
7. **Flags and diagnostics** (below).

### Solar-cycle reference (SN13)

| Cycle | Minimum (start) | Maximum | SN13 max | Maximum phase (`phase_sn13`) |
|---|---|---|---|---|
| 23 | 1996-08 | 2001-11 | 180.3 | 1999-09 → 2002-09 |
| 24 | 2008-12 | 2014-04 | 116.4 | 2012-01 → 2014-11 |
| 25 | 2019-12 | 2024-10 | 160.9 | 2023-12 → 2025-04 |

The cycle 25 maximum (2024-10, SN13 = 160.9) agrees with the value announced by SIDC/SILSO.

## Columns

The full list, with units and descriptions, is in `master_monthly_columns.csv`. Groups:

| Group | Columns | Source |
|---|---|---|
| Time and cycle | `yearmonth`, `solar_cycle`, `phase_sn13`, `phase_repo` | master |
| Sunspot number | `sunspot_number`, `sunspot_number_sd`, `sunspot_provisional`, `sn13` | `sunspot_number/` |
| CME counts | `count_cmes_{all, narrow, normal, partial_halo, halo, slow, moderate, fast, extreme, filtered}` and their `_hq`, `_norm`, `_hq_norm` versions | `cme/` |
| LASCO coverage | `lasco_coverage`, `lasco_gap_days` | `cme/` |
| Active regions | `srs_usable_days`, `n_days`, `srs_coverage`, `n_regions`, `n_new_regions`, `n_high_complexity`, `n_delta`, `n_{long,mid,short}_lived`, `area_*`, `complexity_area_sum`, `*_daily_mean`, `frac_delta_area` | `active_regions/` |
| Flares | `n_flares_{C,M,X,MX}`, `flare_index`, `flare_index_MX`, `max_flux_classic`, `n_MX_*`, `frac_MX_*`, `goes_scale_published` | `flares/` |
| Flags | `flag_*` (below) | master |

### Flags

| Flag | Meaning | Months |
|---|---|---|
| `flag_no_lasco` | LASCO coverage < 0.5: CME counts are NaN | 4 |
| `flag_partial_lasco` | 0.5 ≤ coverage < 1: use `*_norm` counts or a coverage offset | 37 |
| `flag_srs_incomplete` | SRS coverage < 0.9: use `*_daily_mean` area features | 3 |
| `flag_sunspot_provisional` | SILSO value still provisional | 1 (2026-07) |
| `flag_flare_region_gap` | > 50 % of the month's M/X flares (≥ 3) have no NOAA region: region-based flare features unreliable | 70 |

### Which columns to use

- **CME rates:** `count_cmes_*_norm` for correlations; raw `count_cmes_*` with `log(lasco_coverage)` as offset in count models. Repeat with `_hq` to test the effect of low-quality CDAW events.
- **Active-region areas:** `*_daily_mean` (insensitive to missing SRS reports) rather than the raw sums.
- **Cycle trend:** `sn13`; phases from `phase_sn13` (objective) or `phase_repo` (previous analysis).
- **Flares:** counts and flare index are reliable for the whole period; region-based flare columns should be used only in months without `flag_flare_region_gap`.

## Changes with respect to the previous `master_monthly.csv`

| Previous column | Current column |
|---|---|
| `n_total` | `n_regions` |
| `n_alta_complejidad` / `n_high_complexity` | `n_high_complexity` |
| `n_large` | `n_long_lived` |
| `n_small` | `n_mid_lived` |
| `n_ephemeral` | `n_short_lived` |

CME count columns keep their names. For 1996-01 → 2026-02 they are identical to the previous master except: the four months without LASCO observations (now NaN instead of 0), and one month in which a CDAW revision moved one CME between the partial-halo and full-halo classes. The analysis scripts in `../../Correlation analysis/` still use the previous active-region names and will be updated in the pipeline refactor.

## Diagnostics printed by the builder

End month and the last complete month of each source; months without or with partial LASCO coverage; SILSO provisional months; SN13 minima, maxima and phase lengths; consistency checks (width classes ≤ all CMEs, persistence classes = `n_regions`, `_hq` ≤ all); number of months per flag; columns with missing values.
