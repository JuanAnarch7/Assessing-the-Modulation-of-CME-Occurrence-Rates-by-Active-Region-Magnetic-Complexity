# Active regions (NOAA Solar Region Summaries)

This folder builds the daily active-region dataset from the NOAA Solar Region Summaries (SRS) and aggregates it into annual, monthly and weekly active-region features.

## Contents

| Path | Type | Description |
|---|---|---|
| `noaa_mount_wilson.py` | script | Downloads and parses the daily SRS reports |
| `ar_features_builder.py` | script | Aggregates the region records into period features |
| `mount_wilson_dataset.csv` | output | One row per region per observation day (1996-01-01 → 2026-07-31) |
| `mount_wilson_summary.csv` | output | One row per observation day with regions |
| `srs_day_status.csv` | output | Status of every requested SRS report (usable vs missing days) |
| `ar_features_{annual,monthly,weekly}.csv` | output | Period features (counts, complexity, δ, areas, persistence) |
| `srs_cache/` | cache, not versioned | Downloaded SRS files, one per day |

## Quick start

```bash
cd Data/active_regions
python noaa_mount_wilson.py --start 1996-01-01 --end 2026-08-01
python ar_features_builder.py --start 1996-01 --end 2026-07
```

Ending the SRS download on 2026-08-01 gives the observation day 2026-07-31 (the report issued on day D describes day D − 1).

## Reference values (SRS run of 2026-10-24, 1996-01-01 → 2026-08-01)

| Quantity | Value |
|---|---|
| Report dates | 11 171: parsed 9 162, no_regions 1 960, missing_404 42, no_section_I 4, empty_section 2, superseded 1 |
| Observation-date source | header 11 124, assumed 47 (all of them missing or unreadable reports) |
| Unparsed lines in Section I | 0 |
| Region records | 46 296 (2 with unknown magnetic type, 5 with blank spot count) |
| Unique regions (`noaa_full`) | 6 540 |
| δ configurations | 1 880 region-days |
| Monthly features | 367 months; 0 months without usable days; 3 months with SRS coverage < 0.9 (1996-12, 1997-03, 1997-04) |
| Region-months (`n_regions` summed) | 7 871 |

Reports to inspect by hand (`no_section_I` / `empty_section`, treated as missing): 1996-05-09, 1996-11-25, 2004-09-22, 2019-08-04, 2019-08-07, 2019-10-11.

## Source

[NOAA/NGDC — Solar Region Summaries (SRS)](https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/solar_region_summaries/), downloaded automatically by `noaa_mount_wilson.py`.

## `noaa_mount_wilson.py`

Downloads (or reads from the local cache) one SRS report per day, parses Section I ("Regions with Sunspots"), and writes one row per active region per observation day, plus a record of what happened with every requested report.

**Usage**

```bash
python noaa_mount_wilson.py --start 1996-01-01 --end 2026-07-31
```

| Argument | Description | Default |
|---|---|---|
| `--start` | First report date (YYYY-MM-DD) | `1996-01-01` |
| `--end` | Last report date (YYYY-MM-DD) | today |
| `--output` | Region-level dataset | `mount_wilson_dataset.csv` |
| `--summary` | Daily summary | `mount_wilson_summary.csv` |
| `--status` | Status of every report date | `srs_day_status.csv` |

Requirements: `pandas`, `requests`; `tqdm` optional (progress bar).

**Processing steps**

1. **Download with cache.** Each report is read from `srs_cache/YYYY/YYYYMMDDSRS.txt` if present; otherwise it is downloaded. HTTP 404 is recorded as `missing_404`. Network errors and HTTP 5xx are retried 3 times with exponential back-off and recorded as `network_error` / `http_<code>`; failed downloads are not cached, so a later run retries them.
2. **Section I parsing.** Lines between the `I.  Regions with Sunspots` header and the next section (`IA.` or `II.`; some reports write `1.` / `1A.` with the digit one, which is also accepted) are matched against the fixed-column pattern `Nmbr Location Lo Area Z LL NN Mag Type`. In a few reports `NN` or `Mag Type` is blank: the region is kept with `nn = NaN` or `mag_type = Unknown` (`complexity = NaN`). A line reading `None` marks a day without spotted regions. Lines that do not match the pattern are counted and the first one is kept as an example (not silently dropped).
3. **Observation date.** The SRS issued on day *D* at 00:30 UT gives positions valid at 24:00 UT of day *D − 1* (`Locations Valid at DD/2400Z`). `date` is the observation date read from that header (`date_source = header`); if the header cannot be read, `date` = report date − 1 day (`date_source = assumed`). The report date is kept in `report_date`. *The previous version stored the report date in `date`, one day late.*
4. **Full NOAA number.** The SRS prints region numbers modulo 10 000 (9999 was followed by 0000 in June 2002; region 14466 appears as `4466`). `noaa_full` adds 10 000 to numbers below 9000 observed after 2002-06-01, so regions can be matched with external catalogs (e.g. NOAA flare lists). Within 1996–2026 the printed numbers do not collide, so `noaa_number` still identifies regions uniquely.
5. **Normalisation.** Mount Wilson types are case-insensitive (`Beta` and `BETA` both occur) and mapped to α, β, βδ, βγ, γ, γδ, βγδ with the ordinal complexity scale below; partial matches try the longest names first. McIntosh classes are normalised to `Zpc` case (the SRS used upper case for the 2nd letter until 2000) and split into their three components. `is_delta` flags δ configurations.
6. **Duplicate observation days.** If two reports describe the same observation day, the report issued the day after it is kept (otherwise the latest), and the other is marked `superseded`, so that regions are not counted twice.
7. **Outputs and report.** The script writes the three CSV files and prints the count of report dates by status, the source of the observation dates, reports with unparsed lines, download errors, and the distribution of magnetic types.

**Generated datasets**

| File | One row per | Description |
|---|---|---|
| `mount_wilson_dataset.csv` | Region per observation day | Region records (columns below) |
| `mount_wilson_summary.csv` | Observation day with regions | Counts, total area, complexity, δ regions |
| `srs_day_status.csv` | Requested report date | File status and parsing diagnostics (below) |

**Columns in `mount_wilson_dataset.csv`:**

| Column | Description |
|---|---|
| `date` | Observation date (YYYY-MM-DD): positions valid at 24:00 UT of this day |
| `report_date` | Issue date of the SRS file |
| `date_source` | `header` (read from "Valid at DD/2400Z") or `assumed` (report date − 1) |
| `noaa_number` | Region number as printed (4 digits, modulo 10 000) |
| `noaa_full` | Full NOAA region number |
| `location` | Heliographic position (e.g. N14E23) |
| `lat`, `lon` | Latitude and central-meridian distance in degrees (north and west positive) |
| `lo` | Carrington longitude |
| `area` | Spot area in millionths of the solar hemisphere |
| `z_class` | McIntosh class, normalised case (e.g. `Ekc`) |
| `mcintosh_z`, `mcintosh_p`, `mcintosh_c` | Zurich class, penumbra of the largest spot, spot distribution |
| `ll` | Longitudinal extent (degrees) |
| `nn` | Number of sunspots |
| `mag_type_raw` | Magnetic type as printed in the report |
| `mag_type` | Normalised magnetic type (α, β, βγ, βγδ...) |
| `complexity` | Ordinal complexity value (1–5) |
| `is_delta` | δ configuration (βδ, γδ, βγδ) |

**Columns in `srs_day_status.csv`:**

| Column | Description |
|---|---|
| `report_date` | Requested report date |
| `file_status` | `parsed` (≥ 1 region), `no_regions` (report says `None`: a real zero), `empty_section` (Section I found but no regions and no `None`), `no_section_I`, `superseded` (another report covers the same observation day), `missing_404`, `network_error`, `http_<code>` |
| `obs_date` | Observation date of the report |
| `date_source` | `header` or `assumed` |
| `n_regions` | Regions parsed |
| `n_unparsed` | Lines in Section I that did not match the pattern |
| `unparsed_example` | First unmatched line |

Use `file_status` to tell days without spotted regions (`no_regions`) from days without data (`missing_404`, errors). In the previous dataset both appeared simply as absent days: 2 008 days were absent between 1996-01-02 and 2026-06-11, of which 38 fall in months with a monthly sunspot number above 40 (e.g. 2001-08-28, 2024-04-21) and cannot be spotless.

**Mount Wilson complexity scale:**

| Type | Value |
|---|---|
| α (Alpha) | 1 |
| β (Beta) | 2 |
| βδ (Beta-Delta) | 3 |
| βγ (Beta-Gamma) / γ (Gamma) | 4 |
| γδ (Gamma-Delta) / βγδ (Beta-Gamma-Delta) | 5 |

> The placement of βδ (3) below βγ (4) is under review: δ configurations are the most flare-productive. The scale is unchanged for now; `is_delta` allows δ regions to be analysed separately.

**Main functions:** `download_srs()` (cache, retries, status), `parse_srs()` (Section I, observation date, diagnostics), `observation_date()`, `full_noaa_number()`, `normalize_mag_type()`, `normalize_mcintosh()`, `parse_location()`, `build_dataset()`, `build_summary()`, `print_report()`.

## `ar_features_builder.py` — Period-based Active Region Features

Builds annual, monthly and weekly active-region features from the outputs of `noaa_mount_wilson.py`.

**Usage**

```bash
python ar_features_builder.py --input mount_wilson_dataset.csv --status srs_day_status.csv \
    --start 1996-01 --end 2026-07 [--outdir .]
```

| Argument | Description | Default |
|---|---|---|
| `--input` | Region-level dataset | `mount_wilson_dataset.csv` |
| `--status` | Day status file (usable vs missing days) | `srs_day_status.csv` |
| `--start` / `--end` | First / last month (YYYY-MM) | `1996-01` / `2026-07` |
| `--outdir` | Output folder | this folder (`Data/active_regions/`) |

**Processing steps**

1. **Region identity and persistence.** Regions are identified by `noaa_full`. Persistence = days between the first and last observation of the region in the whole dataset (+1). Since the SRS lists only regions with spots on the Earth-facing disk, persistence measures visibility (at most ~14–16 days per passage), not physical lifetime. Classes: short-lived (≤ 1 day), mid-lived (2–6 days), long-lived (≥ 7 days).
2. **Usable days.** A day is usable when its report is `parsed` or `no_regions` (a real zero). `missing_404`, download errors, `no_section_I` and `empty_section` are missing data; `superseded` reports are ignored. Without a status file, days without regions are assumed spotless (with a warning).
3. **Counts per period.** Each region contributes once to every period in which it is observed (*region-periods*), with its peak complexity and whether it showed a δ configuration in that period. `n_new_regions` counts regions first seen in the period, so its sum over all periods equals the number of unique regions.
4. **Area sums per period.** Sums over daily observations of total area, δ-region area, complex-region area (complexity ≥ 4), area at |central-meridian distance| ≤ 45° (centre) and > 45° (limb), and Φ_proxy = Σ complexity × area (records with unknown magnetic type are excluded from Φ_proxy). Each sum also has a `_daily_mean` version (sum / usable days), which is insensitive to missing reports and should be used in the analysis.
5. **Missing periods.** Periods with usable days but no regions get 0; periods without any usable day get `NaN` in every feature.
6. **Checks.** `n_long_lived + n_mid_lived + n_short_lived == n_regions` in every period; the script prints the number of periods without usable days and with SRS coverage < 0.9.

**Columns of `ar_features_{annual,monthly,weekly}.csv`**

| Column | Description |
|---|---|
| `year` / `yearmonth` / `yearweek` | Period |
| `n_usable_days`, `n_days`, `srs_coverage` | Usable SRS days, calendar days, and their ratio |
| `n_regions` | Regions observed in the period (region-periods) |
| `n_new_regions` | Regions first observed in the period (unique regions) |
| `n_high_complexity` | Regions with peak complexity ≥ 4 (βγ, γ, γδ, βγδ) |
| `n_delta` | Regions with a δ configuration in the period (βδ, γδ, βγδ) |
| `n_long_lived`, `n_mid_lived`, `n_short_lived` | Regions by persistence class |
| `area_sum` | Σ daily spot area (millionths of hemisphere × days) |
| `area_delta`, `area_complex` | Σ daily area of δ regions / of regions with complexity ≥ 4 |
| `area_center`, `area_limb` | Σ daily area at \|lon\| ≤ 45° / > 45° |
| `complexity_area_sum` | Φ_proxy = Σ daily complexity × area |
| `*_daily_mean` | Each area sum divided by `n_usable_days` |
| `frac_delta_area` | `area_delta / area_sum` |

**Renamed columns** (previous → current): `n_total` → `n_regions`; `n_large` → `n_long_lived`; `n_small` → `n_mid_lived`; `n_ephemeral` → `n_short_lived`. The analysis scripts in `../../Correlation analysis/` still use the previous names and will be updated in the pipeline refactor.

**Configuration constants:** `THRESH_SHORT` (1 day), `THRESH_LONG` (7 days), `HIGH_COMPLEXITY` (4), `CENTER_LON` (45°).

> **Counting unit.** A region observed across a month boundary is counted in both months. Monthly counts are therefore *region-months* (7 871 over 1996-01 → 2026-07), whereas `n_new_regions` counts unique regions (6 540).
