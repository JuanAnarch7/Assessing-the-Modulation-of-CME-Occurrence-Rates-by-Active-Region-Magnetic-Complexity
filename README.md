# CME – Active Region & Correlation Analysis

This repository studies the statistical relationship between solar **Active
Region (AR)** characteristics and **Coronal Mass Ejection (CME)**
subpopulations across Solar Cycles 23, 24, and 25 (1996–2026), as part of a
CME annual/monthly forecasting project.

The work is split into two folders, matching two stages of the pipeline:

```
repo/
├── data/                   → Acquisition, preprocessing, feature engineering,
│                              and monthly aggregation (produces master_monthly.csv)
└── correlation_analysis/   → Spearman correlation, solar-cycle phase, and
                               lag analysis (consumes master_monthly.csv)
```

## Pipeline overview

```
1. Data Acquisition        → Retrieve CME catalog (SOHO/LASCO) and AR data (NOAA SRS)
2. Data Preprocessing      → Clean, parse, and standardize each raw source
3. Feature Engineering     → Derive CME subpopulations and AR-based variables,
                              merge into a single dataset
4. Monthly Aggregation     → Aggregate into monthly counts per CME subpopulation
                              and AR category  →  master_monthly.csv
5. Correlation Analysis    → Spearman correlation (full period / per cycle /
                              per cycle phase) and lag analysis (1–12 months)
```

Stages **1–4** are implemented in [`data/`](./data) — see
[`data/README.md`](./data/README.md) for the full breakdown of scripts,
datasets, and data sources.

Stage **5** is implemented in [`correlation_analysis/`](./correlation_analysis)
— see [`correlation_analysis/README.md`](./correlation_analysis/README.md)
for details on each correlation script.

The single hand-off point between the two folders is `master_monthly.csv`:
a monthly table with AR-derived variables and CME subpopulation counts,
produced at the end of `data/` and consumed at the start of
`correlation_analysis/`.

## End-to-end execution order

```bash
# --- data/ : stages 1-4 ---
cd data
python Lecture.py
python noaa_mount_wilson.py --start 1996-01-01 --end 2026-02-28
python ar_features_builder_period_en.py --input mount_wilson_dataset.csv --start 1996-01 --end 2026-02
# download SN_m_tot_V2.0 (1).txt manually from SILSO and place it in data/
python master_dataset_builder_en.py
# -> produces data/master_monthly.csv

# --- correlation_analysis/ : stage 5 ---
cd ../correlation_analysis
cp ../data/master_monthly.csv .        # or adjust BASE_DIR / CSV_PATH in each script
python correlation_matrix_periods.py
python correlation_matrix_solar_cycle_phases.py
python correlation_lag_variables.py
```

## Data sources

- **CME data:** [SOHO/LASCO CME Catalog](https://cdaw.gsfc.nasa.gov/CME_list/)
- **Active Region data:** [NOAA/NGDC — Solar Region Summaries](https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/solar_region_summaries/)
- **Sunspot numbers:** [SILSO — Royal Observatory of Belgium](https://www.sidc.be/silso/) (downloaded manually, not included in the repo)

## Requirements

```
pandas
numpy
scipy
matplotlib
requests      # data/ only, for noaa_mount_wilson.py
openpyxl      # optional, correlation_analysis/ only
```

```bash
pip install pandas numpy scipy matplotlib requests openpyxl
```

## Reproducibility

- `data/master_monthly.csv` is included in the repository so that
  `correlation_analysis/` can be reproduced immediately without re-running
  stages 1–4.
- See each folder's README for stage-specific reproducibility notes
  (caching, zero-filling of empty periods, bootstrap seeding, etc.).
