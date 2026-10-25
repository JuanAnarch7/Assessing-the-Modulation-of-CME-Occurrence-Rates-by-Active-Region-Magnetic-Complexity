# CME data (SOHO/LASCO CDAW catalog)

This folder turns the raw CDAW CME catalog into a clean event table, documents the periods without coronagraph observations, and gives the monthly observing coverage used by the master dataset.

## Contents

| Path | Type | Description |
|---|---|---|
| `Lecture.py` | script | Reads and cleans the catalog, flags quality and uncertain values, detects observing gaps |
| `raw/Soho_Lasco_YYYY_MM_DD.txt` | raw input | CDAW text catalog, named with its download date (current: 2026-07-31) |
| `datos_procesados_TAG.csv` | output | One row per CME (column dictionary below) |
| `lasco_gaps_TAG.csv` | output | One row per detected observing gap |
| `lasco_monthly_coverage_TAG.csv` | output | Fraction of each month covered by observations |

`TAG` is the CDAW download date (e.g. `2026_07_31`), so every derived file can be traced to the catalog version that produced it.

## Quick start

```bash
cd Data/cme
python Lecture.py --input raw/Soho_Lasco_2026_07_31.txt --tag 2026_07_31
```

Then check the printed report against the [reference values](#reference-values-catalog-downloaded-on-2026-07-31).

## Source: SOHO/LASCO CDAW catalog

- Source: [SOHO/LASCO CME Catalog, CDAW Data Center (NASA/GSFC)](https://cdaw.gsfc.nasa.gov/CME_list/).
- Format: plain text, one CME per line, whitespace-separated, no header. Each line has 12 fixed fields followed by free-text remarks:

| # | Field (CDAW) | Example | Notes |
|---|---|---|---|
| 1 | Date | `1996/01/22` | UT, first appearance in the LASCO C2 field of view |
| 2 | Time | `03:11:01` | UT |
| 3 | Central position angle (CPA) | `105` or `Halo` | degrees, counter-clockwise from solar north; `Halo` for full halos |
| 4 | Angular width | `37` | degrees; `360` for full halos |
| 5 | Linear speed | `267` | km/s, linear fit to height–time points; `----` if not measured |
| 6 | 2nd-order speed, initial | `401` | km/s, at first height |
| 7 | 2nd-order speed, final | `130` | km/s, at last height |
| 8 | 2nd-order speed at 20 R☉ | `0` | km/s; CDAW writes `0` when it cannot be computed |
| 9 | Acceleration | `-126.3*` | m/s²; `*` = uncertain (only 3 height–time points or poor fit) |
| 10 | Mass | `7.1e+13*` | g; `-------` if not measured; `*` = uncertain |
| 11 | Kinetic energy | `2.5e+28*` | erg; same conventions as mass |
| 12 | Measurement position angle (MPA) | `103` | degrees, angle at which the height–time measurements were made |
| 13+ | Remarks | `Very Poor Event; Only C3` | free text, several items separated by `;` |

- The catalog is revised by CDAW over time (e.g. remarks such as `Fixed the MVI roll angle issue on 2026-01-30` or `Newly inserted on 2024/05/01.`). **Always record the download date**: two downloads of the same period may differ.

## `Lecture.py`

Reads the raw CDAW text catalog, cleans it, flags data quality and uncertain values, and documents the periods without coronagraph observations.

**Usage**

```bash
python Lecture.py --input raw/Soho_Lasco_2026_07_31.txt --tag 2026_07_31 [--outdir .]
```

| Argument | Description | Default |
|---|---|---|
| `--input` | Path to the raw CDAW `.txt` catalog (required) | — |
| `--tag` | Suffix of the three output files; use the catalog download date | `2026_02_28` |
| `--outdir` | Output folder | this folder (`Data/cme/`) |

Requirements: Python ≥ 3.8, `numpy`, `pandas`.

**Processing steps**

1. **Line selection.** Only lines that start with a date (`YYYY/MM/DD HH:MM:SS`) are parsed; headers and blank lines are skipped.
2. **Field parsing.** The first 10 whitespace-separated tokens after date and time are the numeric fields 3–12 of the table above; everything after them is kept as the full remarks string. (The previous version split the remarks on spaces and kept only the first word, so `Very Poor Event; Only C2` became `Very` and `Only C2; Poor Event` became `Only`.)
3. **Missing and flagged values.**
   - Tokens made only of dashes (`----`, `-------`) → `NaN`.
   - A trailing `*` marks an uncertain value: the number is kept and a boolean flag is set (`accel_uncertain` for acceleration; `mass_uncertain` if mass or kinetic energy carries `*`). The previous version turned these values into `NaN`.
   - `Halo` in the CPA field → `Central = NaN` and `is_halo = True`.
   - Second-order speeds equal to `0` (not computable in CDAW) → `NaN`.
4. **Malformed lines.** A dated line with fewer than 10 numeric fields is not parsed; it is reported with its line number at the end of the run (none in the 2026-07-31 catalog).
5. **Derived columns.** `t` = date + time as a timestamp; `quality` from the remarks (`very_poor` if they contain "Very Poor", else `poor` if they contain "Poor", else `normal`); `only_c2` if the remarks contain "Only C2". Events are sorted by `t`.
6. **Observing-gap detection.** CMEs are recorded only when LASCO observes, so an empty interval can mean either "no CMEs" or "no data". For each interval of at least `GAP_MIN_DAYS` (3 days) between consecutive CMEs:
   - the local CME rate λ is estimated from the events in the `RATE_WINDOW` (30 days) before and after the interval, excluding the interval itself;
   - the probability of seeing no CME during the interval length Δt is computed as p = exp(−λ·Δt) (Poisson);
   - the interval is flagged as an observing gap if p < `GAP_P` (10⁻⁶).

   The threshold is deliberately strict: CMEs are clustered in time, so short lulls are more frequent than a Poisson process predicts (with p < 10⁻³ about 100 intervals of 2–3 days were flagged, most of them natural lulls). The months without coverage (below) are the same for any threshold between 10⁻³ and 10⁻⁹.
7. **Monthly coverage.** For each calendar month, `coverage` = 1 − (days of the month inside flagged gaps) / (days in the month).
8. **Report.** The script prints the number of events, malformed lines, halos, quality counts, missing speeds, uncertain values, the list of gaps and the months with coverage < `MIN_COVERAGE` (0.5).

**Configuration constants** (top of the script)

| Constant | Meaning | Default |
|---|---|---|
| `GAP_P` | Poisson probability below which an empty interval is flagged as a gap | `1e-6` |
| `GAP_MIN_DAYS` | Minimum interval length tested (days) | `3.0` |
| `RATE_WINDOW` | Days on each side used to estimate the local CME rate | `30.0` |
| `MIN_COVERAGE` | Coverage threshold reported, and suggested for the monthly builder | `0.5` |

### Columns of `datos_procesados_TAG.csv`

Legacy Spanish names are kept for compatibility with `../master/master_dataset_builder.py`; new columns are in English. Names will be unified in the planned pipeline refactor.

| Column | Type | Description |
|---|---|---|
| `Fecha` | date (YYYY-MM-DD) | Date of first appearance in C2 (UT) |
| `Hora` | time (HH:MM:SS) | Time of first appearance in C2 (UT) |
| `Central` | float, degrees | Central position angle; `NaN` for full halos |
| `Ancho` | float, degrees | Angular width; 360 for full halos |
| `Rapidez` | float, km/s | Linear speed; `NaN` if not measured |
| `Col4` | float, km/s | Second-order speed at the first height |
| `Col5` | float, km/s | Second-order speed at the last height |
| `Col6` | float, km/s | Second-order speed at 20 R☉; `NaN` when CDAW gives 0 |
| `Aceleracion` | float, m/s² | Acceleration (see `accel_uncertain`) |
| `Masa` | float, g | Mass (see `mass_uncertain`) |
| `Energia` | float, erg | Kinetic energy (see `mass_uncertain`) |
| `MPA` | float, degrees | Measurement position angle |
| `Comentarios` | text | Full CDAW remarks |
| `is_halo` | bool | CPA field was `Halo` |
| `accel_uncertain` | bool | Acceleration carried `*` in CDAW |
| `mass_uncertain` | bool | Mass or kinetic energy carried `*` |
| `t` | timestamp | `Fecha` + `Hora` |
| `quality` | `normal` / `poor` / `very_poor` | From the remarks ("Poor Event", "Very Poor Event") |
| `only_c2` | bool | Remarks contain "Only C2" (not tracked in C3) |

### Columns of `lasco_gaps_TAG.csv`

| Column | Description |
|---|---|
| `start`, `end` | Timestamps of the last CME before and the first CME after the gap |
| `days` | Gap length (days) |
| `local_rate_per_day` | CME rate around the gap (CMEs/day, ±30 days) |
| `p_no_cme` | Poisson probability of no CME in the interval at that rate |

### Columns of `lasco_monthly_coverage_TAG.csv`

| Column | Description |
|---|---|
| `yearmonth` | Calendar month (YYYY-MM) |
| `coverage` | Fraction of the month with observations (0–1) |
| `gap_days` | Days of the month inside flagged gaps |

### Reference values: catalog downloaded on 2026-07-31

| Quantity | Value |
|---|---|
| Events | 43 440 (1996-01-11 → 2026-07-31) |
| Events up to 2026-02-28 | 42 744 (identical to the previous processed file) |
| Malformed lines | 0 |
| Full halos | 1 033 (`Halo` CPA = width 360°) |
| Quality | normal 15 841 (36 %), poor 14 948 (34 %), very poor 12 651 (29 %) |
| Linear speed missing | 119 |
| Acceleration missing / uncertain | 740 / 35 335 |
| Mass missing | 13 333 |
| Mass or kinetic energy uncertain | 5 200 |
| Second-order speed at 20 R☉ not computable | 10 432 |
| Observing gaps detected | 31 (318.5 days in total) |
| Months with coverage < 0.5 | 1998-07, 1998-08, 1998-09, 1999-01 (coverage 0) |

The two largest gaps are 1998-06-24 → 1998-10-15 (113 days, loss of contact with SOHO) and 1998-12-20 → 1999-02-05 (47 days). The remaining 29 gaps last 3–12 days, mostly in 1999–2002 and 2003–2004; they should be checked against the CDAW data-gap notes.

**Data quality depends strongly on the CME subpopulation** (2026-07-31 catalog):

| Subpopulation | n | normal | poor | very poor |
|---|---|---|---|---|
| All | 43 440 | 36 % | 34 % | 29 % |
| Width < 20° | 12 254 | 13 % | 30 % | 57 % |
| Width 20°–120° | 27 261 | 40 % | 39 % | 21 % |
| Partial halo (120°–359°) | 2 892 | 82 % | 15 % | 3 % |
| Full halo (360°) | 1 033 | 87 % | 12 % | 1 % |
| Speed ≥ 1000 km/s | 1 036 | 91 % | 6 % | 2 % |
| Speed ≥ 750 km/s and width ≥ 120° | 1 246 | 96 % | 4 % | 0 % |

The fraction of `normal` events also changes over time (about 15 % in 1996, 68 % in 2002, 11 % in 2008, 38 % in 2023). Analyses of the narrow/slow population should therefore be repeated without `poor` and `very_poor` events.
