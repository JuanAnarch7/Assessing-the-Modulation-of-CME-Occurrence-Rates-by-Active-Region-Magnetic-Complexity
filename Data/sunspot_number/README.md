# Sunspot number (SILSO)

The international sunspot number is used as the solar-cycle reference: its 13-month smoothed value (SN13) is the cycle trend removed or controlled for in the analysis, and SN13 defines the cycle phases.

## Contents

| Path | Type | Description |
|---|---|---|
| `SN_m_tot_V2.0.csv` | raw input | Monthly mean total sunspot number, version 2.0 (1749-01 → 2026-09; 2026-07 to 2026-09 provisional at upload) |

## Source and download

- **Source:** [SILSO — World Data Center for the production, preservation and dissemination of the international sunspot number, Royal Observatory of Belgium](https://www.sidc.be/silso/).
- **File:** monthly mean total sunspot number, CSV version (`SN_m_tot_V2.0.csv`), from the SILSO data files page. The `.txt` version has the same columns separated by spaces.
- **Record the download date** in the commit message: SILSO revises the most recent months (provisional values become definitive).

## Format

Semicolon-separated (`;`), no header, one row per month:

| Column | Description |
|---|---|
| 1 | Year |
| 2 | Month |
| 3 | Date in fraction of year (middle of the month) |
| 4 | Monthly mean total sunspot number (`-1` = missing) |
| 5 | Monthly mean standard deviation of the input sunspot numbers |
| 6 | Number of observations used |
| 7 | Definitive/provisional marker (`1` = definitive, `0` = provisional) |

The master builder reads columns 1, 2, 4 and 7, replaces `-1` with `NaN`, and keeps the provisional marker so that provisional months at the end of the study period can be flagged.
