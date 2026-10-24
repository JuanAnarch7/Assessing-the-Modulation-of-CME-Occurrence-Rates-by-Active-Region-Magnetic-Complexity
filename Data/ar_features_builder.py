"""
=============================================================================
AR Features Builder — Period-based Active Region Features
=============================================================================
Builds annual, monthly and weekly active-region (AR) features from the
outputs of noaa_mount_wilson.py:

  mount_wilson_dataset.csv  one row per region per observation day
  srs_day_status.csv        status of every SRS report (which days are usable)

Counting rules
  - Regions are identified by `noaa_full` (full NOAA number).
  - A region contributes once to each period in which it is observed
    (region-periods), with its PEAK complexity in that period.
  - Persistence = days between the first and last observation of the region
    in the whole dataset (+1). It measures how long the region is visible
    with spots on the Earth-facing disk (at most ~14–16 days per passage),
    not its physical lifetime.
  - Area-type features are sums over daily observations. Because periods can
    miss a few SRS reports, each area sum also has a daily-mean version
    (sum / number of usable days), which is the one to use in the analysis.

Usable days and missing data
  - A day is usable when its report is `parsed` (regions listed) or
    `no_regions` (report says "None": a real zero).
  - `missing_404`, download errors, `no_section_I` and `empty_section` are
    treated as missing (unknown), not as zero.
  - A period with no usable day gets NaN in every feature (not 0).

Outputs: ar_features_annual.csv, ar_features_monthly.csv, ar_features_weekly.csv

Usage:
  python ar_features_builder.py --input mount_wilson_dataset.csv \
      --status srs_day_status.csv --start 1996-01 --end 2026-07
=============================================================================
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

THRESH_SHORT = 1        # persistence_days <= 1  -> short-lived
THRESH_LONG = 7         # persistence_days >= 7  -> long-lived (2–6 days -> mid-lived)
HIGH_COMPLEXITY = 4     # peak complexity >= 4: βγ, γ, γδ, βγδ
CENTER_LON = 45         # |central-meridian distance| <= 45° -> disk centre, else limb

USABLE = {"parsed", "no_regions"}

DEFAULT_START = "1996-01"
DEFAULT_END = "2026-07"

PERIODS = {"annual": ("Y", "year"), "monthly": ("M", "yearmonth"), "weekly": ("W", "yearweek")}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_regions(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    if "noaa_full" not in df.columns:   # backward compatibility with the old dataset
        df["noaa_full"] = df["noaa_number"]
    if "is_delta" not in df.columns:
        df["is_delta"] = df["mag_type"].astype(str).str.contains("δ")

    life = df.groupby("noaa_full")["date"].agg(lambda x: (x.max() - x.min()).days + 1)
    df["persistence_days"] = df["noaa_full"].map(life)
    df["persistence_class"] = np.select(
        [df.persistence_days <= THRESH_SHORT, df.persistence_days >= THRESH_LONG],
        ["short", "long"], default="mid")
    df["compl_x_area"] = df["complexity"] * df["area"]          # NaN if type unknown
    df["area_delta_obs"] = df["area"].where(df["is_delta"], 0)
    df["area_complex_obs"] = df["area"].where(df["complexity"] >= HIGH_COMPLEXITY, 0)
    if "lon" in df.columns:
        df["area_center_obs"] = df["area"].where(df["lon"].abs() <= CENTER_LON, 0)
        df["area_limb_obs"] = df["area"].where(df["lon"].abs() > CENTER_LON, 0)
    return df


def load_usable_days(path: str | None, regions: pd.DataFrame) -> pd.Series:
    """Boolean Series indexed by observation date: True if the day is usable."""
    if path and Path(path).exists():
        st = pd.read_csv(path)
        st = st[st["file_status"] != "superseded"]
        st["obs_date"] = pd.to_datetime(st["obs_date"])
        usable = st.groupby("obs_date")["file_status"].agg(lambda s: s.isin(USABLE).any())
        return usable
    # fallback (old dataset, no status file): days with regions are usable,
    # other days are assumed spotless
    print("  WARNING: no srs_day_status.csv; days without regions are assumed spotless")
    days = pd.date_range(regions["date"].min(), regions["date"].max(), freq="D")
    return pd.Series(True, index=days)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(df: pd.DataFrame, usable: pd.Series, freq: str, col: str,
              start: str, end: str) -> pd.DataFrame:
    d = df.copy()
    d[col] = pd.PeriodIndex(d["date"], freq=freq).astype(str)

    # one row per region and period: peak complexity, δ in the period, class
    per_region = d.groupby([col, "noaa_full"]).agg(
        peak_compl=("complexity", "max"),
        any_delta=("is_delta", "any"),
        persistence_class=("persistence_class", "first"),
        first_seen=("date", "min"),
    ).reset_index()
    first_ever = d.groupby("noaa_full")["date"].min()
    per_region["new_in_period"] = per_region["first_seen"].eq(per_region["noaa_full"].map(first_ever))

    g = per_region.groupby(col)
    out = pd.DataFrame({
        "n_regions": g.size(),
        "n_new_regions": g["new_in_period"].sum(),
        "n_high_complexity": g["peak_compl"].apply(lambda x: int((x >= HIGH_COMPLEXITY).sum())),
        "n_delta": g["any_delta"].sum(),
        "n_long_lived": g["persistence_class"].apply(lambda x: int((x == "long").sum())),
        "n_mid_lived": g["persistence_class"].apply(lambda x: int((x == "mid").sum())),
        "n_short_lived": g["persistence_class"].apply(lambda x: int((x == "short").sum())),
    })

    sums = {"area_sum": "area", "area_delta": "area_delta_obs",
            "area_complex": "area_complex_obs", "complexity_area_sum": "compl_x_area"}
    if "area_center_obs" in d.columns:
        sums.update({"area_center": "area_center_obs", "area_limb": "area_limb_obs"})
    gs = d.groupby(col)
    for name, src in sums.items():
        out[name] = gs[src].sum()

    # usable and total days per period
    days = pd.date_range(f"{start}-01", pd.Period(end, freq="M").end_time.normalize(), freq="D")
    dayinfo = pd.DataFrame({"usable": usable.reindex(days, fill_value=False).to_numpy()}, index=days)
    dayinfo[col] = pd.PeriodIndex(days, freq=freq).astype(str)
    cov = dayinfo.groupby(col)["usable"].agg(n_usable_days="sum", n_days="size")

    full = pd.DataFrame(index=pd.Index(sorted(cov.index), name=col))
    full = full.join(cov).join(out)
    has_data = full["n_usable_days"] > 0
    feat_cols = list(out.columns)
    # periods with usable days but no regions -> 0 ; without usable days -> NaN
    full.loc[has_data, feat_cols] = full.loc[has_data, feat_cols].fillna(0)
    full.loc[~has_data, feat_cols] = np.nan
    full["srs_coverage"] = full["n_usable_days"] / full["n_days"]
    for name in sums:
        full[f"{name}_daily_mean"] = full[name] / full["n_usable_days"].replace(0, np.nan)
    full["frac_delta_area"] = full["area_delta"] / full["area_sum"].replace(0, np.nan)
    return full.reset_index()


# ---------------------------------------------------------------------------
# Checks and main
# ---------------------------------------------------------------------------

def check(table: pd.DataFrame, name: str) -> None:
    s = table["n_long_lived"] + table["n_mid_lived"] + table["n_short_lived"]
    bad = (s != table["n_regions"]) & table["n_regions"].notna()
    print(f"  {name:8s}: rows={len(table):5d}  class-sum check: "
          f"{'OK' if not bad.any() else f'{int(bad.sum())} inconsistent rows'}  "
          f"periods without usable days: {int(table['n_regions'].isna().sum())}  "
          f"periods with SRS coverage < 0.9: {int((table['srs_coverage'] < 0.9).sum())}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build period-based active-region features")
    ap.add_argument("--input", default="mount_wilson_dataset.csv")
    ap.add_argument("--status", default="srs_day_status.csv")
    ap.add_argument("--start", default=DEFAULT_START, help="first month, YYYY-MM")
    ap.add_argument("--end", default=DEFAULT_END, help="last month, YYYY-MM")
    ap.add_argument("--outdir", default=".")
    a = ap.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)

    regions = load_regions(a.input)
    regions = regions[(regions["date"] >= f"{a.start}-01") &
                      (regions["date"] <= pd.Period(a.end, freq="M").end_time)]
    usable = load_usable_days(a.status, regions)
    print(f"Regions: {regions['noaa_full'].nunique()} unique, {len(regions)} region-days "
          f"({regions['date'].min().date()} -> {regions['date'].max().date()})")
    print(f"Records with unknown magnetic type (excluded from Φ_proxy): {int(regions['complexity'].isna().sum())}")

    print("Checks:")
    for name, (freq, col) in PERIODS.items():
        table = aggregate(regions, usable, freq, col, a.start, a.end)
        check(table, name)
        table.to_csv(out / f"ar_features_{name}.csv", index=False,
                     quoting=csv.QUOTE_NONNUMERIC, float_format="%.4f")
    print(f"Saved ar_features_annual/monthly/weekly.csv to {out.resolve()}")


if __name__ == "__main__":
    main()
